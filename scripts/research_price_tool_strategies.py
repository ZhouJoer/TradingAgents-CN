from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import site
import sys
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median, pstdev
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The local venv interpreter is not always usable, but its pure-Python Mongo
# packages are useful for this research script when the bundled runtime is used.
site.addsitedir(str(ROOT / "venv" / "Lib" / "site-packages"))

from pymongo import MongoClient  # noqa: E402

from app.services.backtest.engine import (  # noqa: E402
    BacktestConfig,
    BacktestEngine,
    DEFAULT_ROTATION_UNIVERSE,
    STRATEGIES,
    StrategyContext,
    StrategySignal,
    _empty_signal,
    _ret,
    _score_dict,
    _signal_from_scores,
    _vol,
)
from app.services.backtest.strategy_catalog import strategy_default_params  # noqa: E402


EXPERIMENTAL_STRATEGIES = (
    "ema_momentum_rotation",
    "price_action_breakout_rotation",
    "fibonacci_retracement_rotation",
)

BASELINE_STRATEGIES = (
    "industry_momentum_enhanced",
    "biweekly_adaptive_stable_rotation",
    "dual_momentum_core",
    "trend_following_equal_weight",
)


def _clean_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return default
        number = float(value)
        if np.isfinite(number):
            return number
    except Exception:
        pass
    return default


def _ema(frame: pd.DataFrame | pd.Series, span: int) -> pd.DataFrame | pd.Series:
    return frame.ewm(span=span, adjust=False, min_periods=span).mean()


def _ema_momentum_rotation(ctx: StrategyContext, date: pd.Timestamp, params: Dict[str, Any]) -> StrategySignal:
    idx = ctx.close.index.get_loc(date)
    top_k = int(params.get("top_k", 2))
    fast_span = int(params.get("fast_ema", 20))
    slow_span = int(params.get("slow_ema", 120))
    momentum_window = int(params.get("momentum_window", 60))
    if idx < max(fast_span, slow_span, momentum_window):
        return _empty_signal("warmup")

    fast = _ema(ctx.close, fast_span).iloc[idx]
    slow = _ema(ctx.close, slow_span).iloc[idx]
    ret = _ret(ctx.close, idx, momentum_window)
    vol = _vol(ctx.returns, int(params.get("vol_window", momentum_window))).iloc[idx]
    trend_strength = fast / slow.replace(0, np.nan) - 1.0
    score = (
        ret
        + float(params.get("trend_weight", 0.5)) * trend_strength
        - float(params.get("vol_penalty", 0.02)) * vol
    )
    eligible = (
        (ctx.close.iloc[idx] > slow)
        & (fast > slow)
        & (ret > float(params.get("min_momentum", 0.0)))
    )
    return _signal_from_scores(
        score,
        eligible,
        top_k,
        empty_reason="ema_no_asset",
        selected_reason="ema_selected",
    )


def _price_action_breakout_rotation(
    ctx: StrategyContext, date: pd.Timestamp, params: Dict[str, Any]
) -> StrategySignal:
    idx = ctx.close.index.get_loc(date)
    top_k = int(params.get("top_k", 2))
    lookback = int(params.get("lookback", 60))
    momentum_window = int(params.get("momentum_window", 20))
    higher_low_window = int(params.get("higher_low_window", 10))
    warmup = max(lookback + 1, momentum_window, higher_low_window * 2)
    if idx < warmup:
        return _empty_signal("warmup")

    close_now = ctx.close.iloc[idx]
    prev_high = ctx.high.iloc[idx - lookback : idx].max()
    prev_low = ctx.low.iloc[idx - lookback : idx].min()
    range_width = (prev_high - prev_low).replace(0, np.nan)
    range_position = (close_now - prev_low) / range_width
    ret = _ret(ctx.close, idx, momentum_window)
    vol = _vol(ctx.returns, int(params.get("vol_window", momentum_window))).iloc[idx]
    breakout_strength = close_now / prev_high.replace(0, np.nan) - 1.0

    recent_low = ctx.low.iloc[idx - higher_low_window + 1 : idx + 1].min()
    previous_low = ctx.low.iloc[idx - higher_low_window * 2 + 1 : idx - higher_low_window + 1].min()
    higher_low = recent_low > previous_low

    eligible = (
        (close_now >= prev_high * float(params.get("breakout_buffer", 0.99)))
        & (ret > float(params.get("min_momentum", 0.0)))
    )
    if bool(params.get("require_higher_low", True)):
        eligible = eligible & higher_low

    score = (
        ret
        + float(params.get("breakout_weight", 1.5)) * breakout_strength
        + float(params.get("range_weight", 0.05)) * range_position
        - float(params.get("vol_penalty", 0.02)) * vol
    )
    return _signal_from_scores(
        score,
        eligible,
        top_k,
        empty_reason="price_action_no_breakout",
        selected_reason="price_action_breakout",
    )


