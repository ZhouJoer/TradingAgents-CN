from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from .strategy_catalog import strategy_default_frequency, strategy_default_params


MIN_POSITION_WEIGHT = 1e-8
MIN_SHARE_QUANTITY = 1e-8


DEFAULT_ETF_UNIVERSE: List[Dict[str, str]] = [
    {"code": "510300", "name": "CSI 300 ETF", "group": "broad"},
    {"code": "510500", "name": "CSI 500 ETF", "group": "broad"},
    {"code": "510050", "name": "SSE 50 ETF", "group": "broad"},
    {"code": "159915", "name": "创业板ETF易方达", "group": "broad"},
    {"code": "159952", "name": "创业板ETF广发", "group": "broad"},
    {"code": "159956", "name": "创业板ETF建信", "group": "broad"},
    {"code": "588000", "name": "STAR 50 ETF", "group": "broad"},
    {"code": "512800", "name": "Bank ETF", "group": "sector"},
    {"code": "512880", "name": "Securities ETF", "group": "sector"},
    {"code": "512480", "name": "Semiconductor ETF", "group": "sector"},
    {"code": "512010", "name": "Healthcare ETF", "group": "sector"},
    {"code": "512690", "name": "Liquor ETF", "group": "sector"},
    {"code": "515790", "name": "Photovoltaic ETF", "group": "sector"},
    {"code": "516160", "name": "New Energy ETF", "group": "sector"},
    {"code": "515030", "name": "EV ETF", "group": "sector"},
    {"code": "159928", "name": "Consumer ETF", "group": "sector"},
    {"code": "512400", "name": "Nonferrous ETF", "group": "sector"},
    {"code": "512890", "name": "红利低波ETF华泰柏瑞", "group": "factor"},
    {"code": "515100", "name": "红利低波100ETF景顺", "group": "factor"},
    {"code": "515300", "name": "300红利低波ETF嘉实", "group": "factor"},
    {"code": "563020", "name": "红利低波ETF易方达", "group": "factor"},
    {"code": "518880", "name": "Gold ETF", "group": "commodity"},
    {"code": "511880", "name": "Money Market ETF", "group": "cash_watch"},
]

DEFAULT_ROTATION_UNIVERSE: List[Dict[str, str]] = [
    item for item in DEFAULT_ETF_UNIVERSE if item.get("group") != "cash_watch"
]

DEFAULT_DEFENSIVE_UNIVERSE = ("518880", "512890", "515100", "515300", "563020")


@dataclass
class BacktestConfig:
    strategy_id: str
    start_date: str
    end_date: str
    universe: List[str]
    initial_cash: float = 1_000_000.0
    commission_bps: float = 5.0
    slippage_bps: float = 5.0
    price_adjust: str = "qfq"
    entry_delay_trading_days: int = 0
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyContext:
    close: pd.DataFrame
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    volume: pd.DataFrame
    returns: pd.DataFrame


@dataclass
class StrategySignal:
    weights: Dict[str, float]
    scores: Dict[str, float] = field(default_factory=dict)
    eligible: List[str] = field(default_factory=list)
    reason: str = "selected"


StrategyFn = Callable[[StrategyContext, pd.Timestamp, Dict[str, Any]], StrategySignal]


def _clean_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return default
        result = float(value)
        if np.isfinite(result):
            return result
    except Exception:
        pass
    return default


def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    cleaned = {code: max(0.0, float(weight)) for code, weight in weights.items() if weight and weight > 0}
    total = sum(cleaned.values())
    if total <= 0:
        return {}
    return {code: weight / total for code, weight in cleaned.items()}


def _top_equal(scores: Dict[str, float], top_k: int) -> Dict[str, float]:
    ranked = [(code, score) for code, score in scores.items() if np.isfinite(score)]
    ranked.sort(key=lambda item: item[1], reverse=True)
    selected = [code for code, _ in ranked[: max(0, top_k)]]
    if not selected:
        return {}
    weight = 1.0 / len(selected)
    return {code: weight for code in selected}


def _score_dict(scores: pd.Series, limit: int = 10) -> Dict[str, float]:
    cleaned = scores.replace([np.inf, -np.inf], np.nan).dropna().sort_values(ascending=False).head(limit)
    return {str(code): round(float(value), 6) for code, value in cleaned.items()}


def _signal_from_scores(
    scores: pd.Series,
    eligible: pd.Series,
    top_k: int,
    empty_reason: str = "no_eligible_asset",
    selected_reason: str = "selected",
) -> StrategySignal:
    eligible_scores = scores[eligible].replace([np.inf, -np.inf], np.nan).dropna()
    weights = _top_equal(eligible_scores.to_dict(), top_k)
    return StrategySignal(
        weights=weights,
        scores=_score_dict(scores),
        eligible=[str(code) for code in eligible_scores.index.tolist()],
        reason=selected_reason if weights else empty_reason,
    )


def _empty_signal(reason: str) -> StrategySignal:
    return StrategySignal(weights={}, reason=reason)


def _empty_rule_mask(
    ctx: StrategyContext,
    idx: int,
    rule: str,
    score: pd.Series,
    ret: pd.Series,
    trend_ma: int,
    trend_fast_ma: Optional[int] = None,
) -> pd.Series:
    if rule == "score_gt_0":
        return score > 0
    if rule == "trend_filter":
        ma = _ma(ctx.close, trend_ma).iloc[idx]
        trend_ok = (ctx.close.iloc[idx] > ma) & (ret > 0)
        if trend_fast_ma and trend_fast_ma > 0:
            fast_ma = _ma(ctx.close, trend_fast_ma).iloc[idx]
            trend_ok = trend_ok & (fast_ma > ma)
        return trend_ok
    return ret > 0


