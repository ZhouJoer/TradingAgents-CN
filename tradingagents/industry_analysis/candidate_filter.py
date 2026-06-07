"""行业分析候选股规则过滤器。"""

from __future__ import annotations

import importlib.util
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tradingagents.utils.logging_manager import get_logger



def _load_stock_candidate_model():
    try:
        from app.models.industry_analysis import StockCandidate as stock_candidate_model

        return stock_candidate_model
    except ModuleNotFoundError:
        model_path = Path(__file__).resolve().parents[2] / "app" / "models" / "industry_analysis.py"
        spec = importlib.util.spec_from_file_location("app.models.industry_analysis", model_path)
        if spec is None or spec.loader is None:
            raise

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.StockCandidate


StockCandidate = _load_stock_candidate_model()
logger = get_logger("industry_analysis")


FILTER_REASON_ST_OR_SPECIAL_TREATMENT = "st_or_special_treatment"
FILTER_REASON_DELISTED = "delisted"
FILTER_REASON_SUSPENDED_OR_INVALID_PRICE = "suspended_or_invalid_price"
FILTER_REASON_SMALL_MARKET_CAP = "small_market_cap"
FILTER_REASON_LOW_RULE_SCORE = "low_rule_score"
FILTER_REASON_DATA_MISSING = "data_missing"
FILTER_REASON_NOT_EXCLUDED = "not_excluded"


@dataclass
class FilterTraceItem:
    code: str
    name: str = ""
    industry: str = ""
    included: bool = False
    reason: str = FILTER_REASON_NOT_EXCLUDED
    reason_detail: str = ""
    rule_score: float = 0.0
    source_boards: List[str] = field(default_factory=list)
    key_metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FilterResult:
    selected: List[Any] = field(default_factory=list)
    details: List[FilterTraceItem] = field(default_factory=list)
    excluded_counts: Dict[str, int] = field(default_factory=dict)
    score_distribution: Dict[str, Any] = field(default_factory=dict)