def _fibonacci_retracement_rotation(
    ctx: StrategyContext, date: pd.Timestamp, params: Dict[str, Any]
) -> StrategySignal:
    idx = ctx.close.index.get_loc(date)
    top_k = int(params.get("top_k", 2))
    lookback = int(params.get("lookback", 120))
    bounce_days = int(params.get("bounce_days", 3))
    trend_span = int(params.get("trend_ema", 60))
    if idx < max(lookback, bounce_days, trend_span):
        return _empty_signal("warmup")

    fib_low = float(params.get("fib_low", 0.382))
    fib_high = float(params.get("fib_high", 0.618))
    zone_tolerance = float(params.get("zone_tolerance", 0.02))
    min_leg_return = float(params.get("min_leg_return", 0.10))
    bounce_threshold = float(params.get("bounce_threshold", 0.0))
    target = (fib_low + fib_high) / 2.0
    trend_ema = _ema(ctx.close, trend_span).iloc[idx]
    vol = _vol(ctx.returns, int(params.get("vol_window", 60))).iloc[idx]

    scores = pd.Series(np.nan, index=ctx.close.columns, dtype=float)
    eligible = pd.Series(False, index=ctx.close.columns)
    close_now = ctx.close.iloc[idx]
    close_then = ctx.close.iloc[idx - bounce_days]

    for code in ctx.close.columns:
        high_slice = ctx.high[code].iloc[idx - lookback + 1 : idx + 1].dropna()
        low_slice = ctx.low[code].iloc[idx - lookback + 1 : idx + 1].dropna()
        if high_slice.empty or low_slice.empty:
            continue

        swing_high_pos = int(np.argmax(high_slice.to_numpy()))
        lows_before_high = low_slice.iloc[: swing_high_pos + 1]
        if lows_before_high.empty:
            continue
        swing_low_pos = int(np.argmin(lows_before_high.to_numpy()))
        if swing_high_pos <= swing_low_pos:
            continue

        swing_high = _clean_float(high_slice.iloc[swing_high_pos])
        swing_low = _clean_float(lows_before_high.iloc[swing_low_pos])
        current = _clean_float(close_now.get(code))
        previous = _clean_float(close_then.get(code))
        ema_value = _clean_float(trend_ema.get(code))
        if (
            swing_high is None
            or swing_low is None
            or current is None
            or previous is None
            or ema_value is None
            or swing_low <= 0
            or previous <= 0
            or swing_high <= swing_low
        ):
            continue

        move = swing_high - swing_low
        leg_return = move / swing_low
        retrace = (swing_high - current) / move
        bounce = current / previous - 1.0
        in_zone = fib_low - zone_tolerance <= retrace <= fib_high + zone_tolerance
        trend_ok = current > ema_value
        if in_zone and trend_ok and leg_return >= min_leg_return and bounce > bounce_threshold:
            eligible.at[code] = True
        scores.at[code] = (
            leg_return
            + float(params.get("bounce_weight", 2.0)) * bounce
            - float(params.get("fib_distance_penalty", 0.25)) * abs(retrace - target)
            - float(params.get("vol_penalty", 0.02)) * (_clean_float(vol.get(code), 0.0) or 0.0)
        )

    return _signal_from_scores(
        scores,
        eligible,
        top_k,
        empty_reason="fibonacci_no_retracement",
        selected_reason="fibonacci_retracement",
    )


def register_experimental_strategies() -> None:
    STRATEGIES["ema_momentum_rotation"] = _ema_momentum_rotation
    STRATEGIES["price_action_breakout_rotation"] = _price_action_breakout_rotation
    STRATEGIES["fibonacci_retracement_rotation"] = _fibonacci_retracement_rotation