def _safe_value(frame: pd.DataFrame, date: pd.Timestamp, code: str) -> Optional[float]:
    if code not in frame.columns or date not in frame.index:
        return None
    return _clean_float(frame.at[date, code])


def _position_value(shares: Dict[str, float], prices: pd.Series) -> float:
    value = 0.0
    for code, quantity in shares.items():
        quantity = _clean_float(quantity, 0.0) or 0.0
        if quantity <= 0:
            continue
        price = _clean_float(prices.get(code))
        if price is None or price <= 0:
            continue
        value += quantity * price
    return value


def _position_weights(shares: Dict[str, float], prices: pd.Series, equity: float) -> Dict[str, float]:
    if equity <= 0:
        return {}
    weights: Dict[str, float] = {}
    for code, quantity in shares.items():
        quantity = _clean_float(quantity, 0.0) or 0.0
        price = _clean_float(prices.get(code))
        if quantity > 0 and price is not None and price > 0:
            weight = quantity * price / equity
            if weight > MIN_POSITION_WEIGHT:
                weights[code] = weight
    return weights


def _ret(close: pd.DataFrame, idx: int, window: int) -> pd.Series:
    if idx < window:
        return pd.Series(index=close.columns, dtype=float)
    prev = close.iloc[idx - window]
    curr = close.iloc[idx]
    return curr / prev - 1.0


def _ma(close: pd.DataFrame, window: int) -> pd.DataFrame:
    return close.rolling(window=window, min_periods=window).mean()


