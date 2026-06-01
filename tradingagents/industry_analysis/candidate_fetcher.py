"""行业分析候选股抓取器。"""

from __future__ import annotations

import asyncio
import importlib.util
import re
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd

try:
    import akshare as ak
except Exception:  # pragma: no cover - 运行环境未安装时允许模块导入
    ak = None

try:
    from app.models.industry_analysis import ConceptMappingResult, StockCandidate
except Exception:
    model_path = Path(__file__).resolve().parents[2] / "app" / "models" / "industry_analysis.py"
    spec = importlib.util.spec_from_file_location("industry_analysis_model_fallback", model_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load industry analysis models from {model_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ConceptMappingResult = module.ConceptMappingResult
    StockCandidate = module.StockCandidate

from tradingagents.utils.logging_manager import get_logger

logger = get_logger("industry_analysis")

_BOARD_CODE_COLUMNS = ("代码", "股票代码", "证券代码", "code", "symbol")
_BOARD_NAME_COLUMNS = ("名称", "股票名称", "证券简称", "name")
_BOARD_INDUSTRY_COLUMNS = ("所属行业", "所处行业", "行业", "industry")

_SPOT_CODE_COLUMNS = ("代码", "股票代码", "证券代码", "code", "symbol")
_SPOT_NAME_COLUMNS = ("名称", "股票名称", "证券简称", "name")
_SPOT_INDUSTRY_COLUMNS = ("所处行业", "所属行业", "行业", "industry")
_SPOT_PRICE_COLUMNS = ("最新价", "现价", "price")
_SPOT_PCT_CHG_COLUMNS = ("涨跌幅", "涨幅", "pct_chg", "changepercent")
_SPOT_PE_COLUMNS = ("市盈率-动态", "市盈率", "PE", "pe")
_SPOT_PB_COLUMNS = ("市净率", "PB", "pb")
_SPOT_TOTAL_MV_COLUMNS = ("总市值", "total_mv")
_SPOT_CIRC_MV_COLUMNS = ("流通市值", "circ_mv", "流通市值(元)")
_SPOT_TURNOVER_COLUMNS = ("换手率", "turnover_rate")
_SPOT_VOLUME_RATIO_COLUMNS = ("量比", "volume_ratio")

_FINANCIAL_DATE_COLUMNS = ("日期", "报告期", "报告日期", "REPORT_DATE", "statDate")
_FINANCIAL_ROE_COLUMNS = ("净资产收益率(%)", "加权净资产收益率(%)", "ROE", "roe")
_FINANCIAL_REVENUE_GROWTH_COLUMNS = (
    "主营业务收入增长率(%)",
    "营业总收入同比增长(%)",
    "营业收入同比增长(%)",
    "营收同比",
    "revenue_growth",
)
_FINANCIAL_PROFIT_GROWTH_COLUMNS = ("净利润增长率(%)", "归母净利润同比增长(%)", "net_profit_growth")
_FINANCIAL_DEBT_RATIO_COLUMNS = ("资产负债率(%)", "资产负债率", "debt_ratio")


@dataclass
class _CandidateSeed:
    code: str
    name: str = ""
    industry: str = ""
    source_boards: set[str] = field(default_factory=set)


class CandidateFetcher:
    """从 AKShare 概念/行业板块抓取候选股并补充基础指标。"""

    def __init__(
        self,
        ak_client: Any | None = None,
        request_delay: float = 0.4,
        financial_enrichment_limit: int = 20,
        data_source_manager: Any | None = None,
    ) -> None:
        self.ak_client = ak_client or ak
        self.request_delay = max(0.0, min(float(request_delay), 1.0))
        self.financial_enrichment_limit = max(int(financial_enrichment_limit), 0)
        self.data_source_manager = data_source_manager

        if self.data_source_manager is None:
            try:
                from tradingagents.dataflows.data_source_manager import get_data_source_manager

                self.data_source_manager = get_data_source_manager()
            except Exception as exc:  # pragma: no cover - 依赖外部环境
                logger.warning("初始化数据源管理器失败，将直接使用 AKShare: %s", exc)
                self.data_source_manager = None

    async def fetch_candidates(self, mapping: ConceptMappingResult) -> list[StockCandidate]:
        """抓取并返回全部候选股，不在此阶段做筛选。"""
        if self.ak_client is None:
            logger.warning("AKShare 未安装或不可用，将跳过板块成分抓取（后续由LLM推荐候选股）")
            return []

        board_pairs = [
            *(('concept', board) for board in mapping.board_concepts),
            *(('industry', board) for board in mapping.board_industries),
        ]
        if not board_pairs:
            logger.info("未提供概念/行业板块，候选股列表为空")
            return []

        logger.info(
            "开始抓取行业分析候选股: user_concept=%s, concept_boards=%s, industry_boards=%s",
            mapping.user_concept,
            len(mapping.board_concepts),
            len(mapping.board_industries),
        )

        seeds: dict[str, _CandidateSeed] = {}
        for board_type, board_name in board_pairs:
            board_df = await self._fetch_board_members(board_name=board_name, board_type=board_type)
            if board_df is None or getattr(board_df, "empty", True):
                continue

            parsed_count = 0
            for seed in self._extract_board_candidates(board_df):
                parsed_count += 1
                existing = seeds.get(seed.code)
                if existing is None:
                    existing = _CandidateSeed(code=seed.code)
                    seeds[seed.code] = existing
                if seed.name and not existing.name:
                    existing.name = seed.name
                if seed.industry and not existing.industry:
                    existing.industry = seed.industry
                existing.source_boards.add(board_name)

            logger.info("板块 %s (%s) 解析完成: %s 只股票", board_name, board_type, parsed_count)

        if not seeds:
            logger.info("所有板块均未返回有效候选股")
            return []

        candidates = [
            StockCandidate(
                code=seed.code,
                name=seed.name,
                industry=seed.industry,
                source_boards=sorted(seed.source_boards),
                match_score=float(len(seed.source_boards)),
            )
            for seed in seeds.values()
        ]

        await self._enrich_with_spot_snapshot(candidates)
        await self._enrich_with_financial_indicators(candidates)

        candidates.sort(key=lambda item: (-item.match_score, item.code))
        logger.info("候选股抓取完成: 共 %s 只", len(candidates))
        return candidates

    async def _fetch_board_members(self, board_name: str, board_type: str) -> Optional[pd.DataFrame]:
        func_name = "stock_board_concept_cons_em" if board_type == "concept" else "stock_board_industry_cons_em"
        fetcher = getattr(self.ak_client, func_name, None)
        if fetcher is None:
            logger.error("AKShare 客户端缺少接口: %s", func_name)
            return None

        try:
            dataframe = await self._call_akshare(fetcher, symbol=board_name)
        except Exception as exc:
            logger.warning("获取%s板块成分失败: %s - %s", board_type, board_name, exc)
            return None

        if dataframe is None or getattr(dataframe, "empty", True):
            logger.warning("%s板块返回空数据: %s", board_type, board_name)
            return None
        return dataframe

    async def _enrich_with_spot_snapshot(self, candidates: list[StockCandidate]) -> None:
        if not candidates:
            return

        # 优先从 MongoDB market_quotes 获取行情数据（与个股分析一致）
        if await self._enrich_from_mongodb(candidates):
            return

        # MongoDB不可用时回退到 AKShare 全市场快照
        if await self._enrich_via_akshare_snapshot(candidates):
            return

        # AKShare 也不可用时，使用 DataSourceManager（含 BaoStock 降级）
        await self._enrich_via_data_source_manager(candidates)

    async def _enrich_via_akshare_snapshot(self, candidates: list[StockCandidate]) -> bool:
        """通过 AKShare 全市场快照批量补充行情数据"""
        fetcher = getattr(self.ak_client, "stock_zh_a_spot_em", None)
        if fetcher is None:
            return False

        try:
            spot_df = await self._call_akshare(fetcher)
        except Exception as exc:
            logger.warning("获取 A 股全市场快照失败: %s", exc)
            return False

        if spot_df is None or getattr(spot_df, "empty", True):
            logger.warning("A 股全市场快照为空")
            return False

        target_codes = {candidate.code for candidate in candidates}
        spot_lookup = self._build_spot_lookup(spot_df, target_codes)
        if not spot_lookup:
            logger.warning("全市场快照中未匹配到候选股票")
            return False

        enriched = 0
        for candidate in candidates:
            payload = spot_lookup.get(candidate.code)
            if not payload:
                continue
            enriched += 1
            if payload.get("name"):
                candidate.name = str(payload["name"])
            if payload.get("industry"):
                candidate.industry = str(payload["industry"])

            for field_name in (
                "pe",
                "pb",
                "total_mv",
                "circ_mv",
                "price",
                "pct_chg",
                "turnover_rate",
                "volume_ratio",
            ):
                value = payload.get(field_name)
                if value is not None:
                    setattr(candidate, field_name, value)

        logger.info("全市场快照补充完成: %s/%s 只候选股命中", enriched, len(candidates))
        return enriched > 0

    async def _enrich_via_data_source_manager(self, candidates: list[StockCandidate]) -> bool:
        """通过 DataSourceManager 逐个获取股票信息（含 BaoStock/Tushare 降级）"""
        if not self.data_source_manager:
            return False

        # 限制数量避免过慢（DataSourceManager 是逐个查询的）
        targets = candidates[:30]
        enriched = 0

        for candidate in targets:
            try:
                info = await asyncio.to_thread(self.data_source_manager.get_stock_info, candidate.code)
            except Exception as exc:
                logger.debug("DataSourceManager获取股票信息失败: %s - %s", candidate.code, exc)
                continue

            if not info or info.get("error"):
                continue

            enriched += 1
            if info.get("name") and not candidate.name:
                candidate.name = str(info["name"])
            if info.get("industry") and not candidate.industry:
                candidate.industry = str(info["industry"])
            if info.get("current_price") is not None:
                candidate.price = _safe_float(info["current_price"])
            if info.get("change_pct") is not None:
                candidate.pct_chg = _safe_float(info["change_pct"])

        if enriched:
            logger.info("DataSourceManager补充完成: %s/%s 只候选股命中", enriched, len(targets))
        return enriched > 0

    async def _enrich_from_mongodb(self, candidates: list[StockCandidate]) -> bool:
        """从 MongoDB market_quotes + stock_basic_info 补充候选股数据（与个股分析一致）"""
        try:
            import os
            from tradingagents.config.database_manager import get_database_manager
            db_manager = get_database_manager()
            if not db_manager or not db_manager.is_mongodb_available():
                return False

            # 使用与 app 层一致的数据库名（MONGODB_DATABASE_NAME）
            db_name = os.getenv("MONGODB_DATABASE_NAME") or db_manager.mongodb_config.get("database", "tradingagents")
            db = db_manager.mongodb_client[db_name]

            quotes_coll = db["market_quotes"]
            basics_coll = db["stock_basic_info"]

            target_codes = {candidate.code for candidate in candidates}

            # 批量查询 market_quotes
            quotes_docs = list(quotes_coll.find({"code": {"$in": list(target_codes)}}))
            quotes_lookup = {doc["code"]: doc for doc in quotes_docs}

            # 批量查询 stock_basic_info
            basics_docs = list(basics_coll.find({"code": {"$in": list(target_codes)}}))
            basics_lookup = {doc["code"]: doc for doc in basics_docs}

            if not quotes_lookup and not basics_lookup:
                logger.info("MongoDB中未找到候选股行情数据，将尝试其他数据源")
                return False

            enriched = 0
            for candidate in candidates:
                quote = quotes_lookup.get(candidate.code)
                basic = basics_lookup.get(candidate.code)

                if basic:
                    if basic.get("name") and not candidate.name:
                        candidate.name = str(basic["name"])
                    if basic.get("industry"):
                        candidate.industry = str(basic["industry"])

                if quote:
                    enriched += 1
                    if quote.get("close") is not None:
                        candidate.price = float(quote["close"])
                    if quote.get("pct_chg") is not None:
                        candidate.pct_chg = float(quote["pct_chg"])
                    if not candidate.name and quote.get("name"):
                        candidate.name = str(quote["name"])

            logger.info("MongoDB行情补充完成: %s/%s 只候选股命中", enriched, len(candidates))
            return enriched > 0

        except Exception as exc:
            logger.warning("从MongoDB补充行情数据失败: %s", exc)
            return False

    async def _enrich_with_financial_indicators(self, candidates: list[StockCandidate]) -> None:
        if not candidates or self.financial_enrichment_limit <= 0:
            return

        targets = sorted(candidates, key=lambda item: (-item.match_score, item.code))[: self.financial_enrichment_limit]

        # Try AKShare first
        fetcher = getattr(self.ak_client, "stock_financial_analysis_indicator", None)
        enriched = 0

        if fetcher is not None:
            for candidate in targets:
                try:
                    dataframe = await self._call_akshare(fetcher, symbol=candidate.code)
                except Exception as exc:
                    logger.debug("获取财务分析指标失败: %s - %s", candidate.code, exc)
                    continue

                metrics = self._extract_financial_metrics(dataframe)
                if not metrics:
                    continue

                if metrics.get("roe") is not None:
                    candidate.roe = metrics["roe"]
                if metrics.get("revenue_growth") is not None:
                    candidate.revenue_growth = metrics["revenue_growth"]
                if metrics.get("net_profit_growth") is not None:
                    candidate.net_profit_growth = metrics["net_profit_growth"]
                if metrics.get("debt_ratio") is not None:
                    candidate.debt_ratio = metrics["debt_ratio"]
                enriched += 1

        # Fallback: use DataSourceManager for stocks that still lack financial data
        if enriched < len(targets) // 2 and self.data_source_manager:
            missing = [c for c in targets if c.roe is None and c.debt_ratio is None]
            if missing:
                dsm_enriched = await self._enrich_financial_via_dsm(missing)
                enriched += dsm_enriched

        if enriched:
            logger.info("财务指标补充完成: %s/%s 只候选股已补充", enriched, len(targets))

    async def _enrich_financial_via_dsm(self, candidates: list[StockCandidate]) -> int:
        """通过 DataSourceManager 获取财务数据（BaoStock profit/growth 降级）"""
        if not self.data_source_manager:
            return 0

        enriched = 0
        for candidate in candidates[:10]:  # Limit to avoid excessive calls
            try:
                # DataSourceManager.get_stock_dataframe returns price data, not financial ratios
                # Try BaoStock profit data directly
                info = await asyncio.to_thread(
                    self._get_baostock_financial, candidate.code
                )
                if not info:
                    continue

                if info.get("roe") is not None and candidate.roe is None:
                    candidate.roe = info["roe"]
                if info.get("revenue_growth") is not None and candidate.revenue_growth is None:
                    candidate.revenue_growth = info["revenue_growth"]
                if info.get("net_profit_growth") is not None and candidate.net_profit_growth is None:
                    candidate.net_profit_growth = info["net_profit_growth"]
                if info.get("debt_ratio") is not None and candidate.debt_ratio is None:
                    candidate.debt_ratio = info["debt_ratio"]
                enriched += 1
            except Exception as exc:
                logger.debug("DataSourceManager财务数据获取失败: %s - %s", candidate.code, exc)
                continue

        return enriched

    def _get_baostock_financial(self, code: str) -> dict[str, Optional[float]]:
        """从 BaoStock 获取单只股票的关键财务指标"""
        try:
            import baostock as bs

            # BaoStock 需要 sh/sz 前缀
            prefix = "sh" if code.startswith(("6", "9")) else "sz"
            bs_code = f"{prefix}.{code}"

            lg = bs.login()
            if lg.error_code != "0":
                return {}

            try:
                # 查询盈利能力数据
                rs = bs.query_profit_data(code=bs_code, year=0, quarter=0)
                if rs.error_code == "0" and rs.data:
                    # Get latest row
                    rows = []
                    while rs.next():
                        rows.append(rs.get_row_data())
                    if rows:
                        fields = rs.fields
                        latest = dict(zip(fields, rows[-1]))
                        result: dict[str, Optional[float]] = {}
                        if "roeAvg" in latest:
                            result["roe"] = _safe_float(latest["roeAvg"])
                            if result["roe"] is not None:
                                result["roe"] = result["roe"] * 100  # Convert to percentage
                        return result

                # 查询成长能力数据
                rs = bs.query_growth_data(code=bs_code, year=0, quarter=0)
                if rs.error_code == "0" and rs.data:
                    rows = []
                    while rs.next():
                        rows.append(rs.get_row_data())
                    if rows:
                        fields = rs.fields
                        latest = dict(zip(fields, rows[-1]))
                        result = {}
                        if "YOYEquity" in latest:
                            result["revenue_growth"] = _safe_float(latest["YOYEquity"])
                        if "YOYNI" in latest:
                            result["net_profit_growth"] = _safe_float(latest["YOYNI"])
                        return result
            finally:
                bs.logout()
        except ImportError:
            logger.debug("BaoStock未安装，跳过财务数据降级")
        except Exception as exc:
            logger.debug("BaoStock财务数据查询失败: %s - %s", code, exc)

        return {}

    async def _call_akshare(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.to_thread(partial(func, *args, **kwargs))
        finally:
            if self.request_delay > 0:
                await asyncio.sleep(self.request_delay)

    def _extract_board_candidates(self, dataframe: pd.DataFrame) -> Iterable[_CandidateSeed]:
        code_col = _pick_column(dataframe, _BOARD_CODE_COLUMNS)
        if not code_col:
            logger.warning("板块成分数据缺少代码列: %s", list(dataframe.columns))
            return []

        name_col = _pick_column(dataframe, _BOARD_NAME_COLUMNS)
        industry_col = _pick_column(dataframe, _BOARD_INDUSTRY_COLUMNS)

        records: dict[str, _CandidateSeed] = {}
        for _, row in dataframe.iterrows():
            code = _normalize_code(row.get(code_col))
            if not code:
                continue
            seed = records.get(code)
            if seed is None:
                seed = _CandidateSeed(code=code)
                records[code] = seed
            if name_col:
                name = _clean_text(row.get(name_col))
                if name:
                    seed.name = name
            if industry_col:
                industry = _clean_text(row.get(industry_col))
                if industry:
                    seed.industry = industry
        return list(records.values())

    def _build_spot_lookup(self, dataframe: pd.DataFrame, target_codes: set[str]) -> dict[str, dict[str, Any]]:
        code_col = _pick_column(dataframe, _SPOT_CODE_COLUMNS)
        if not code_col:
            logger.warning("全市场快照缺少代码列: %s", list(dataframe.columns))
            return {}

        name_col = _pick_column(dataframe, _SPOT_NAME_COLUMNS)
        industry_col = _pick_column(dataframe, _SPOT_INDUSTRY_COLUMNS)
        price_col = _pick_column(dataframe, _SPOT_PRICE_COLUMNS)
        pct_chg_col = _pick_column(dataframe, _SPOT_PCT_CHG_COLUMNS)
        pe_col = _pick_column(dataframe, _SPOT_PE_COLUMNS)
        pb_col = _pick_column(dataframe, _SPOT_PB_COLUMNS)
        total_mv_col = _pick_column(dataframe, _SPOT_TOTAL_MV_COLUMNS)
        circ_mv_col = _pick_column(dataframe, _SPOT_CIRC_MV_COLUMNS)
        turnover_col = _pick_column(dataframe, _SPOT_TURNOVER_COLUMNS)
        volume_ratio_col = _pick_column(dataframe, _SPOT_VOLUME_RATIO_COLUMNS)

        lookup: dict[str, dict[str, Any]] = {}
        for _, row in dataframe.iterrows():
            code = _normalize_code(row.get(code_col))
            if not code or code not in target_codes:
                continue
            lookup[code] = {
                "name": _clean_text(row.get(name_col)) if name_col else "",
                "industry": _clean_text(row.get(industry_col)) if industry_col else "",
                "price": _safe_float(row.get(price_col)) if price_col else None,
                "pct_chg": _safe_float(row.get(pct_chg_col)) if pct_chg_col else None,
                "pe": _safe_float(row.get(pe_col)) if pe_col else None,
                "pb": _safe_float(row.get(pb_col)) if pb_col else None,
                "total_mv": _to_yi(row.get(total_mv_col)) if total_mv_col else None,
                "circ_mv": _to_yi(row.get(circ_mv_col)) if circ_mv_col else None,
                "turnover_rate": _safe_float(row.get(turnover_col)) if turnover_col else None,
                "volume_ratio": _safe_float(row.get(volume_ratio_col)) if volume_ratio_col else None,
            }
        return lookup

    def _extract_financial_metrics(self, dataframe: Any) -> dict[str, Optional[float]]:
        if dataframe is None or getattr(dataframe, "empty", True):
            return {}

        if isinstance(dataframe, pd.DataFrame):
            direct_metrics = self._extract_financial_metrics_from_rows(dataframe)
            if any(value is not None for value in direct_metrics.values()):
                return direct_metrics
            transposed_metrics = self._extract_financial_metrics_from_columns(dataframe)
            if any(value is not None for value in transposed_metrics.values()):
                return transposed_metrics
        return {}

    def _extract_financial_metrics_from_rows(self, dataframe: pd.DataFrame) -> dict[str, Optional[float]]:
        metric_columns = (
            *_FINANCIAL_ROE_COLUMNS,
            *_FINANCIAL_REVENUE_GROWTH_COLUMNS,
            *_FINANCIAL_PROFIT_GROWTH_COLUMNS,
            *_FINANCIAL_DEBT_RATIO_COLUMNS,
        )
        if not any(_pick_column(dataframe, (column,)) for column in metric_columns):
            return {}

        latest_row = _select_latest_row(dataframe)
        return {
            "roe": _lookup_value(latest_row, _FINANCIAL_ROE_COLUMNS),
            "revenue_growth": _lookup_value(latest_row, _FINANCIAL_REVENUE_GROWTH_COLUMNS),
            "net_profit_growth": _lookup_value(latest_row, _FINANCIAL_PROFIT_GROWTH_COLUMNS),
            "debt_ratio": _lookup_value(latest_row, _FINANCIAL_DEBT_RATIO_COLUMNS),
        }

    def _extract_financial_metrics_from_columns(self, dataframe: pd.DataFrame) -> dict[str, Optional[float]]:
        if dataframe.shape[1] < 2:
            return {}

        metric_name_col = dataframe.columns[0]
        date_columns = list(dataframe.columns[1:])
        if not date_columns:
            return {}

        dated_columns = []
        for column in date_columns:
            parsed = pd.to_datetime(column, errors="coerce")
            dated_columns.append((parsed, column))
        valid_dated_columns = [item for item in dated_columns if not pd.isna(item[0])]
        latest_column = max(
            valid_dated_columns,
            default=(None, date_columns[0]),
            key=lambda item: item[0] if item[0] is not None else pd.Timestamp.min,
        )[1]

        metric_map: dict[str, Any] = {}
        for _, row in dataframe.iterrows():
            metric_name = _clean_text(row.get(metric_name_col))
            if metric_name:
                metric_map[metric_name] = row.get(latest_column)

        if not metric_map:
            return {}

        return {
            "roe": _lookup_mapping_value(metric_map, _FINANCIAL_ROE_COLUMNS),
            "revenue_growth": _lookup_mapping_value(metric_map, _FINANCIAL_REVENUE_GROWTH_COLUMNS),
            "net_profit_growth": _lookup_mapping_value(metric_map, _FINANCIAL_PROFIT_GROWTH_COLUMNS),
            "debt_ratio": _lookup_mapping_value(metric_map, _FINANCIAL_DEBT_RATIO_COLUMNS),
        }


def _pick_column(dataframe: pd.DataFrame, aliases: Iterable[str]) -> Optional[str]:
    for alias in aliases:
        if alias in dataframe.columns:
            return alias

    normalized_columns = {_normalize_label(str(column)): str(column) for column in dataframe.columns}
    for alias in aliases:
        normalized_alias = _normalize_label(alias)
        exact = normalized_columns.get(normalized_alias)
        if exact:
            return exact

    for alias in aliases:
        normalized_alias = _normalize_label(alias)
        for normalized_column, original_column in normalized_columns.items():
            if normalized_alias and (normalized_alias in normalized_column or normalized_column in normalized_alias):
                return original_column
    return None


def _lookup_value(row: pd.Series, aliases: Iterable[str]) -> Optional[float]:
    for alias in aliases:
        if alias in row.index:
            return _safe_float(row.get(alias))

    normalized_lookup = {_normalize_label(str(index)): index for index in row.index}
    for alias in aliases:
        normalized_alias = _normalize_label(alias)
        exact = normalized_lookup.get(normalized_alias)
        if exact is not None:
            return _safe_float(row.get(exact))

    for alias in aliases:
        normalized_alias = _normalize_label(alias)
        for normalized_index, original_index in normalized_lookup.items():
            if normalized_alias and (normalized_alias in normalized_index or normalized_index in normalized_alias):
                return _safe_float(row.get(original_index))
    return None


def _lookup_mapping_value(mapping: dict[str, Any], aliases: Iterable[str]) -> Optional[float]:
    for alias in aliases:
        if alias in mapping:
            return _safe_float(mapping.get(alias))

    normalized_lookup = {_normalize_label(key): key for key in mapping.keys()}
    for alias in aliases:
        normalized_alias = _normalize_label(alias)
        exact = normalized_lookup.get(normalized_alias)
        if exact is not None:
            return _safe_float(mapping.get(exact))

    for alias in aliases:
        normalized_alias = _normalize_label(alias)
        for normalized_key, original_key in normalized_lookup.items():
            if normalized_alias and (normalized_alias in normalized_key or normalized_key in normalized_alias):
                return _safe_float(mapping.get(original_key))
    return None


def _select_latest_row(dataframe: pd.DataFrame) -> pd.Series:
    date_col = _pick_column(dataframe, _FINANCIAL_DATE_COLUMNS)
    if not date_col:
        return dataframe.iloc[0]

    sortable = dataframe.copy()
    sortable[date_col] = pd.to_datetime(sortable[date_col], errors="coerce")
    valid_rows = sortable[sortable[date_col].notna()]
    if valid_rows.empty:
        return dataframe.iloc[0]
    return valid_rows.sort_values(date_col).iloc[-1]


def _normalize_code(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return ""
    return digits[-6:].zfill(6)


def _normalize_label(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", str(value or "")).lower()


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if not text or text.lower() == "nan" else text


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if not cleaned or cleaned in {"--", "-", "None", "nan", "NaN"}:
            return None
        cleaned = cleaned.removesuffix("%")
        value = cleaned
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(number) else number


def _to_yi(value: Any) -> Optional[float]:
    number = _safe_float(value)
    if number is None:
        return None
    if abs(number) >= 1_000_000:
        return round(number / 100_000_000, 4)
    return number