def read_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def mongo_config() -> Tuple[str, str]:
    env = read_env_file(ROOT / ".env")
    uri = (
        env.get("MONGO_URI")
        or env.get("MONGODB_URL")
        or "mongodb://localhost:27017/tradingagentscn"
    )
    db_name = env.get("MONGO_DB") or env.get("MONGODB_DATABASE") or "tradingagentscn"
    return uri, db_name


def latest_cached_date(db: Any, codes: Iterable[str], adjust: str) -> str:
    row = db["etf_daily_quotes"].find_one(
        {"code": {"$in": list(codes)}, "adjust": adjust},
        sort=[("trade_date", -1)],
        projection={"_id": 0, "trade_date": 1},
    )
    if not row:
        raise RuntimeError(f"No cached ETF history found for adjust={adjust}")
    return str(row["trade_date"])


def warmup_start(start_date: str, days: int = 760) -> str:
    parsed = datetime.strptime(start_date, "%Y-%m-%d").date()
    return (parsed - timedelta(days=days)).strftime("%Y-%m-%d")


def load_records(
    db: Any,
    codes: List[str],
    start_date: str,
    end_date: str,
    adjust: str,
) -> Tuple[Dict[str, List[Dict[str, Any]]], List[str], Dict[str, Dict[str, Any]]]:
    coll = db["etf_daily_quotes"]
    records_by_code: Dict[str, List[Dict[str, Any]]] = {}
    warnings: List[str] = []
    coverage: Dict[str, Dict[str, Any]] = {}
    for code in codes:
        cursor = coll.find(
            {
                "code": code,
                "adjust": adjust,
                "trade_date": {"$gte": start_date, "$lte": end_date},
            },
            {
                "_id": 0,
                "trade_date": 1,
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
                "source": 1,
            },
        ).sort("trade_date", 1)
        rows = list(cursor)
        if not rows:
            warnings.append(f"{code}: no cached history")
            continue
        records_by_code[code] = rows
        coverage[code] = {
            "count": len(rows),
            "start": rows[0].get("trade_date"),
            "end": rows[-1].get("trade_date"),
        }
        if rows[-1].get("trade_date") < end_date:
            warnings.append(f"{code}: cache ends at {rows[-1].get('trade_date')}")
    return records_by_code, warnings, coverage


def split_plan(records_by_code: Dict[str, List[Dict[str, Any]]], start_date: str, end_date: str) -> Dict[str, Any]:
    dates = sorted(
        {
            row["trade_date"]
            for rows in records_by_code.values()
            for row in rows
            if start_date <= row.get("trade_date", "") <= end_date
        }
    )
    if len(dates) < 180:
        raise RuntimeError("Not enough trade dates to create holdout splits")
    train_end = int(len(dates) * 0.6)
    validation_end = int(len(dates) * 0.8)
    holdout = {
        "train": {"start_date": dates[0], "end_date": dates[train_end - 1]},
        "validation": {"start_date": dates[train_end], "end_date": dates[validation_end - 1]},
        "test": {"start_date": dates[validation_end], "end_date": dates[-1]},
    }

    walk_forward = []
    train_days, validation_days, test_days, step_days = 504, 126, 126, 126
    total = train_days + validation_days + test_days
    start = 0
    while start + total <= len(dates) and len(walk_forward) < 4:
        train_start = start
        train_stop = train_start + train_days
        validation_stop = train_stop + validation_days
        test_stop = validation_stop + test_days
        walk_forward.append(
            {
                "label": f"WF{len(walk_forward) + 1}",
                "train": {"start_date": dates[train_start], "end_date": dates[train_stop - 1]},
                "validation": {"start_date": dates[train_stop], "end_date": dates[validation_stop - 1]},
                "test": {"start_date": dates[validation_stop], "end_date": dates[test_stop - 1]},
            }
        )
        start += step_days

    return {"holdout": holdout, "walk_forward": walk_forward, "date_count": len(dates)}


def _trial_fingerprint(trial: Dict[str, Any]) -> str:
    return json.dumps(trial, sort_keys=True, separators=(",", ":"))


