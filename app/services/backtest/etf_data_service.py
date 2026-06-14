from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReplaceOne

from .engine import DEFAULT_ETF_UNIVERSE

logger = logging.getLogger("webapi")
END_DATE_TOLERANCE_DAYS = 7
FETCH_RETRY_ATTEMPTS = 3
FETCH_RETRY_DELAY_SECONDS = 0.6
PRICE_FIELDS = ("open", "high", "low", "close")
TUSHARE_HISTORY_SOURCES = {
    "none": ("tushare_fund_daily",),
    "qfq": ("tushare_fund_daily_factor_qfq",),
    "hfq": ("tushare_fund_daily_factor_hfq",),
}
SOURCE_PRIORITY = {
    "tushare_fund_daily_factor_qfq": 0,
    "tushare_fund_daily_factor_hfq": 0,
    "tushare_fund_daily": 0,
    "akshare_fund_etf_hist_em": 10,
    "akshare_fund_etf_hist_sina": 20,
}


def etf_exchange_symbol(code: str) -> str:
    code = str(code).strip().zfill(6)
    return f"sh{code}" if code.startswith(("5", "51", "56", "58")) else f"sz{code}"


def etf_ts_code(code: str) -> str:
    code = str(code).strip().zfill(6)
    return f"{code}.SH" if code.startswith(("5", "51", "56", "58")) else f"{code}.SZ"


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _format_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text[:10]


def _parse_date(value: Any) -> Optional[datetime]:
    try:
        return datetime.strptime(_format_date(value), "%Y-%m-%d")
    except Exception:
        return None