class CandidateFilter:
    """对行业分析候选股进行规则过滤与综合评分。"""

    DEFAULT_WEIGHTS: Dict[str, float] = {
        "match_score": 0.25,
        "market_cap": 0.15,
        "pe": 0.15,
        "roe": 0.15,
        "momentum": 0.10,
        "turnover": 0.10,
        "pb": 0.10,
    }

    def __init__(
        self,
        min_market_cap: float = 30.0,
        max_candidates: int = 30,
        preferred_market_cap_range: Tuple[float, float] = (100.0, 2000.0),
        preferred_pe_range: Tuple[float, float] = (0.0, 50.0),
        preferred_pb_range: Tuple[float, float] = (0.0, 10.0),
        preferred_turnover_range: Tuple[float, float] = (1.0, 8.0),
        weights: Optional[Dict[str, float]] = None,
    ) -> None:
        self.min_market_cap = min_market_cap
        self.max_candidates = max_candidates
        self.preferred_market_cap_range = preferred_market_cap_range
        self.preferred_pe_range = preferred_pe_range
        self.preferred_pb_range = preferred_pb_range
        self.preferred_turnover_range = preferred_turnover_range
        self.weights = self._normalize_weights(weights or self.DEFAULT_WEIGHTS)

    def filter(self, candidates: List[StockCandidate], max_output: int = 30) -> List[StockCandidate]:
        """按规则过滤候选股并返回综合评分最高的结果。"""
        return self.filter_with_trace(candidates, max_output=max_output).selected

    def filter_with_trace(self, candidates: List[StockCandidate], max_output: int = 30) -> FilterResult:
        """按规则过滤候选股，并返回可展示的过滤明细。"""
        if not candidates:
            logger.info("候选股过滤完成: 输入=0, 输出=0")
            return FilterResult(
                excluded_counts=self._empty_excluded_counts(),
                score_distribution={},
            )

        excluded = self._empty_excluded_counts()
        survivors: List[StockCandidate] = []
        details_by_code: Dict[str, FilterTraceItem] = {}

        for candidate in candidates:
            name = (candidate.name or "").upper()
            if "*ST" in name or "ST" in name:
                excluded[FILTER_REASON_ST_OR_SPECIAL_TREATMENT] += 1
                details_by_code[candidate.code] = self._build_trace_item(
                    candidate,
                    included=False,
                    reason=FILTER_REASON_ST_OR_SPECIAL_TREATMENT,
                    reason_detail="股票名称包含ST或*ST标识",
                )
                continue
            if "退" in (candidate.name or ""):
                excluded[FILTER_REASON_DELISTED] += 1
                details_by_code[candidate.code] = self._build_trace_item(
                    candidate,
                    included=False,
                    reason=FILTER_REASON_DELISTED,
                    reason_detail="股票名称包含退市相关标识",
                )
                continue
            # price=None 可能是数据获取失败（非停牌），不排除
            if candidate.price is not None and candidate.price <= 0:
                excluded[FILTER_REASON_SUSPENDED_OR_INVALID_PRICE] += 1
                details_by_code[candidate.code] = self._build_trace_item(
                    candidate,
                    included=False,
                    reason=FILTER_REASON_SUSPENDED_OR_INVALID_PRICE,
                    reason_detail="价格小于等于0，疑似停牌或行情无效",
                )
                continue
            market_cap = self._get_market_cap(candidate)
            if market_cap is not None and market_cap < self.min_market_cap:
                excluded[FILTER_REASON_SMALL_MARKET_CAP] += 1
                details_by_code[candidate.code] = self._build_trace_item(
                    candidate,
                    included=False,
                    reason=FILTER_REASON_SMALL_MARKET_CAP,
                    reason_detail=f"市值低于过滤阈值 {self.min_market_cap:.0f} 亿",
                )
                continue
            survivors.append(candidate)

        if not survivors:
            logger.info(
                "候选股过滤完成: 输入=%s, 输出=0, ST剔除=%s, 退市剔除=%s, 停牌剔除=%s, 小市值剔除=%s",
                len(candidates),
                excluded[FILTER_REASON_ST_OR_SPECIAL_TREATMENT],
                excluded[FILTER_REASON_DELISTED],
                excluded[FILTER_REASON_SUSPENDED_OR_INVALID_PRICE],
                excluded[FILTER_REASON_SMALL_MARKET_CAP],
            )
            return FilterResult(
                selected=[],
                details=list(details_by_code.values()),
                excluded_counts=excluded,
                score_distribution={},
            )

        match_signals = [self._match_signal(candidate) for candidate in survivors]
        scored_candidates: List[StockCandidate] = []

        for candidate in survivors:
            score = self._composite_score(candidate, match_signals)
            candidate.match_score = round(score, 4)
            scored_candidates.append(candidate)

        scored_candidates.sort(key=lambda item: item.match_score, reverse=True)
        output_limit = max(0, min(max_output, self.max_candidates))
        result = scored_candidates[:output_limit]
        selected_codes = {item.code for item in result}

        for candidate in scored_candidates:
            included = candidate.code in selected_codes
            reason = FILTER_REASON_NOT_EXCLUDED if included else FILTER_REASON_LOW_RULE_SCORE
            reason_detail = "进入选股阶段" if included else "规则评分排序未进入本次候选上限"
            if not included:
                excluded[FILTER_REASON_LOW_RULE_SCORE] += 1
            details_by_code[candidate.code] = self._build_trace_item(
                candidate,
                included=included,
                reason=reason,
                reason_detail=reason_detail,
                rule_score=candidate.match_score,
            )

        score_distribution = self._score_distribution(survivors)
        self._log_summary(candidates, excluded, survivors, result, score_distribution)
        ordered_details = [details_by_code[item.code] for item in candidates if item.code in details_by_code]
        return FilterResult(
            selected=result,
            details=ordered_details,
            excluded_counts=excluded,
            score_distribution=score_distribution,
        )

    def _composite_score(self, candidate: StockCandidate, match_signals: List[float]) -> float:
        scores = {
            "match_score": self._score_match_signal(self._match_signal(candidate), match_signals),
            "market_cap": self._score_market_cap(self._get_market_cap(candidate)),
            "pe": self._score_pe(candidate.pe),
            "roe": self._score_roe(candidate.roe),
            "momentum": self._score_momentum(candidate.pct_chg_20d),
            "turnover": self._score_turnover(candidate.turnover_rate),
            "pb": self._score_pb(candidate.pb),
        }
        return sum(scores[name] * self.weights[name] for name in self.weights)

    def _match_signal(self, candidate: StockCandidate) -> float:
        base_signal = candidate.match_score if candidate.match_score > 0 else float(len(candidate.source_boards))
        return max(base_signal, 0.0)

    def _score_match_signal(self, signal: float, all_signals: List[float]) -> float:
        if not all_signals:
            return 50.0
        signal_max = max(all_signals)
        signal_min = min(all_signals)
        if signal_max <= 0:
            return 50.0
        if math.isclose(signal_max, signal_min):
            return 100.0 if signal_max > 0 else 50.0
        return self._clamp((signal - signal_min) / (signal_max - signal_min) * 100.0)

    def _score_market_cap(self, market_cap: Optional[float]) -> float:
        if market_cap is None:
            return 50.0
        if market_cap <= 0:
            return 0.0

        preferred_low, preferred_high = self.preferred_market_cap_range
        if preferred_low <= market_cap <= preferred_high:
            return 100.0

        if market_cap < preferred_low:
            floor = max(self.min_market_cap, 1.0)
            if market_cap <= floor:
                return 60.0
            span = math.log(preferred_low / floor) if preferred_low > floor else 1.0
            ratio = math.log(market_cap / floor) / span if span > 0 else 1.0
            return self._clamp(60.0 + ratio * 40.0)

        ceiling = preferred_high * 50.0
        ratio = math.log(min(market_cap, ceiling) / preferred_high) / math.log(ceiling / preferred_high)
        return self._clamp(100.0 - ratio * 50.0)

    def _score_pe(self, pe: Optional[float]) -> float:
        if pe is None:
            return 50.0
        if pe <= 0:
            return 15.0

        _, preferred_high = self.preferred_pe_range
        if pe < preferred_high:
            return 100.0
        if pe <= preferred_high * 2:
            return self._clamp(100.0 - (pe - preferred_high) / preferred_high * 50.0)
        return self._clamp(50.0 - math.log10(pe / preferred_high) * 25.0, lower=10.0)

    def _score_roe(self, roe: Optional[float]) -> float:
        if roe is None:
            return 50.0
        if roe <= 0:
            return 20.0
        if roe < 8:
            return self._clamp(50.0 + roe / 8.0 * 20.0)
        if roe < 15:
            return self._clamp(70.0 + (roe - 8.0) / 7.0 * 20.0)
        if roe < 25:
            return self._clamp(90.0 + (roe - 15.0) / 10.0 * 10.0)
        return 100.0

    def _score_momentum(self, pct_chg_20d: Optional[float]) -> float:
        if pct_chg_20d is None:
            return 50.0
        return self._clamp(50.0 + self._clamp(pct_chg_20d, -20.0, 20.0) * 2.5)

    def _score_turnover(self, turnover_rate: Optional[float]) -> float:
        if turnover_rate is None:
            return 50.0
        if turnover_rate <= 0:
            return 40.0

        preferred_low, preferred_high = self.preferred_turnover_range
        if preferred_low <= turnover_rate <= preferred_high:
            return 100.0
        if turnover_rate < preferred_low:
            return self._clamp(60.0 + turnover_rate / preferred_low * 40.0)
        if turnover_rate <= preferred_high * 2:
            return self._clamp(100.0 - (turnover_rate - preferred_high) / preferred_high * 40.0)
        return self._clamp(60.0 - math.log10(turnover_rate / preferred_high) * 30.0, lower=20.0)

    def _score_pb(self, pb: Optional[float]) -> float:
        if pb is None:
            return 50.0
        if pb <= 0:
            return 20.0

        _, preferred_high = self.preferred_pb_range
        if pb < preferred_high:
            return 100.0
        if pb <= preferred_high * 2:
            return self._clamp(100.0 - (pb - preferred_high) / preferred_high * 50.0)
        return self._clamp(50.0 - math.log10(pb / preferred_high) * 25.0, lower=10.0)

    def _get_market_cap(self, candidate: StockCandidate) -> Optional[float]:
        return candidate.total_mv if candidate.total_mv is not None else candidate.circ_mv

    def _normalize_weights(self, weights: Dict[str, float]) -> Dict[str, float]:
        normalized = dict(self.DEFAULT_WEIGHTS)
        normalized.update(weights)
        total = sum(max(value, 0.0) for value in normalized.values())
        if total <= 0:
            raise ValueError("CandidateFilter weights must sum to a positive value")
        return {key: max(value, 0.0) / total for key, value in normalized.items()}

    def _empty_excluded_counts(self) -> Dict[str, int]:
        return {
            FILTER_REASON_ST_OR_SPECIAL_TREATMENT: 0,
            FILTER_REASON_DELISTED: 0,
            FILTER_REASON_SUSPENDED_OR_INVALID_PRICE: 0,
            FILTER_REASON_SMALL_MARKET_CAP: 0,
            FILTER_REASON_LOW_RULE_SCORE: 0,
            FILTER_REASON_DATA_MISSING: 0,
            FILTER_REASON_NOT_EXCLUDED: 0,
        }

    def _build_trace_item(
        self,
        candidate: StockCandidate,
        included: bool,
        reason: str,
        reason_detail: str,
        rule_score: Optional[float] = None,
    ) -> FilterTraceItem:
        metric_names = [
            "pe", "pb", "roe", "total_mv", "circ_mv", "price", "pct_chg",
            "pct_chg_20d", "turnover_rate", "volume_ratio",
        ]
        metrics = candidate.model_dump()
        return FilterTraceItem(
            code=candidate.code,
            name=candidate.name,
            industry=candidate.industry,
            included=included,
            reason=reason,
            reason_detail=reason_detail,
            rule_score=round(float(rule_score if rule_score is not None else candidate.match_score or 0.0), 4),
            source_boards=list(candidate.source_boards or []),
            key_metrics={key: metrics.get(key) for key in metric_names if metrics.get(key) is not None},
        )

    def _score_distribution(self, candidates: List[StockCandidate]) -> Dict[str, Any]:
        if not candidates:
            return {}
        scores = [candidate.match_score for candidate in candidates]
        return {
            "min": min(scores),
            "mean": statistics.mean(scores),
            "median": statistics.median(scores),
            "max": max(scores),
            "high": sum(score >= 80 for score in scores),
            "mid": sum(60 <= score < 80 for score in scores),
            "low": sum(score < 60 for score in scores),
        }

    def _log_summary(
        self,
        original_candidates: List[StockCandidate],
        excluded: Dict[str, int],
        survivors: List[StockCandidate],
        result: List[StockCandidate],
        distribution: Optional[Dict[str, Any]] = None,
    ) -> None:
        distribution = distribution or self._score_distribution(survivors)
        logger.info(
            "候选股过滤完成: 输入=%s, 保留=%s, 输出=%s, ST剔除=%s, 退市剔除=%s, 停牌剔除=%s, 小市值剔除=%s",
            len(original_candidates),
            len(survivors),
            len(result),
            excluded[FILTER_REASON_ST_OR_SPECIAL_TREATMENT],
            excluded[FILTER_REASON_DELISTED],
            excluded[FILTER_REASON_SUSPENDED_OR_INVALID_PRICE],
            excluded[FILTER_REASON_SMALL_MARKET_CAP],
        )
        logger.info(
            "候选股评分分布: min=%.2f, mean=%.2f, median=%.2f, max=%.2f, >=80=%s, 60-80=%s, <60=%s",
            distribution["min"],
            distribution["mean"],
            distribution["median"],
            distribution["max"],
            distribution["high"],
            distribution["mid"],
            distribution["low"],
        )

    @staticmethod
    def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
        return max(lower, min(value, upper))