def _sample_product(
    strategy_id: str,
    space: Dict[str, List[Any]],
    quota: int,
    random_gen: random.Random,
    validator: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    keys = list(space)
    all_combos = []
    for values in itertools.product(*(space[key] for key in keys)):
        combo = dict(zip(keys, values))
        if validator and not validator(combo):
            continue
        all_combos.append(combo)
    random_gen.shuffle(all_combos)
    trials = []
    for combo in all_combos[:quota]:
        params = dict(combo)
        params.setdefault("cash_entry_mode", "daily_when_cash")
        params.setdefault("cash_entry_confirmations", 2)
        params.setdefault("min_days_to_rebalance_for_cash_entry", 2)
        trials.append({"strategy_id": strategy_id, "params": params})
    return trials


def generate_trials(max_trials: int, seed: int) -> List[Dict[str, Any]]:
    random_gen = random.Random(seed)
    quota = max(1, max_trials // len(EXPERIMENTAL_STRATEGIES))
    spaces = {
        "ema_momentum_rotation": {
            "rebalance_frequency": ["weekly", "biweekly", "monthly"],
            "top_k": [1, 2, 3],
            "fast_ema": [10, 20, 30, 40],
            "slow_ema": [50, 80, 120, 200],
            "momentum_window": [20, 40, 60, 120],
            "vol_window": [20, 60, 120],
            "trend_weight": [0.25, 0.5, 0.75],
            "vol_penalty": [0.0, 0.02, 0.04],
        },
        "price_action_breakout_rotation": {
            "rebalance_frequency": ["weekly", "biweekly", "monthly"],
            "top_k": [1, 2, 3],
            "lookback": [20, 40, 60, 120],
            "momentum_window": [10, 20, 40],
            "higher_low_window": [5, 10, 20],
            "breakout_buffer": [0.97, 0.99, 1.0],
            "require_higher_low": [True, False],
            "vol_penalty": [0.0, 0.02, 0.04],
        },
        "fibonacci_retracement_rotation": {
            "rebalance_frequency": ["weekly", "biweekly", "monthly"],
            "top_k": [1, 2, 3],
            "lookback": [60, 120, 180, 250],
            "fib_low": [0.236, 0.382],
            "fib_high": [0.5, 0.618, 0.786],
            "zone_tolerance": [0.0, 0.02, 0.05],
            "bounce_days": [1, 3, 5],
            "min_leg_return": [0.08, 0.15, 0.25],
            "trend_ema": [20, 60, 120],
        },
    }

    fixed = [
        {
            "strategy_id": "ema_momentum_rotation",
            "params": {
                "rebalance_frequency": "monthly",
                "top_k": 2,
                "fast_ema": 20,
                "slow_ema": 120,
                "momentum_window": 60,
                "vol_window": 60,
                "trend_weight": 0.5,
                "vol_penalty": 0.02,
                "cash_entry_mode": "daily_when_cash",
                "cash_entry_confirmations": 2,
                "min_days_to_rebalance_for_cash_entry": 2,
            },
        },
        {
            "strategy_id": "price_action_breakout_rotation",
            "params": {
                "rebalance_frequency": "weekly",
                "top_k": 2,
                "lookback": 60,
                "momentum_window": 20,
                "higher_low_window": 10,
                "breakout_buffer": 0.99,
                "require_higher_low": True,
                "vol_penalty": 0.02,
                "cash_entry_mode": "daily_when_cash",
                "cash_entry_confirmations": 2,
                "min_days_to_rebalance_for_cash_entry": 2,
            },
        },
        {
            "strategy_id": "fibonacci_retracement_rotation",
            "params": {
                "rebalance_frequency": "weekly",
                "top_k": 2,
                "lookback": 120,
                "fib_low": 0.382,
                "fib_high": 0.618,
                "zone_tolerance": 0.02,
                "bounce_days": 3,
                "min_leg_return": 0.10,
                "trend_ema": 60,
                "cash_entry_mode": "daily_when_cash",
                "cash_entry_confirmations": 2,
                "min_days_to_rebalance_for_cash_entry": 2,
            },
        },
    ]

    trials = list(fixed)
    trials.extend(
        _sample_product(
            "ema_momentum_rotation",
            spaces["ema_momentum_rotation"],
            quota,
            random_gen,
            lambda combo: int(combo["fast_ema"]) < int(combo["slow_ema"]),
        )
    )
    trials.extend(
        _sample_product(
            "price_action_breakout_rotation",
            spaces["price_action_breakout_rotation"],
            quota,
            random_gen,
        )
    )
    trials.extend(
        _sample_product(
            "fibonacci_retracement_rotation",
            spaces["fibonacci_retracement_rotation"],
            quota,
            random_gen,
            lambda combo: float(combo["fib_low"]) < float(combo["fib_high"]),
        )
    )

    unique: List[Dict[str, Any]] = []
    seen = set()
    for trial in trials:
        fingerprint = _trial_fingerprint(trial)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(trial)
    return unique[:max_trials]


def enrich_metrics(metrics: Dict[str, Any], diagnostics: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(metrics)
    benchmark_return = diagnostics.get("benchmark_return")
    total_return = metrics.get("total_return")
    if benchmark_return is not None and total_return is not None:
        result["benchmark_return"] = round(float(benchmark_return), 6)
        result["excess_return"] = round(float(total_return) - float(benchmark_return), 6)
    return result


def run_once(
    engine: BacktestEngine,
    records_by_code: Dict[str, List[Dict[str, Any]]],
    trial: Dict[str, Any],
    split: Dict[str, str],
    args: argparse.Namespace,
    cost_multiplier: float = 1.0,
) -> Dict[str, Any]:
    result = engine.run(
        records_by_code,
        BacktestConfig(
            strategy_id=trial["strategy_id"],
            start_date=split["start_date"],
            end_date=split["end_date"],
            universe=args.codes,
            initial_cash=args.initial_cash,
            commission_bps=args.commission_bps * cost_multiplier,
            slippage_bps=args.slippage_bps * cost_multiplier,
            price_adjust=args.adjust,
            params=trial.get("params") or {},
        ),
    )
    return {
        "metrics": enrich_metrics(result["metrics"], result.get("diagnostics") or {}),
        "diagnostics": result.get("diagnostics") or {},
    }


def walk_forward_summary(slices: List[Dict[str, Any]]) -> Dict[str, Any]:
    metrics = [item.get("metrics") or {} for item in slices]
    if not metrics:
        return {"sample_count": 0}

    def values(key: str) -> List[float]:
        return [float(item[key]) for item in metrics if item.get(key) is not None]

    def rounded(value: float) -> float:
        return round(float(value), 6)

    summary: Dict[str, Any] = {"sample_count": len(metrics)}
    returns = values("total_return")
    excess = values("excess_return")
    if returns:
        summary["positive_ratio"] = rounded(sum(1 for value in returns if value > 0) / len(returns))
    if excess:
        summary["beat_benchmark_ratio"] = rounded(sum(1 for value in excess if value > 0) / len(excess))
    for key in ("total_return", "excess_return", "calmar", "sharpe"):
        source = values(key)
        if source:
            summary[f"{key}_median"] = rounded(median(source))
            summary[f"{key}_mean"] = rounded(sum(source) / len(source))
            summary[f"{key}_std"] = rounded(pstdev(source)) if len(source) > 1 else 0.0
            summary[f"{key}_min"] = rounded(min(source))
    drawdowns = values("max_drawdown")
    if drawdowns:
        summary["max_drawdown_worst"] = rounded(min(drawdowns))
    trades = values("trade_count")
    if trades:
        summary["trade_count_total"] = int(sum(trades))
    return summary


def score_trial(
    metrics_by_split: Dict[str, Dict[str, Any]],
    stress_metrics: Dict[str, Any],
    wf_summary: Dict[str, Any],
) -> float:
    test = metrics_by_split["test"]
    validation = metrics_by_split["validation"]
    penalty = abs(test.get("max_drawdown", 0.0)) * 0.5
    turnover_penalty = test.get("avg_turnover", 0.0) * 0.1
    stability = abs(test.get("calmar", 0.0) - validation.get("calmar", 0.0)) * 0.1
    stress_bonus = max(0.0, stress_metrics.get("total_return", 0.0)) * 0.2
    excess_bonus = max(0.0, test.get("excess_return", 0.0)) * 0.5
    validation_excess_bonus = max(0.0, validation.get("excess_return", 0.0)) * 0.2
    wf_bonus = (
        0.4 * wf_summary.get("calmar_median", 0.0)
        + 0.25 * max(0.0, wf_summary.get("excess_return_median", 0.0))
        + 0.15 * wf_summary.get("positive_ratio", 0.0)
        + 0.15 * wf_summary.get("beat_benchmark_ratio", 0.0)
    )
    wf_penalty = (
        0.08 * wf_summary.get("calmar_std", 0.0)
        + 0.5 * max(0.0, 0.5 - wf_summary.get("positive_ratio", 0.0))
        + 0.5 * max(0.0, 0.4 - wf_summary.get("beat_benchmark_ratio", 0.0))
    )
    return (
        test.get("calmar", 0.0)
        + 0.3 * validation.get("calmar", 0.0)
        + excess_bonus
        + validation_excess_bonus
        + stress_bonus
        + wf_bonus
        - penalty
        - turnover_penalty
        - stability
        - wf_penalty
    )


def acceptance_reasons(
    metrics_by_split: Dict[str, Dict[str, Any]],
    stress_metrics: Dict[str, Any],
    wf_summary: Dict[str, Any],
) -> List[str]:
    reasons: List[str] = []
    test = metrics_by_split["test"]
    if test.get("total_return", 0.0) <= 0:
        reasons.append("test_return_not_positive")
    if test.get("excess_return", test.get("total_return", 0.0)) <= 0:
        reasons.append("test_excess_not_positive")
    if abs(test.get("max_drawdown", 0.0)) > 0.35:
        reasons.append("drawdown_too_high")
    if test.get("trade_count", 0) < 4:
        reasons.append("too_few_trades")
    if sum(1 for item in metrics_by_split.values() if item.get("total_return", 0.0) > 0) < 2:
        reasons.append("performance_too_concentrated")
    if stress_metrics.get("total_return", 0.0) <= 0:
        reasons.append("failed_2x_cost_stress")
    if wf_summary.get("sample_count", 0) >= 2:
        if wf_summary.get("positive_ratio", 0.0) < 0.5:
            reasons.append("walk_forward_return_unstable")
        if wf_summary.get("beat_benchmark_ratio", 0.0) < 0.4:
            reasons.append("walk_forward_excess_unstable")
    return reasons


def evaluate_trial(
    engine: BacktestEngine,
    records_by_code: Dict[str, List[Dict[str, Any]]],
    trial: Dict[str, Any],
    plan: Dict[str, Any],
    args: argparse.Namespace,
    index: int,
) -> Dict[str, Any]:
    metrics_by_split: Dict[str, Dict[str, Any]] = {}
    for split_name, split in plan["holdout"].items():
        metrics_by_split[split_name] = run_once(engine, records_by_code, trial, split, args)["metrics"]

    wf_slices = []
    if not args.no_walk_forward:
        for fold in plan.get("walk_forward", []):
            item = run_once(engine, records_by_code, trial, fold["test"], args)
            wf_slices.append({"label": fold["label"], "test": fold["test"], "metrics": item["metrics"]})
    wf_summary = walk_forward_summary(wf_slices)

    stress_metrics = run_once(
        engine,
        records_by_code,
        trial,
        plan["holdout"]["test"],
        args,
        cost_multiplier=2.0,
    )["metrics"]
    reasons = acceptance_reasons(metrics_by_split, stress_metrics, wf_summary)
    score = score_trial(metrics_by_split, stress_metrics, wf_summary)
    return {
        "trial_index": index,
        "strategy_id": trial["strategy_id"],
        "family": trial["strategy_id"].split("_", 1)[0],
        "params": trial.get("params") or {},
        "score": round(float(score), 6),
        "accepted": not reasons,
        "reasons": reasons,
        "train_metrics": metrics_by_split["train"],
        "validation_metrics": metrics_by_split["validation"],
        "test_metrics": metrics_by_split["test"],
        "stress_2x_metrics": stress_metrics,
        "walk_forward_summary": wf_summary,
        "walk_forward_slices": wf_slices,
    }


def baseline_trials() -> List[Dict[str, Any]]:
    return [
        {"strategy_id": strategy_id, "params": strategy_default_params(strategy_id)}
        for strategy_id in BASELINE_STRATEGIES
    ]


def family_summary(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for family in sorted({item["strategy_id"] for item in results}):
        items = [item for item in results if item["strategy_id"] == family]
        test_returns = [float(item["test_metrics"].get("total_return", 0.0)) for item in items]
        test_excess = [float(item["test_metrics"].get("excess_return", 0.0)) for item in items]
        accepted = [item for item in items if item["accepted"]]
        best = max(items, key=lambda item: item["score"])
        rows.append(
            {
                "strategy_id": family,
                "trial_count": len(items),
                "accepted_count": len(accepted),
                "median_test_return": round(float(median(test_returns)), 6) if test_returns else 0.0,
                "median_test_excess": round(float(median(test_excess)), 6) if test_excess else 0.0,
                "best_score": best["score"],
                "best_test_metrics": best["test_metrics"],
                "best_params": best["params"],
            }
        )
    return rows


def pct(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value) * 100:.2f}%"
    except Exception:
        return str(value)


def num(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.3f}"
    except Exception:
        return str(value)


def compact_params(params: Dict[str, Any], max_len: int = 90) -> str:
    text = json.dumps(params, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def render_table(headers: List[str], rows: List[List[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_markdown(payload: Dict[str, Any]) -> str:
    meta = payload["meta"]
    lines = [
        "# EMA / Price Action / Fibonacci ETF Research",
        "",
        f"- Generated: {meta['generated_at']}",
        f"- Period: {meta['start_date']} to {meta['end_date']} ({meta['date_count']} trading dates)",
        f"- Adjust: {meta['adjust']}",
        f"- Universe size: {len(meta['universe'])}",
        f"- Experimental trials: {meta['trial_count']}",
        f"- Costs: commission {meta['commission_bps']} bps, slippage {meta['slippage_bps']} bps",
        "",
        "## Holdout Splits",
        "",
        render_table(
            ["split", "start", "end"],
            [[name, split["start_date"], split["end_date"]] for name, split in payload["split_plan"]["holdout"].items()],
        ),
        "",
        "## Baselines",
        "",
        render_table(
            [
                "strategy",
                "test ret",
                "test excess",
                "test dd",
                "test calmar",
                "full ret",
                "full dd",
                "full calmar",
                "trades",
            ],
            [
                [
                    item["strategy_id"],
                    pct(item["test_metrics"].get("total_return")),
                    pct(item["test_metrics"].get("excess_return")),
                    pct(item["test_metrics"].get("max_drawdown")),
                    num(item["test_metrics"].get("calmar")),
                    pct(item["full_metrics"].get("total_return")),
                    pct(item["full_metrics"].get("max_drawdown")),
                    num(item["full_metrics"].get("calmar")),
                    str(item["full_metrics"].get("trade_count")),
                ]
                for item in payload["baselines"]
            ],
        ),
        "",
        "## Experimental Family Summary",
        "",
        render_table(
            [
                "strategy",
                "trials",
                "accepted",
                "median test ret",
                "median test excess",
                "best score",
                "best test ret",
                "best test excess",
                "best test dd",
                "best test calmar",
            ],
            [
                [
                    row["strategy_id"],
                    str(row["trial_count"]),
                    str(row["accepted_count"]),
                    pct(row["median_test_return"]),
                    pct(row["median_test_excess"]),
                    num(row["best_score"]),
                    pct(row["best_test_metrics"].get("total_return")),
                    pct(row["best_test_metrics"].get("excess_return")),
                    pct(row["best_test_metrics"].get("max_drawdown")),
                    num(row["best_test_metrics"].get("calmar")),
                ]
                for row in payload["family_summary"]
            ],
        ),
        "",
        "## Top Experimental Trials",
        "",
        render_table(
            [
                "rank",
                "strategy",
                "score",
                "accepted",
                "test ret",
                "test excess",
                "test dd",
                "test calmar",
                "wf beat",
                "full ret",
                "full dd",
                "params",
            ],
            [
                [
                    str(index + 1),
                    item["strategy_id"],
                    num(item["score"]),
                    "yes" if item["accepted"] else "no",
                    pct(item["test_metrics"].get("total_return")),
                    pct(item["test_metrics"].get("excess_return")),
                    pct(item["test_metrics"].get("max_drawdown")),
                    num(item["test_metrics"].get("calmar")),
                    pct(item["walk_forward_summary"].get("beat_benchmark_ratio")),
                    pct(item.get("full_metrics", {}).get("total_return")),
                    pct(item.get("full_metrics", {}).get("max_drawdown")),
                    compact_params(item["params"]),
                ]
                for index, item in enumerate(payload["top_trials"])
            ],
        ),
    ]
    if payload.get("warnings"):
        lines.extend(["", "## Data Warnings", ""])
        lines.extend(f"- {warning}" for warning in payload["warnings"][:50])
    return "\n".join(lines) + "\n"


def attach_full_period_metrics(
    engine: BacktestEngine,
    records_by_code: Dict[str, List[Dict[str, Any]]],
    items: List[Dict[str, Any]],
    args: argparse.Namespace,
) -> None:
    full_split = {"start_date": args.start_date, "end_date": args.end_date}
    for item in items:
        metrics = run_once(
            engine,
            records_by_code,
            {"strategy_id": item["strategy_id"], "params": item.get("params") or {}},
            full_split,
            args,
        )["metrics"]
        item["full_metrics"] = metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only ETF backtests for EMA, price action, and Fibonacci strategies."
    )
    parser.add_argument("--start-date", default="2019-01-01")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--adjust", default="qfq", choices=["qfq", "none", "hfq"])
    parser.add_argument("--max-trials", type=int, default=180)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument("--commission-bps", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--codes", nargs="*", default=[item["code"] for item in DEFAULT_ROTATION_UNIVERSE])
    parser.add_argument("--top-output", type=int, default=15)
    parser.add_argument("--no-walk-forward", action="store_true")
    parser.add_argument("--output-dir", default=str(ROOT / "reports" / "backtest_research"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    register_experimental_strategies()

    uri, db_name = mongo_config()
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    db = client[db_name]
    args.codes = [str(code).zfill(6) for code in args.codes]
    if not args.end_date:
        args.end_date = latest_cached_date(db, args.codes, args.adjust)

    records_by_code, warnings, coverage = load_records(
        db,
        args.codes,
        warmup_start(args.start_date),
        args.end_date,
        args.adjust,
    )
    plan = split_plan(records_by_code, args.start_date, args.end_date)

    engine = BacktestEngine()
    trials = generate_trials(args.max_trials, args.seed)
    results = []
    for index, trial in enumerate(trials, 1):
        try:
            results.append(evaluate_trial(engine, records_by_code, trial, plan, args, index))
        except Exception as exc:
            results.append(
                {
                    "trial_index": index,
                    "strategy_id": trial["strategy_id"],
                    "params": trial.get("params") or {},
                    "score": float("-inf"),
                    "accepted": False,
                    "reasons": [f"error:{exc}"],
                }
            )
        if index % 10 == 0 or index == len(trials):
            print(f"evaluated {index}/{len(trials)} trials")

    ranked = sorted(results, key=lambda item: item.get("score", float("-inf")), reverse=True)
    top_trials = [dict(item) for item in ranked[: args.top_output] if math.isfinite(float(item.get("score", 0.0)))]
    attach_full_period_metrics(engine, records_by_code, top_trials, args)

    baselines = []
    for trial in baseline_trials():
        test_metrics = run_once(engine, records_by_code, trial, plan["holdout"]["test"], args)["metrics"]
        full_metrics = run_once(
            engine,
            records_by_code,
            trial,
            {"start_date": args.start_date, "end_date": args.end_date},
            args,
        )["metrics"]
        baselines.append(
            {
                "strategy_id": trial["strategy_id"],
                "params": trial["params"],
                "test_metrics": test_metrics,
                "full_metrics": full_metrics,
            }
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "database": db_name,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "adjust": args.adjust,
            "universe": args.codes,
            "date_count": plan["date_count"],
            "trial_count": len(trials),
            "commission_bps": args.commission_bps,
            "slippage_bps": args.slippage_bps,
        },
        "coverage": coverage,
        "warnings": warnings,
        "split_plan": {"holdout": plan["holdout"], "walk_forward": plan["walk_forward"]},
        "baselines": baselines,
        "family_summary": family_summary([item for item in ranked if "test_metrics" in item]),
        "top_trials": top_trials,
        "ranked_trials": ranked,
    }
    json_path = output_dir / f"price_tool_strategy_research_{stamp}.json"
    md_path = output_dir / f"price_tool_strategy_research_{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    print(f"json={json_path}")
    print(f"markdown={md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