def _vol(returns: pd.DataFrame, window: int) -> pd.DataFrame:
    return returns.rolling(window=window, min_periods=max(5, window // 2)).std() * sqrt(252)


def _multi_window_score(
    ctx: StrategyContext,
    idx: int,
    windows: Iterable[int],
    weights: Iterable[float],
) -> pd.Series:
    score = pd.Series(0.0, index=ctx.close.columns)
    for window, weight in zip(windows, weights):
        score = score.add(_ret(ctx.close, idx, int(window)) * float(weight), fill_value=0)
    return score


def _market_regime_series(ctx: StrategyContext) -> pd.Series:
    if "510300" in ctx.close.columns:
        return ctx.close["510300"]
    equal_returns = ctx.returns.mean(axis=1).fillna(0)
    return (1 + equal_returns).cumprod()


def _rebalance_dates(index: pd.DatetimeIndex, frequency: str) -> List[pd.Timestamp]:
    if len(index) < 2:
        return []
    if frequency == "monthly":
        freq = "ME"
    else:
        freq = "W-FRI"
    grouped = pd.Series(index=index, data=index).groupby(pd.Grouper(freq=freq)).last().dropna()
    dates = [date for date in grouped.tolist() if date in index and date != index[-1]]
    if frequency == "biweekly":
        return dates[::2]
    return dates


def _momentum_enhanced(ctx: StrategyContext, date: pd.Timestamp, params: Dict[str, Any]) -> StrategySignal:
    idx = ctx.close.index.get_loc(date)
    top_k = int(params.get("top_k", 2))
    windows = params.get("momentum_windows", [20, 60, 120])
    weights = params.get("momentum_weights", [0.4, 0.4, 0.2])
    trend_ma = int(params.get("trend_ma", 120))
    trend_fast_ma = int(params.get("trend_fast_ma", 0) or 0)
    vol_window = int(params.get("vol_window", 60))

    score = _multi_window_score(ctx, idx, windows, weights)
    volatility = _vol(ctx.returns, vol_window).iloc[idx]
    score = score - float(params.get("vol_penalty", 0.08)) * volatility

    ret60 = _ret(ctx.close, idx, int(params.get("absolute_window", 60)))
    eligible = _empty_rule_mask(
        ctx, idx, str(params.get("empty_threshold", "trend_filter")), score, ret60, trend_ma, trend_fast_ma
    )
    return _signal_from_scores(score, eligible, top_k)


def _vol_adjusted_momentum(ctx: StrategyContext, date: pd.Timestamp, params: Dict[str, Any]) -> StrategySignal:
    idx = ctx.close.index.get_loc(date)
    top_k = int(params.get("top_k", 3))
    ret_fast = _ret(ctx.close, idx, int(params.get("fast_window", 60)))
    ret_slow = _ret(ctx.close, idx, int(params.get("slow_window", 120)))
    vol_fast = _vol(ctx.returns, int(params.get("fast_vol_window", 60))).iloc[idx]
    vol_slow = _vol(ctx.returns, int(params.get("slow_vol_window", 120))).iloc[idx]
    score = ret_fast / vol_fast.replace(0, np.nan) + 0.5 * ret_slow / vol_slow.replace(0, np.nan)
    eligible = _empty_rule_mask(
        ctx,
        idx,
        str(params.get("empty_threshold", "ret_gt_0")),
        score,
        ret_fast,
        int(params.get("trend_ma", 120)),
        int(params.get("trend_fast_ma", 0) or 0),
    )
    ranked = score[eligible].dropna().sort_values(ascending=False).head(top_k)
    if ranked.empty:
        eligible_scores = score[eligible].replace([np.inf, -np.inf], np.nan).dropna()
        return StrategySignal(
            weights={},
            scores=_score_dict(score),
            eligible=[str(code) for code in eligible_scores.index.tolist()],
            reason="no_eligible_asset",
        )
    inverse_vol = (1 / vol_fast[ranked.index].replace(0, np.nan)).dropna()
    raw = inverse_vol.to_dict() if not inverse_vol.empty else {code: 1.0 for code in ranked.index}
    capped = {code: min(float(weight), float(params.get("max_weight", 0.5))) for code, weight in raw.items()}
    return StrategySignal(
        weights=_normalize_weights(capped),
        scores=_score_dict(score),
        eligible=[str(code) for code in score[eligible].dropna().index.tolist()],
        reason="selected",
    )


def _dual_momentum_core(ctx: StrategyContext, date: pd.Timestamp, params: Dict[str, Any]) -> StrategySignal:
    idx = ctx.close.index.get_loc(date)
    top_k = int(params.get("top_k", 1))
    window = int(params.get("momentum_window", 120))
    trend_ma = int(params.get("trend_ma", 120))
    trend_fast_ma = int(params.get("trend_fast_ma", 0) or 0)
    ret = _ret(ctx.close, idx, window)
    eligible = _empty_rule_mask(
        ctx, idx, str(params.get("empty_threshold", "trend_filter")), ret, ret, trend_ma, trend_fast_ma
    )
    return _signal_from_scores(ret, eligible, top_k)


def _trend_following_equal_weight(ctx: StrategyContext, date: pd.Timestamp, params: Dict[str, Any]) -> StrategySignal:
    idx = ctx.close.index.get_loc(date)
    top_k = int(params.get("top_k", 5))
    ma_fast = _ma(ctx.close, int(params.get("fast_ma", 20))).iloc[idx]
    ma_slow = _ma(ctx.close, int(params.get("slow_ma", 60))).iloc[idx]
    ret = _ret(ctx.close, idx, int(params.get("score_window", 60)))
    rule = str(params.get("empty_threshold", "trend_filter"))
    if rule == "score_gt_0":
        eligible = ret > 0
    elif rule == "ret_gt_0":
        eligible = ret > 0
    else:
        eligible = (ctx.close.iloc[idx] > ma_slow) & (ma_fast > ma_slow) & (ret > 0)
    return _signal_from_scores(ret, eligible, top_k)


def _adaptive_regime_rotation(ctx: StrategyContext, date: pd.Timestamp, params: Dict[str, Any]) -> StrategySignal:
    idx = ctx.close.index.get_loc(date)
    regime_fast_ma = int(params.get("regime_fast_ma", 20))
    regime_slow_ma = int(params.get("regime_slow_ma", 120))
    regime_window = int(params.get("regime_momentum_window", 60))
    if idx < max(regime_slow_ma, regime_window):
        return _empty_signal("warmup")

    market = _market_regime_series(ctx)
    market_now = _clean_float(market.iloc[idx])
    market_prev = _clean_float(market.iloc[idx - regime_window])
    fast_ma = _clean_float(market.rolling(regime_fast_ma, min_periods=regime_fast_ma).mean().iloc[idx])
    slow_ma = _clean_float(market.rolling(regime_slow_ma, min_periods=regime_slow_ma).mean().iloc[idx])
    if market_now is None or market_prev is None or market_prev <= 0 or fast_ma is None or slow_ma is None:
        return _empty_signal("warmup")

    market_ret = market_now / market_prev - 1
    up_threshold = float(params.get("regime_up_threshold", 0.02))
    down_threshold = float(params.get("regime_down_threshold", -0.02))
    uptrend = market_now > slow_ma and fast_ma > slow_ma and market_ret > up_threshold
    downtrend = market_now < slow_ma and fast_ma < slow_ma and market_ret < down_threshold

    trend_ma = int(params.get("trend_ma", 120))
    trend_fast_ma = int(params.get("trend_fast_ma", 20))
    vol_window = int(params.get("vol_window", 60))
    volatility = _vol(ctx.returns, vol_window).iloc[idx]

    if uptrend:
        windows = params.get("momentum_windows", [40, 120, 250])
        weights = params.get("momentum_weights", [0.3, 0.5, 0.2])
        score = _multi_window_score(ctx, idx, windows, weights) - float(params.get("vol_penalty", 0.03)) * volatility
        ret = _ret(ctx.close, idx, int(params.get("absolute_window", 60)))
        eligible = _empty_rule_mask(ctx, idx, "trend_filter", score, ret, trend_ma, trend_fast_ma)
        return _signal_from_scores(
            score,
            eligible,
            int(params.get("top_k_uptrend", params.get("top_k", 1))),
            empty_reason="regime_uptrend_no_asset",
            selected_reason="regime_uptrend",
        )

    if downtrend:
        defensive_codes = {str(code).zfill(6) for code in params.get("defensive_codes", DEFAULT_DEFENSIVE_UNIVERSE)}
        defensive_window = int(params.get("defensive_window", 60))
        ret = _ret(ctx.close, idx, defensive_window)
        defensive_vol = _vol(ctx.returns, defensive_window).iloc[idx].replace(0, np.nan)
        score = ret / defensive_vol
        defensive_mask = pd.Series([code in defensive_codes for code in ctx.close.columns], index=ctx.close.columns)
        defensive_ma = _ma(ctx.close, int(params.get("defensive_ma", 120))).iloc[idx]
        eligible = defensive_mask & (ret > 0) & (ctx.close.iloc[idx] > defensive_ma)
        return _signal_from_scores(
            score,
            eligible,
            int(params.get("top_k_downtrend", 1)),
            empty_reason="regime_downtrend_cash",
            selected_reason="regime_downtrend_defensive",
        )

    range_window = int(params.get("range_window", 40))
    range_ma_window = int(params.get("range_ma", 60))
    ret = _ret(ctx.close, idx, range_window)
    range_vol = _vol(ctx.returns, int(params.get("range_vol_window", 20))).iloc[idx].replace(0, np.nan)
    score = ret / range_vol - float(params.get("range_vol_penalty", 0.02)) * range_vol
    range_ma = _ma(ctx.close, range_ma_window).iloc[idx]
    eligible = (ret > 0) & (ctx.close.iloc[idx] > range_ma)
    return _signal_from_scores(
        score,
        eligible,
        int(params.get("top_k_range", 2)),
        empty_reason="regime_range_no_asset",
        selected_reason="regime_range",
    )


def _donchian_breakout_rotation(ctx: StrategyContext, date: pd.Timestamp, params: Dict[str, Any]) -> StrategySignal:
    idx = ctx.close.index.get_loc(date)
    top_k = int(params.get("top_k", 2))
    lookback = int(params.get("lookback", 60))
    if idx < lookback:
        return _empty_signal("warmup")
    high = ctx.close.iloc[idx - lookback + 1 : idx + 1].max()
    ret20 = _ret(ctx.close, idx, int(params.get("momentum_window", 20)))
    vol20 = _vol(ctx.returns, int(params.get("vol_window", 20))).iloc[idx]
    threshold = float(params.get("breakout_buffer", 0.98))
    eligible = (ctx.close.iloc[idx] >= high * threshold) & (ret20 > 0)
    score = ret20 - 0.5 * vol20
    return _signal_from_scores(score, eligible, top_k)


def _rsrs_timing_rotation(ctx: StrategyContext, date: pd.Timestamp, params: Dict[str, Any]) -> StrategySignal:
    idx = ctx.close.index.get_loc(date)
    top_k = int(params.get("top_k", 2))
    window = int(params.get("rsrs_window", 18))
    z_window = int(params.get("z_window", 120))
    if idx < window + 5:
        return _empty_signal("warmup")
    cov = ctx.high.rolling(window).cov(ctx.low)
    var = ctx.low.rolling(window).var().replace(0, np.nan)
    slope = cov / var
    z = (slope - slope.rolling(z_window, min_periods=window).mean()) / slope.rolling(
        z_window, min_periods=window
    ).std()
    z_now = z.iloc[idx]
    ret = _ret(ctx.close, idx, int(params.get("momentum_window", 60)))
    threshold = float(params.get("z_threshold", 0.7))
    eligible = (z_now > threshold) & (ret > 0)
    score = ret + 0.2 * z_now
    return _signal_from_scores(score, eligible, top_k)


def _last_fractals(
    frame: Dict[str, pd.DataFrame], idx: int, code: str, lookback: int
) -> Tuple[Optional[int], Optional[int]]:
    highs = frame["high"][code].iloc[max(0, idx - lookback) : idx + 1]
    lows = frame["low"][code].iloc[max(0, idx - lookback) : idx + 1]
    offset = max(0, idx - lookback)
    last_bottom = None
    last_top = None
    for local in range(1, len(highs) - 1):
        if lows.iloc[local] < lows.iloc[local - 1] and lows.iloc[local] < lows.iloc[local + 1]:
            last_bottom = offset + local
        if highs.iloc[local] > highs.iloc[local - 1] and highs.iloc[local] > highs.iloc[local + 1]:
            last_top = offset + local
    return last_bottom, last_top


def _chan_fractal_rotation(ctx: StrategyContext, date: pd.Timestamp, params: Dict[str, Any]) -> StrategySignal:
    idx = ctx.close.index.get_loc(date)
    top_k = int(params.get("top_k", 2))
    lookback = int(params.get("lookback", 80))
    ma20 = _ma(ctx.close, int(params.get("ma", 20))).iloc[idx]
    scores: Dict[str, float] = {}
    frame = {"high": ctx.high, "low": ctx.low}
    for code in ctx.close.columns:
        bottom_idx, top_idx = _last_fractals(frame, idx - 2, code, lookback) if idx > 3 else (None, None)
        close_now = _safe_value(ctx.close, date, code)
        if bottom_idx is None or close_now is None or close_now <= ma20.get(code, np.nan):
            continue
        if top_idx is not None and top_idx > bottom_idx:
            continue
        bottom_price = ctx.low[code].iloc[bottom_idx]
        drawdown = abs(ctx.close[code].iloc[max(0, idx - 20) : idx + 1].min() / close_now - 1)
        scores[code] = float(close_now / bottom_price - 1) - float(drawdown)
    return StrategySignal(
        weights=_top_equal(scores, top_k),
        scores=dict(sorted(scores.items(), key=lambda item: item[1], reverse=True)[:10]),
        eligible=list(scores.keys()),
        reason="selected" if scores else "no_chan_fractal_setup",
    )


def _chan_center_breakout(ctx: StrategyContext, date: pd.Timestamp, params: Dict[str, Any]) -> StrategySignal:
    idx = ctx.close.index.get_loc(date)
    top_k = int(params.get("top_k", 2))
    segment = int(params.get("segment", 20))
    if idx < segment * 3:
        return _empty_signal("warmup")
    scores: Dict[str, float] = {}
    for code in ctx.close.columns:
        ranges = []
        for n in range(3, 0, -1):
            part = slice(idx - segment * n + 1, idx - segment * (n - 1) + 1)
            ranges.append((ctx.low[code].iloc[part].min(), ctx.high[code].iloc[part].max()))
        center_low = max(low for low, _ in ranges)
        center_high = min(high for _, high in ranges)
        close_now = _safe_value(ctx.close, date, code)
        if close_now is None or center_low >= center_high:
            continue
        recent_low = ctx.low[code].iloc[idx - segment + 1 : idx + 1].min()
        if close_now > center_high and recent_low > center_low:
            scores[code] = float(close_now / center_high - 1)
    return StrategySignal(
        weights=_top_equal(scores, top_k),
        scores=dict(sorted(scores.items(), key=lambda item: item[1], reverse=True)[:10]),
        eligible=list(scores.keys()),
        reason="selected" if scores else "no_center_breakout",
    )


STRATEGIES: Dict[str, StrategyFn] = {
    "industry_momentum_enhanced": _momentum_enhanced,
    "vol_adjusted_momentum": _vol_adjusted_momentum,
    "dual_momentum_core": _dual_momentum_core,
    "trend_following_equal_weight": _trend_following_equal_weight,
    "adaptive_regime_rotation": _adaptive_regime_rotation,
    "biweekly_adaptive_stable_rotation": _adaptive_regime_rotation,
    "donchian_breakout_rotation": _donchian_breakout_rotation,
    "rsrs_timing_rotation": _rsrs_timing_rotation,
    "chan_fractal_rotation": _chan_fractal_rotation,
    "chan_center_breakout": _chan_center_breakout,
}


class BacktestEngine:
    def run(self, records_by_code: Dict[str, List[Dict[str, Any]]], config: BacktestConfig) -> Dict[str, Any]:
        if config.strategy_id not in STRATEGIES:
            raise ValueError(f"Unsupported strategy: {config.strategy_id}")

        ctx = self._build_context(records_by_code, config.start_date, config.end_date)
        trade_index = ctx.close.loc[config.start_date : config.end_date].dropna(how="all").index
        if ctx.close.empty or len(trade_index) < 30:
            raise ValueError("Not enough ETF daily data for backtest")

        strategy_fn = STRATEGIES[config.strategy_id]
        params = self._strategy_params(config.strategy_id, config.params)
        frequency = params.get("rebalance_frequency") or self._default_frequency(config.strategy_id)
        cash_entry_mode = params.get("cash_entry_mode", "daily_when_cash")
        cash_entry_confirmations = self._int_param(params, "cash_entry_confirmations", 2, minimum=1)
        min_days_to_rebalance_for_cash_entry = self._int_param(
            params, "min_days_to_rebalance_for_cash_entry", 2, minimum=0
        )
        params["cash_entry_confirmations"] = cash_entry_confirmations
        params["min_days_to_rebalance_for_cash_entry"] = min_days_to_rebalance_for_cash_entry
        signal_dates = set(_rebalance_dates(trade_index, frequency))
        signal_positions = [idx for idx, date in enumerate(trade_index) if date in signal_dates]
        entry_delay = self._bounded_entry_delay(config.entry_delay_trading_days, len(trade_index))
        next_signal_pos_by_pos: Dict[int, Optional[int]] = {}
        signal_pos_cursor = 0
        for idx in range(len(trade_index)):
            while signal_pos_cursor < len(signal_positions) and signal_positions[signal_pos_cursor] <= idx:
                signal_pos_cursor += 1
            next_signal_pos_by_pos[idx] = (
                signal_positions[signal_pos_cursor] if signal_pos_cursor < len(signal_positions) else None
            )
        next_by_date = {
            trade_index[i]: trade_index[i + 1] for i in range(len(trade_index) - 1)
        }

        cash = float(config.initial_cash)
        shares = {code: 0.0 for code in ctx.close.columns}
        pending_targets: Dict[pd.Timestamp, Dict[str, float]] = {}
        equity_curve: List[Dict[str, Any]] = []
        position_records: List[Dict[str, Any]] = []
        signal_records: List[Dict[str, Any]] = []
        trades: List[Dict[str, Any]] = []
        turnover_values: List[float] = []
        cash_days = 0
        cash_entry_streak = 0
        cash_entry_signature: Tuple[str, ...] = tuple()
        attribution_values = {code: 0.0 for code in ctx.close.columns}
        active_days = {code: 0 for code in ctx.close.columns}
        weight_sums = {code: 0.0 for code in ctx.close.columns}
        holding_start_positions: Dict[str, int] = {}
        previous_close_prices: Optional[pd.Series] = None

        for position, date in enumerate(trade_index):
            open_prices = ctx.open.loc[date]
            shares_before_trades = dict(shares)
            if date in pending_targets:
                cash, turnover, new_trades = self._execute_rebalance(
                    date, ctx, shares, cash, pending_targets.pop(date), config
                )
                turnover_values.append(turnover)
                trades.extend(new_trades)
                cash_entry_streak = 0
                cash_entry_signature = tuple()

            close_prices = ctx.close.loc[date]
            equity = cash + _position_value(shares, close_prices)
            weights = _position_weights(shares, close_prices, equity)
            if not weights:
                cash_days += 1

            equity_curve.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "equity": round(float(equity), 4),
                    "cash": round(float(cash), 4),
                    "cash_weight": round(float(cash / equity), 6) if equity > 0 else 1.0,
                }
            )
            position_records.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "weights": {code: round(float(weight), 6) for code, weight in weights.items()},
                }
            )
            for code, weight in weights.items():
                active_days[code] = active_days.get(code, 0) + 1
                weight_sums[code] = weight_sums.get(code, 0.0) + float(weight)
            for code in list(holding_start_positions):
                if code not in weights:
                    holding_start_positions.pop(code, None)
            for code in weights:
                holding_start_positions.setdefault(code, position)
            if previous_close_prices is not None:
                self._accumulate_return_attribution(
                    attribution_values,
                    shares_before_trades,
                    shares,
                    previous_close_prices,
                    open_prices,
                    close_prices,
                )
            previous_close_prices = close_prices

            initial_entry_blocked = not weights and position < entry_delay
            periodic_signal = date in signal_dates and not initial_entry_blocked
            cash_daily_scan = (
                cash_entry_mode == "daily_when_cash"
                and not weights
                and not periodic_signal
                and not initial_entry_blocked
            )
            if periodic_signal or cash_daily_scan:
                signal = strategy_fn(ctx, date, params)
                execute_date = next_by_date.get(date)
                if execute_date is not None:
                    raw_target_weights = _normalize_weights(signal.weights)
                    target_weights, stability = self._stabilize_target_weights(
                        signal,
                        raw_target_weights,
                        weights,
                        holding_start_positions,
                        position,
                        params,
                    )
                    if periodic_signal:
                        pending_targets[execute_date] = target_weights
                        signal_records.append(
                            {
                                "date": date.strftime("%Y-%m-%d"),
                                "execute_date": execute_date.strftime("%Y-%m-%d"),
                                "trigger": "periodic",
                                "reason": signal.reason,
                                "eligible_count": len(signal.eligible),
                                "eligible": signal.eligible[:20],
                                "raw_selected": list(raw_target_weights.keys()),
                                "selected": list(target_weights.keys()),
                                "target_weights": {
                                    code: round(float(weight), 6) for code, weight in target_weights.items()
                                },
                                "scores": signal.scores,
                                "stability": stability,
                            }
                        )
                        cash_entry_streak = 0
                        cash_entry_signature = tuple()
                    elif target_weights:
                        selected_signature = tuple(sorted(target_weights.keys()))
                        if selected_signature == cash_entry_signature:
                            cash_entry_streak += 1
                        else:
                            cash_entry_signature = selected_signature
                            cash_entry_streak = 1

                        next_rebalance_pos = next_signal_pos_by_pos.get(position)
                        days_to_next_rebalance = (
                            next_rebalance_pos - position if next_rebalance_pos is not None else None
                        )
                        far_from_next_rebalance = (
                            days_to_next_rebalance is None
                            or days_to_next_rebalance > min_days_to_rebalance_for_cash_entry
                        )
                        if cash_entry_streak >= cash_entry_confirmations and far_from_next_rebalance:
                            pending_targets[execute_date] = target_weights
                            signal_records.append(
                                {
                                    "date": date.strftime("%Y-%m-%d"),
                                    "execute_date": execute_date.strftime("%Y-%m-%d"),
                                    "trigger": "cash_confirmed_scan",
                                    "reason": signal.reason,
                                    "eligible_count": len(signal.eligible),
                                    "eligible": signal.eligible[:20],
                                    "raw_selected": list(raw_target_weights.keys()),
                                    "selected": list(target_weights.keys()),
                                    "target_weights": {
                                        code: round(float(weight), 6)
                                        for code, weight in target_weights.items()
                                    },
                                    "scores": signal.scores,
                                    "stability": stability,
                                    "cash_entry_streak": cash_entry_streak,
                                    "days_to_next_rebalance": days_to_next_rebalance,
                                }
                            )
                    else:
                        cash_entry_streak = 0
                        cash_entry_signature = tuple()

        metrics = self._metrics(equity_curve, trades, turnover_values, cash_days)
        return {
            "strategy_id": config.strategy_id,
            "params": params,
            "start_date": config.start_date,
            "end_date": config.end_date,
            "metrics": metrics,
            "equity_curve": equity_curve,
            "positions": position_records,
            "signals": signal_records,
            "trades": trades,
            "diagnostics": self._diagnostics(
                ctx,
                config,
                metrics,
                attribution_values,
                active_days,
                weight_sums,
                len(equity_curve),
            ),
        }

    def _build_context(self, records_by_code: Dict[str, List[Dict[str, Any]]], start: str, end: str) -> StrategyContext:
        frames: Dict[str, pd.DataFrame] = {}
        for code, records in records_by_code.items():
            if not records:
                continue
            df = pd.DataFrame(records)
            date_col = "trade_date" if "trade_date" in df.columns else "date"
            if date_col not in df.columns:
                continue
            df[date_col] = pd.to_datetime(df[date_col])
            df = df.sort_values(date_col).drop_duplicates(date_col).set_index(date_col)
            for col in ("open", "high", "low", "close", "volume"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            frames[code] = df

        def build(field: str) -> pd.DataFrame:
            data = {code: df[field] for code, df in frames.items() if field in df.columns}
            return pd.DataFrame(data).sort_index()

        close = build("close").loc[:end].ffill()
        open_ = build("open").reindex(close.index).ffill()
        high = build("high").reindex(close.index).ffill()
        low = build("low").reindex(close.index).ffill()
        volume = build("volume").reindex(close.index).fillna(0)
        valid_cols = [col for col in close.columns if close[col].notna().sum() >= 30]
        close = close[valid_cols].dropna(how="all")
        return StrategyContext(
            close=close,
            open=open_[valid_cols].reindex(close.index).fillna(close),
            high=high[valid_cols].reindex(close.index).fillna(close),
            low=low[valid_cols].reindex(close.index).fillna(close),
            volume=volume[valid_cols].reindex(close.index),
            returns=close.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0),
        )

    def _stabilize_target_weights(
        self,
        signal: StrategySignal,
        raw_target_weights: Dict[str, float],
        current_weights: Dict[str, float],
        holding_start_positions: Dict[str, int],
        position: int,
        params: Dict[str, Any],
    ) -> Tuple[Dict[str, float], Dict[str, Any]]:
        if not raw_target_weights or not current_weights:
            return raw_target_weights, {}

        min_holding_days = self._int_param(params, "min_holding_days", 0, minimum=0)
        rank_switch_buffer = self._int_param(params, "rank_switch_buffer", 0, minimum=0)
        turnover_threshold = float(params.get("rebalance_turnover_threshold", 0.0) or 0.0)
        if min_holding_days <= 0 and rank_switch_buffer <= 0 and turnover_threshold <= 0:
            return raw_target_weights, {}

        target_count = max(1, len(raw_target_weights))
        ranked_codes = [
            code
            for code, value in sorted(signal.scores.items(), key=lambda item: item[1], reverse=True)
            if np.isfinite(value)
        ]
        rank_by_code = {code: index + 1 for index, code in enumerate(ranked_codes)}
        eligible = set(signal.eligible)
        kept: List[str] = []
        keep_reasons: Dict[str, str] = {}
        for code in current_weights:
            if code not in eligible or code not in rank_by_code:
                continue
            holding_days = position - holding_start_positions.get(code, position)
            rank = rank_by_code[code]
            if min_holding_days > 0 and holding_days < min_holding_days:
                kept.append(code)
                keep_reasons[code] = f"min_holding_days:{holding_days}/{min_holding_days}"
            elif rank_switch_buffer > 0 and rank <= target_count + rank_switch_buffer:
                kept.append(code)
                keep_reasons[code] = f"rank_buffer:{rank}<={target_count + rank_switch_buffer}"

        if kept:
            combined: List[str] = []
            for code in kept + list(raw_target_weights.keys()):
                if code not in combined:
                    combined.append(code)
            target_weights = _normalize_weights({code: 1.0 for code in combined[:target_count]})
        else:
            target_weights = raw_target_weights

        turnover = self._target_turnover(current_weights, target_weights)
        skipped_by_turnover = False
        if turnover_threshold > 0 and 0 < turnover < turnover_threshold:
            target_weights = _normalize_weights(current_weights)
            skipped_by_turnover = True

        return target_weights, {
            "kept": kept,
            "keep_reasons": keep_reasons,
            "raw_selected": list(raw_target_weights.keys()),
            "turnover": round(float(turnover), 6),
            "turnover_threshold": turnover_threshold,
            "skipped_by_turnover": skipped_by_turnover,
        }

    @staticmethod
    def _target_turnover(current_weights: Dict[str, float], target_weights: Dict[str, float]) -> float:
        codes = set(current_weights) | set(target_weights)
        return 0.5 * sum(abs(float(target_weights.get(code, 0.0)) - float(current_weights.get(code, 0.0))) for code in codes)

    def _execute_rebalance(
        self,
        date: pd.Timestamp,
        ctx: StrategyContext,
        shares: Dict[str, float],
        cash: float,
        target_weights: Dict[str, float],
        config: BacktestConfig,
    ) -> Tuple[float, float, List[Dict[str, Any]]]:
        open_prices = ctx.open.loc[date]
        equity_before = cash + _position_value(shares, open_prices)
        if equity_before <= 0:
            return cash, 0.0, []

        trades: List[Dict[str, Any]] = []
        traded_notional = 0.0
        commission_rate = config.commission_bps / 10000.0
        slippage_rate = config.slippage_bps / 10000.0

        planned_orders = []
        for code in list(shares.keys()):
            price = _clean_float(open_prices.get(code))
            if price is None or price <= 0:
                continue
            current_value = shares[code] * price
            target_value = equity_before * target_weights.get(code, 0.0)
            delta_value = target_value - current_value
            if abs(delta_value) < max(1.0, equity_before * 0.0001):
                continue
            side = "buy" if delta_value > 0 else "sell"
            planned_orders.append((0 if side == "sell" else 1, code, side, price, delta_value))

        for _, code, side, price, delta_value in sorted(planned_orders):
            execution_price = price * (1 + slippage_rate) if side == "buy" else price * (1 - slippage_rate)
            quantity = abs(delta_value) / execution_price
            amount = quantity * execution_price
            fee = amount * commission_rate

            if side == "buy":
                available = max(0.0, cash)
                if amount + fee > available:
                    scale = available / (amount + fee) if amount + fee > 0 else 0
                    quantity *= scale
                    amount *= scale
                    fee *= scale
                if quantity <= 0:
                    continue
                shares[code] += quantity
                cash -= amount + fee
            else:
                quantity = min(quantity, shares[code])
                if quantity <= 0:
                    continue
                amount = quantity * execution_price
                fee = amount * commission_rate
                shares[code] -= quantity
                if shares[code] < MIN_SHARE_QUANTITY:
                    shares[code] = 0.0
                cash += amount - fee

            traded_notional += amount
            trades.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "code": code,
                    "side": side,
                    "quantity": round(float(quantity), 4),
                    "price": round(float(execution_price), 4),
                    "amount": round(float(amount), 4),
                    "commission": round(float(fee), 4),
                }
            )

        return cash, traded_notional / equity_before, trades

    def _accumulate_return_attribution(
        self,
        attribution_values: Dict[str, float],
        shares_before_trades: Dict[str, float],
        shares_after_trades: Dict[str, float],
        previous_close_prices: pd.Series,
        open_prices: pd.Series,
        close_prices: pd.Series,
    ) -> None:
        for code in attribution_values:
            previous_close = _clean_float(previous_close_prices.get(code))
            open_price = _clean_float(open_prices.get(code))
            close_price = _clean_float(close_prices.get(code))
            if previous_close is None or open_price is None or close_price is None:
                continue
            quantity_before = _clean_float(shares_before_trades.get(code), 0.0) or 0.0
            quantity_after = _clean_float(shares_after_trades.get(code), 0.0) or 0.0
            gap_pnl = quantity_before * (open_price - previous_close)
            intraday_pnl = quantity_after * (close_price - open_price)
            attribution_values[code] += float(gap_pnl + intraday_pnl)

    def _metrics(
        self,
        equity_curve: List[Dict[str, Any]],
        trades: List[Dict[str, Any]],
        turnover_values: List[float],
        cash_days: int,
    ) -> Dict[str, Any]:
        equity = pd.Series([row["equity"] for row in equity_curve], dtype=float)
        if equity.empty:
            return {}
        daily_returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0)
        total_return = equity.iloc[-1] / equity.iloc[0] - 1
        years = max(len(equity) / 252.0, 1 / 252)
        annual_return = (1 + total_return) ** (1 / years) - 1
        annual_vol = daily_returns.std() * sqrt(252)
        sharpe = daily_returns.mean() / daily_returns.std() * sqrt(252) if daily_returns.std() > 0 else 0.0
        drawdown = equity / equity.cummax() - 1
        max_drawdown = drawdown.min()
        calmar = annual_return / abs(max_drawdown) if max_drawdown < 0 else 0.0
        total_commission = sum(float(trade.get("commission", 0) or 0) for trade in trades)
        return {
            "total_return": round(float(total_return), 6),
            "annual_return": round(float(annual_return), 6),
            "annual_volatility": round(float(annual_vol), 6),
            "sharpe": round(float(sharpe), 6),
            "max_drawdown": round(float(max_drawdown), 6),
            "calmar": round(float(calmar), 6),
            "win_rate": round(float((daily_returns > 0).mean()), 6),
            "trade_count": len(trades),
            "avg_turnover": round(float(np.mean(turnover_values)), 6) if turnover_values else 0.0,
            "cash_days_ratio": round(float(cash_days / len(equity_curve)), 6) if equity_curve else 1.0,
            "total_commission": round(float(total_commission), 4),
            "commission_ratio": round(float(total_commission / equity.iloc[0]), 6) if equity.iloc[0] else 0.0,
        }

    def _diagnostics(
        self,
        ctx: StrategyContext,
        config: BacktestConfig,
        metrics: Dict[str, Any],
        attribution_values: Dict[str, float],
        active_days: Dict[str, int],
        weight_sums: Dict[str, float],
        total_days: int,
    ) -> Dict[str, Any]:
        close = ctx.close.loc[config.start_date : config.end_date]
        returns = close.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0)
        asset_returns: Dict[str, float] = {}
        for code in close.columns:
            series = close[code].dropna()
            if len(series) >= 2 and series.iloc[0] > 0:
                asset_returns[code] = round(float(series.iloc[-1] / series.iloc[0] - 1), 6)

        benchmark_code = "510300" if "510300" in asset_returns else next(iter(asset_returns), None)
        benchmark_return = asset_returns.get(benchmark_code) if benchmark_code else None
        daily_equal_returns = returns.mean(axis=1).fillna(0)
        equal_weight_return = float((1 + daily_equal_returns).prod() - 1) if not daily_equal_returns.empty else None
        best_asset = max(asset_returns.items(), key=lambda item: item[1]) if asset_returns else None
        worst_asset = min(asset_returns.items(), key=lambda item: item[1]) if asset_returns else None
        attribution = self._return_attribution(
            config,
            metrics,
            asset_returns,
            attribution_values,
            active_days,
            weight_sums,
            total_days,
        )

        return {
            "benchmark_code": benchmark_code,
            "benchmark_return": benchmark_return,
            "equal_weight_return": round(equal_weight_return, 6) if equal_weight_return is not None else None,
            "best_asset": {"code": best_asset[0], "return": best_asset[1]} if best_asset else None,
            "worst_asset": {"code": worst_asset[0], "return": worst_asset[1]} if worst_asset else None,
            "return_attribution": attribution["items"],
            "return_attribution_residual": attribution["residual"],
            "active_days_ratio": round(float(1 - metrics.get("cash_days_ratio", 1)), 6),
            "trading_days": int(len(close.index)),
            "data_start": close.index[0].strftime("%Y-%m-%d") if len(close.index) else config.start_date,
            "data_end": close.index[-1].strftime("%Y-%m-%d") if len(close.index) else config.end_date,
            "price_adjust": config.price_adjust,
            "entry_delay_trading_days": self._bounded_entry_delay(
                config.entry_delay_trading_days,
                int(len(close.index)),
            ),
        }

    def _return_attribution(
        self,
        config: BacktestConfig,
        metrics: Dict[str, Any],
        asset_returns: Dict[str, float],
        attribution_values: Dict[str, float],
        active_days: Dict[str, int],
        weight_sums: Dict[str, float],
        total_days: int,
    ) -> Dict[str, Any]:
        name_by_code = {item["code"]: item["name"] for item in DEFAULT_ETF_UNIVERSE}
        initial_cash = max(float(config.initial_cash), 1.0)
        total_return = float(metrics.get("total_return", 0.0) or 0.0)
        items: List[Dict[str, Any]] = []
        for code in config.universe:
            code = str(code).zfill(6)
            contribution = float(attribution_values.get(code, 0.0)) / initial_cash
            held_days = int(active_days.get(code, 0))
            if held_days <= 0 and abs(contribution) < 1e-10:
                continue
            avg_weight = float(weight_sums.get(code, 0.0)) / max(total_days, 1)
            contribution_share = contribution / total_return if abs(total_return) > 1e-10 else 0.0
            items.append(
                {
                    "code": code,
                    "name": name_by_code.get(code, code),
                    "contribution": round(contribution, 6),
                    "contribution_share": round(float(contribution_share), 6),
                    "avg_weight": round(avg_weight, 6),
                    "active_days": held_days,
                    "asset_return": asset_returns.get(code),
                }
            )
        items.sort(key=lambda item: item["contribution"], reverse=True)
        residual = total_return - sum(float(item["contribution"]) for item in items)
        return {"items": items, "residual": round(float(residual), 6)}

    def _strategy_params(self, strategy_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return strategy_default_params(strategy_id, params)

    def _int_param(self, params: Dict[str, Any], key: str, default: int, minimum: int = 0) -> int:
        try:
            value = int(params.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, value)

    def _bounded_entry_delay(self, value: Any, trading_days: int) -> int:
        try:
            delay = int(value or 0)
        except (TypeError, ValueError):
            delay = 0
        if trading_days <= 0:
            return 0
        return min(max(0, delay), trading_days - 1)

    def _default_frequency(self, strategy_id: str) -> str:
        return strategy_default_frequency(strategy_id)