def _records_by_date(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {row["trade_date"]: row for row in records if row.get("trade_date")}


def _source_priority(source: Any) -> int:
    return SOURCE_PRIORITY.get(str(source), 100)


def _dedupe_history_by_source(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_date: Dict[str, Dict[str, Any]] = {}
    for row in records:
        trade_date = row.get("trade_date")
        if not trade_date:
            continue
        existing = by_date.get(trade_date)
        if existing is None or _source_priority(row.get("source")) < _source_priority(existing.get("source")):
            by_date[trade_date] = row
    return [by_date[date] for date in sorted(by_date)]


def verify_adjustment_factor_rows(
    raw_records: List[Dict[str, Any]],
    adjusted_records: List[Dict[str, Any]],
    factor_records: List[Dict[str, Any]],
    tolerance: float = 0.01,
) -> Dict[str, Any]:
    raw_by_date = _records_by_date(raw_records)
    adjusted_by_date = _records_by_date(adjusted_records)
    factor_by_date = _records_by_date(factor_records)
    common_dates = sorted(set(raw_by_date) & set(adjusted_by_date) & set(factor_by_date))
    field_errors = {field: 0.0 for field in PRICE_FIELDS}
    field_mismatches = {field: 0 for field in PRICE_FIELDS}
    worst: Optional[Dict[str, Any]] = None

    for trade_date in common_dates:
        factor = _safe_float(factor_by_date[trade_date].get("factor"))
        if factor is None:
            continue
        for field in PRICE_FIELDS:
            raw_value = _safe_float(raw_by_date[trade_date].get(field))
            adjusted_value = _safe_float(adjusted_by_date[trade_date].get(field))
            if raw_value is None or adjusted_value is None:
                continue
            rebuilt_value = raw_value * factor
            abs_error = abs(rebuilt_value - adjusted_value)
            field_errors[field] = max(field_errors[field], abs_error)
            if abs_error > tolerance:
                field_mismatches[field] += 1
            if worst is None or abs_error > worst["abs_error"]:
                worst = {
                    "trade_date": trade_date,
                    "field": field,
                    "raw": raw_value,
                    "factor": factor,
                    "rebuilt": rebuilt_value,
                    "adjusted": adjusted_value,
                    "abs_error": abs_error,
                }

    return {
        "common_count": len(common_dates),
        "tolerance": tolerance,
        "max_abs_error": max(field_errors.values()) if field_errors else 0.0,
        "field_errors": field_errors,
        "field_mismatches": field_mismatches,
        "mismatch_count": sum(field_mismatches.values()),
        "worst": worst,
    }


class ETFDataService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        if isinstance(db, dict):
            self.basic_collection = db.get("etf_basic_info")
            self.daily_collection = db.get("etf_daily_quotes")
            self.factor_collection = db.get("etf_adjustment_factors")
        else:
            self.basic_collection = db["etf_basic_info"]
            self.daily_collection = db["etf_daily_quotes"]
            self.factor_collection = db["etf_adjustment_factors"]

    async def ensure_indexes(self) -> None:
        await self.basic_collection.create_index([("code", 1)], unique=True, background=True)
        await self.daily_collection.create_index(
            [("code", 1), ("trade_date", 1), ("source", 1), ("adjust", 1)],
            unique=True,
            background=True,
            name="code_date_source_adjust_unique",
        )
        await self.daily_collection.create_index([("code", 1), ("trade_date", -1)], background=True)
        await self.factor_collection.create_index(
            [("code", 1), ("trade_date", 1), ("adjust", 1)],
            unique=True,
            background=True,
            name="code_date_adjust_factor_unique",
        )

    async def get_universe(self) -> List[Dict[str, Any]]:
        await self.ensure_indexes()
        codes = [item["code"] for item in DEFAULT_ETF_UNIVERSE]
        cached = await self.basic_collection.find({"code": {"$in": codes}}, {"_id": 0}).to_list(None)
        cached_by_code = {item["code"]: item for item in cached}
        result = []
        for item in DEFAULT_ETF_UNIVERSE:
            merged = dict(item)
            if item["code"] in cached_by_code:
                merged.update(cached_by_code[item["code"]])
            result.append(merged)
        return result

    async def refresh_basic_info(self) -> int:
        await self.ensure_indexes()
        rows = await asyncio.to_thread(self._fetch_basic_info)
        if not rows:
            return 0
        now = datetime.utcnow()
        operations = []
        for row in rows:
            row["updated_at"] = now
            operations.append(
                ReplaceOne({"code": row["code"]}, row, upsert=True)
            )
        result = await self.basic_collection.bulk_write(operations, ordered=False)
        return int(result.upserted_count + result.modified_count)

    async def get_history_map(
        self,
        codes: Iterable[str],
        start_date: str,
        end_date: str,
        adjust: str = "qfq",
        auto_fetch: bool = True,
    ) -> Tuple[Dict[str, List[Dict[str, Any]]], List[str]]:
        await self.ensure_indexes()
        warnings: List[str] = []
        history: Dict[str, List[Dict[str, Any]]] = {}
        for code in [str(c).zfill(6) for c in codes]:
            records = await self._query_history(code, start_date, end_date, adjust)
            primary_records = await self._query_tushare_history(code, start_date, end_date, adjust)
            primary_missing = self._should_prefer_tushare() and not self._covers_range(
                primary_records, start_date, end_date
            )
            if auto_fetch and (not self._covers_range(records, start_date, end_date) or primary_missing):
                try:
                    saved = await self.fetch_and_cache_history(code, start_date, end_date, adjust)
                    if saved == 0:
                        warnings.append(f"{code}: no new ETF history fetched")
                    records = await self._query_history(code, start_date, end_date, adjust)
                except Exception as exc:
                    logger.warning("ETF history fetch failed for %s: %s", code, exc)
                    warnings.append(f"{code}: fetch failed: {exc}")
            if records:
                history[code] = records
            else:
                warnings.append(f"{code}: no cached ETF history")
        return history, warnings

    async def fetch_and_cache_history(self, code: str, start_date: str, end_date: str, adjust: str = "qfq") -> int:
        await self.ensure_indexes()
        code = str(code).zfill(6)
        rows = await asyncio.to_thread(self._fetch_history, code, start_date, end_date, adjust)
        if not rows:
            return 0
        now = datetime.utcnow()
        operations = []
        for row in rows:
            row.update({"code": code, "adjust": adjust, "updated_at": now})
            operations.append(
                ReplaceOne(
                    {
                        "code": code,
                        "trade_date": row["trade_date"],
                        "source": row["source"],
                        "adjust": adjust,
                    },
                    row,
                    upsert=True,
                )
            )
        result = await self.daily_collection.bulk_write(operations, ordered=False)
        return int(result.upserted_count + result.modified_count)

    async def _query_history(self, code: str, start_date: str, end_date: str, adjust: str) -> List[Dict[str, Any]]:
        cursor = self.daily_collection.find(
            {
                "code": code,
                "trade_date": {"$gte": start_date, "$lte": end_date},
                "adjust": adjust,
            },
            {"_id": 0},
        ).sort("trade_date", 1)
        return _dedupe_history_by_source(await cursor.to_list(None))

    async def _query_tushare_history(self, code: str, start_date: str, end_date: str, adjust: str) -> List[Dict[str, Any]]:
        if self.daily_collection is None:
            return []
        sources = TUSHARE_HISTORY_SOURCES.get(adjust, ())
        if not sources:
            return []
        cursor = self.daily_collection.find(
            {
                "code": str(code).zfill(6),
                "trade_date": {"$gte": start_date, "$lte": end_date},
                "adjust": adjust,
                "source": {"$in": list(sources)},
            },
            {"_id": 0},
        ).sort("trade_date", 1)
        return _dedupe_history_by_source(await cursor.to_list(None))

    async def _query_factors(self, code: str, start_date: str, end_date: str, adjust: str) -> List[Dict[str, Any]]:
        cursor = self.factor_collection.find(
            {
                "code": str(code).zfill(6),
                "trade_date": {"$gte": start_date, "$lte": end_date},
                "adjust": adjust,
            },
            {"_id": 0},
        ).sort("trade_date", 1)
        return await cursor.to_list(None)

    async def fetch_and_cache_adjustment_factors(
        self,
        code: str,
        start_date: str,
        end_date: str,
        adjust: str = "qfq",
        source: str = "tushare",
    ) -> Dict[str, Any]:
        if adjust == "none":
            raise ValueError("Cannot fetch adjustment factors for unadjusted data")
        await self.ensure_indexes()
        code = str(code).zfill(6)
        rows = await asyncio.to_thread(
            self._fetch_adjustment_factors,
            code,
            start_date,
            end_date,
            adjust,
            source,
        )
        if not rows:
            return {
                "code": code,
                "adjust": adjust,
                "source": source,
                "factor_count": 0,
                "saved": 0,
            }

        now = datetime.utcnow()
        operations = []
        for row in rows:
            row["updated_at"] = now
            operations.append(
                ReplaceOne(
                    {"code": code, "trade_date": row["trade_date"], "adjust": adjust},
                    row,
                    upsert=True,
                )
            )
        result = await self.factor_collection.bulk_write(operations, ordered=False)
        return {
            "code": code,
            "adjust": adjust,
            "source": source,
            "factor_count": len(rows),
            "saved": int(result.upserted_count + result.modified_count),
            "date_range": f"{rows[0]['trade_date']}..{rows[-1]['trade_date']}",
        }

    async def verify_cached_adjustment_factors(
        self,
        code: str,
        start_date: str,
        end_date: str,
        adjust: str = "qfq",
        tolerance: float = 0.01,
    ) -> Dict[str, Any]:
        code = str(code).zfill(6)
        raw_records = await self._query_history(code, start_date, end_date, "none")
        adjusted_records = await self._query_history(code, start_date, end_date, adjust)
        factor_records = await self._query_factors(code, start_date, end_date, adjust)
        report = verify_adjustment_factor_rows(raw_records, adjusted_records, factor_records, tolerance)
        report.update(
            {
                "code": code,
                "adjust": adjust,
                "raw_count": len(raw_records),
                "adjusted_count": len(adjusted_records),
                "factor_count": len(factor_records),
            }
        )
        return report

    def _fetch_adjustment_factors(
        self,
        code: str,
        start_date: str,
        end_date: str,
        adjust: str,
        source: str,
    ) -> List[Dict[str, Any]]:
        if source != "tushare":
            raise ValueError(f"Unsupported adjustment factor source: {source}")
        return self._fetch_adjustment_factors_tushare(code, start_date, end_date, adjust)

    def _fetch_adjustment_factors_tushare(
        self,
        code: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ) -> List[Dict[str, Any]]:
        from app.core.config import settings
        import tushare as ts

        if settings.TUSHARE_TOKEN:
            ts.set_token(settings.TUSHARE_TOKEN)
        pro = ts.pro_api()
        df = pro.fund_adj(
            ts_code=etf_ts_code(code),
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
        )
        if df is None or df.empty:
            return []

        rows: List[Dict[str, Any]] = []
        for _, row in df.iterrows():
            raw_factor = _safe_float(row.get("adj_factor"))
            trade_date = _format_date(row.get("trade_date"))
            if raw_factor is None or raw_factor <= 0 or not (start_date <= trade_date <= end_date):
                continue
            rows.append(
                {
                    "code": str(code).zfill(6),
                    "trade_date": trade_date,
                    "adjust": adjust,
                    "raw_factor": raw_factor,
                    "source": "tushare_fund_adj",
                }
            )
        rows.sort(key=lambda item: item["trade_date"])
        if not rows:
            return []

        normalization_factor = rows[-1]["raw_factor"] if adjust == "qfq" else 1.0
        for row in rows:
            row["factor"] = row["raw_factor"] / normalization_factor
            row["normalization_factor"] = normalization_factor
        return rows

    def _covers_range(self, records: List[Dict[str, Any]], start_date: str, end_date: str) -> bool:
        if len(records) < 30:
            return False
        dates = [row.get("trade_date") for row in records if row.get("trade_date")]
        if not dates or min(dates) > start_date:
            return False
        latest = max(dates)
        if latest >= end_date:
            return True
        latest_dt = _parse_date(latest)
        end_dt = _parse_date(end_date)
        if latest_dt is None or end_dt is None or latest_dt > end_dt:
            return False
        return end_dt - latest_dt <= timedelta(days=END_DATE_TOLERANCE_DAYS)

    def _fetch_basic_info(self) -> List[Dict[str, Any]]:
        try:
            import akshare as ak

            df = ak.fund_etf_spot_em()
            if df is None or df.empty:
                return []
            code_col = df.columns[0]
            name_col = df.columns[1]
            rows: List[Dict[str, Any]] = []
            for _, row in df.iterrows():
                code = str(row.get(code_col, "")).strip().zfill(6)
                if not code.isdigit():
                    continue
                rows.append(
                    {
                        "code": code,
                        "name": str(row.get(name_col, "")),
                        "latest_price": _safe_float(row.get("latest_price") or row.get("最新价")),
                        "amount": _safe_float(row.get("amount") or row.get("成交额")),
                        "volume": _safe_float(row.get("volume") or row.get("成交量")),
                        "trade_date": _format_date(row.get("数据日期") or datetime.utcnow()),
                        "source": "akshare_fund_etf_spot_em",
                    }
                )
            return rows
        except Exception as exc:
            logger.warning("Failed to fetch ETF basic info: %s", exc)
            return []

    def _fetch_history(self, code: str, start_date: str, end_date: str, adjust: str) -> List[Dict[str, Any]]:
        if self._should_prefer_tushare():
            try:
                rows = self._fetch_with_retries(lambda: self._fetch_history_tushare(code, start_date, end_date, adjust))
                if rows:
                    return rows
            except Exception as exc:
                logger.warning("ETF tushare history fetch failed for %s %s: %s", code, adjust, exc)

        if adjust and adjust != "none":
            return self._fetch_with_retries(lambda: self._fetch_history_em(code, start_date, end_date, adjust))
        try:
            rows = self._fetch_with_retries(lambda: self._fetch_history_sina(code, start_date, end_date))
        except Exception as exc:
            logger.warning("ETF sina history fetch failed for %s: %s", code, exc)
            rows = []
        if rows:
            return rows
        return self._fetch_with_retries(lambda: self._fetch_history_em(code, start_date, end_date, ""))

    def _fetch_with_retries(self, fetcher) -> List[Dict[str, Any]]:
        last_exc: Optional[Exception] = None
        for attempt in range(FETCH_RETRY_ATTEMPTS):
            try:
                return fetcher()
            except Exception as exc:
                last_exc = exc
                if attempt >= FETCH_RETRY_ATTEMPTS - 1:
                    break
                time.sleep(FETCH_RETRY_DELAY_SECONDS * (attempt + 1))
        if last_exc is not None:
            raise last_exc
        return []

    def _should_prefer_tushare(self) -> bool:
        try:
            from app.core.config import settings

            return bool(settings.TUSHARE_TOKEN)
        except Exception:
            return False

    def _fetch_history_tushare(self, code: str, start_date: str, end_date: str, adjust: str) -> List[Dict[str, Any]]:
        raw_rows = self._fetch_history_tushare_raw(code, start_date, end_date)
        if adjust == "none":
            return raw_rows

        factor_rows = self._fetch_adjustment_factors_tushare(code, start_date, end_date, adjust)
        factor_by_date = _records_by_date(factor_rows)
        rows: List[Dict[str, Any]] = []
        for row in raw_rows:
            factor_row = factor_by_date.get(row["trade_date"])
            factor = _safe_float(factor_row.get("factor")) if factor_row else None
            if factor is None or factor <= 0:
                continue
            adjusted_row = dict(row)
            for field in PRICE_FIELDS:
                value = _safe_float(adjusted_row.get(field))
                if value is not None:
                    adjusted_row[field] = value * factor
            pre_close = _safe_float(adjusted_row.get("pre_close"))
            if pre_close is not None:
                adjusted_row["pre_close"] = pre_close * factor
            adjusted_row["source"] = f"tushare_fund_daily_factor_{adjust}"
            adjusted_row["factor_source"] = factor_row.get("source")
            adjusted_row["adjust_factor"] = factor
            rows.append(adjusted_row)
        return rows

    def _fetch_history_tushare_raw(self, code: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        from app.core.config import settings
        import tushare as ts

        if settings.TUSHARE_TOKEN:
            ts.set_token(settings.TUSHARE_TOKEN)
        pro = ts.pro_api()
        df = pro.fund_daily(
            ts_code=etf_ts_code(code),
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
        )
        if df is None or df.empty:
            return []
        return self._standardize_tushare_fund_daily(df, start_date, end_date)

    def _standardize_tushare_fund_daily(self, df: pd.DataFrame, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        normalized = df.rename(columns={"vol": "volume"})
        return self._standardize_history(normalized, "tushare_fund_daily", start_date, end_date)

    def _fetch_history_sina(self, code: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        import akshare as ak

        df = ak.fund_etf_hist_sina(symbol=etf_exchange_symbol(code))
        if df is None or df.empty:
            return []
        return self._standardize_history(df, "akshare_fund_etf_hist_sina", start_date, end_date)

    def _fetch_history_em(self, code: str, start_date: str, end_date: str, adjust: str) -> List[Dict[str, Any]]:
        import akshare as ak

        df = ak.fund_etf_hist_em(
            symbol=code,
            period="daily",
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            adjust=adjust if adjust != "none" else "",
        )
        if df is None or df.empty:
            return []
        return self._standardize_history(df, "akshare_fund_etf_hist_em", start_date, end_date)

    def _standardize_history(self, df: pd.DataFrame, source: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        mapping = {
            "日期": "trade_date",
            "date": "trade_date",
            "开盘": "open",
            "open": "open",
            "最高": "high",
            "high": "high",
            "最低": "low",
            "low": "low",
            "收盘": "close",
            "close": "close",
            "成交量": "volume",
            "volume": "volume",
            "成交额": "amount",
            "amount": "amount",
            "prevclose": "pre_close",
        }
        renamed = df.rename(columns={key: value for key, value in mapping.items() if key in df.columns})
        rows: List[Dict[str, Any]] = []
        for _, row in renamed.iterrows():
            trade_date = _format_date(row.get("trade_date"))
            if not (start_date <= trade_date <= end_date):
                continue
            close = _safe_float(row.get("close"))
            if close is None or close <= 0:
                continue
            rows.append(
                {
                    "trade_date": trade_date,
                    "open": _safe_float(row.get("open")) or close,
                    "high": _safe_float(row.get("high")) or close,
                    "low": _safe_float(row.get("low")) or close,
                    "close": close,
                    "volume": _safe_float(row.get("volume")),
                    "amount": _safe_float(row.get("amount")),
                    "pre_close": _safe_float(row.get("pre_close")),
                    "source": source,
                    "created_at": datetime.utcnow(),
                }
            )
        return rows
