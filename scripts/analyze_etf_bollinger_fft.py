from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]


def _append_project_site_packages() -> None:
    """Let a bundled/system Python reuse pure Python packages from local venvs."""
    for relative in (".venv/Lib/site-packages", "venv/Lib/site-packages"):
        candidate = ROOT / relative
        if candidate.exists() and str(candidate) not in sys.path:
            sys.path.append(str(candidate))


_append_project_site_packages()

import numpy as np
import pandas as pd


DEFAULT_ETF_UNIVERSE: List[Dict[str, str]] = [
    {"code": "510300", "name": "CSI 300 ETF", "group": "broad"},
    {"code": "510500", "name": "CSI 500 ETF", "group": "broad"},
    {"code": "510050", "name": "SSE 50 ETF", "group": "broad"},
    {"code": "159915", "name": "ChiNext ETF", "group": "broad"},
    {"code": "159952", "name": "ChiNext ETF GF", "group": "broad"},
    {"code": "159956", "name": "ChiNext ETF CCB", "group": "broad"},
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
    {"code": "512890", "name": "Dividend Low Vol ETF", "group": "factor"},
    {"code": "515100", "name": "Dividend Low Vol 100 ETF", "group": "factor"},
    {"code": "515300", "name": "CSI 300 Dividend Low Vol ETF", "group": "factor"},
    {"code": "563020", "name": "Dividend Low Vol ETF E Fund", "group": "factor"},
    {"code": "518880", "name": "Gold ETF", "group": "commodity"},
]

SOURCE_PRIORITY = {
    "tushare_fund_daily_factor_qfq": 0,
    "tushare_fund_daily_factor_hfq": 0,
    "tushare_fund_daily": 0,
    "akshare_fund_etf_hist_em": 10,
    "akshare_fund_etf_hist_sina": 20,
}


@dataclass(frozen=True)
class AnalysisConfig:
    boll_window: int
    boll_k: float
    squeeze_lookback: int
    squeeze_quantile: float
    contraction_days: int
    event_mode: str
    event_cooldown: int
    horizons: List[int]
    large_move_threshold: float
    fft_window: int
    fft_min_period: float
    fft_max_period: Optional[float]
    fft_top_k: int
    control_samples_per_event: int
    seed: int
    permutation_rounds: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "ETF event study for Bollinger-band narrowing and FFT cycle features. "
            "Default source is MongoDB ETF cache."
        )
    )
    parser.add_argument("--source", choices=["mongo", "csv", "akshare"], default="mongo")
    parser.add_argument("--csv", help="CSV with code, trade_date/date, open, high, low, close columns.")
    parser.add_argument("--mongo-uri", default=None, help="Mongo URI. Defaults to MONGO_URI from env/.env.")
    parser.add_argument("--mongo-db", default=None, help="Mongo database. Defaults to MONGO_DB from env/.env.")
    parser.add_argument("--mongo-collection", default="etf_daily_quotes")
    parser.add_argument("--fallback-akshare", action="store_true", help="Fetch missing codes from AKShare without caching.")
    parser.add_argument("--codes", nargs="*", default=None, help="ETF codes. Defaults to the built-in ETF universe.")
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument("--end-date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--adjust", choices=["qfq", "hfq", "none"], default="qfq")
    parser.add_argument("--min-rows", type=int, default=180)

    parser.add_argument("--boll-window", type=int, default=20)
    parser.add_argument("--boll-k", type=float, default=2.0)
    parser.add_argument("--squeeze-lookback", type=int, default=252)
    parser.add_argument("--squeeze-quantile", type=float, default=0.2)
    parser.add_argument("--contraction-days", type=int, default=3)
    parser.add_argument(
        "--event-mode",
        choices=["squeeze-start", "squeeze", "narrowing-start"],
        default="squeeze-start",
        help=(
            "squeeze-start: first low-bandwidth contraction day; "
            "squeeze: all low-bandwidth contraction days after cooldown; "
            "narrowing-start: first contraction streak regardless of low quantile."
        ),
    )
    parser.add_argument("--event-cooldown", type=int, default=20)
    parser.add_argument("--horizons", default="5,10,20,40", help="Forward trading-day horizons, comma-separated.")
    parser.add_argument("--large-move-threshold", type=float, default=0.08)

    parser.add_argument("--fft-window", type=int, default=128)
    parser.add_argument("--fft-min-period", type=float, default=5.0)
    parser.add_argument("--fft-max-period", type=float, default=None)
    parser.add_argument("--fft-top-k", type=int, default=3)
    parser.add_argument("--control-samples-per-event", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--permutation-rounds", type=int, default=1000)
    parser.add_argument("--export-csv", default=None, help="Optional path for event/control outcome rows.")
    parser.add_argument("--json", action="store_true", help="Print the full report as JSON.")
    return parser.parse_args()


def normalize_codes(codes: Optional[Iterable[str]]) -> List[str]:
    raw = list(codes) if codes else [item["code"] for item in DEFAULT_ETF_UNIVERSE]
    result: List[str] = []
    seen = set()
    for code in raw:
        normalized = str(code).strip().zfill(6)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def parse_horizons(value: str) -> List[int]:
    horizons = []
    for part in str(value).split(","):
        part = part.strip()
        if not part:
            continue
        horizon = int(part)
        if horizon <= 0:
            raise ValueError("horizons must be positive integers")
        horizons.append(horizon)
    if not horizons:
        raise ValueError("at least one horizon is required")
    return sorted(set(horizons))


def load_dotenv(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def mongo_defaults(args: argparse.Namespace) -> Tuple[str, str]:
    env_file = load_dotenv(ROOT / ".env")
    uri = args.mongo_uri or os.getenv("MONGO_URI") or env_file.get("MONGO_URI")
    db = args.mongo_db or os.getenv("MONGO_DB") or env_file.get("MONGO_DB")
    if not uri:
        uri = "mongodb://admin:tradingagents123@localhost:27017/tradingagentscn?authSource=admin"
    if not db:
        db = "tradingagentscn"
    return uri, db


def load_from_mongo(args: argparse.Namespace, codes: List[str]) -> pd.DataFrame:
    try:
        from pymongo import MongoClient
    except ImportError as exc:
        raise RuntimeError("pymongo is required for --source mongo") from exc

    uri, db_name = mongo_defaults(args)
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
        collection = client[db_name][args.mongo_collection]
        query = {
            "code": {"$in": codes},
            "trade_date": {"$gte": args.start_date, "$lte": args.end_date},
            "adjust": args.adjust,
        }
        projection = {
            "_id": 0,
            "code": 1,
            "trade_date": 1,
            "open": 1,
            "high": 1,
            "low": 1,
            "close": 1,
            "volume": 1,
            "amount": 1,
            "source": 1,
        }
        rows = list(collection.find(query, projection).sort([("code", 1), ("trade_date", 1)]))
    finally:
        client.close()
    return normalize_history(pd.DataFrame(rows))


def load_from_csv(path: str) -> pd.DataFrame:
    if not path:
        raise ValueError("--csv is required when --source csv")
    return normalize_history(pd.read_csv(path))


def load_from_akshare(args: argparse.Namespace, codes: List[str]) -> pd.DataFrame:
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError("akshare is required for --source akshare") from exc

    frames: List[pd.DataFrame] = []
    adjust = "" if args.adjust == "none" else args.adjust
    for code in codes:
        df = ak.fund_etf_hist_em(
            symbol=code,
            period="daily",
            start_date=args.start_date.replace("-", ""),
            end_date=args.end_date.replace("-", ""),
            adjust=adjust,
        )
        if df is None or df.empty:
            continue
        df = df.copy()
        df["code"] = code
        df["source"] = "akshare_fund_etf_hist_em"
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return normalize_history(pd.concat(frames, ignore_index=True))


def normalize_history(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["code", "trade_date", "open", "high", "low", "close", "volume", "source"])
    mapping = {
        "date": "trade_date",
        "日期": "trade_date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
    }
    renamed = df.rename(columns={key: value for key, value in mapping.items() if key in df.columns}).copy()
    if "code" not in renamed.columns:
        raise ValueError("history data must include a code column")
    if "trade_date" not in renamed.columns:
        raise ValueError("history data must include trade_date or date")
    if "close" not in renamed.columns:
        raise ValueError("history data must include close")

    renamed["code"] = renamed["code"].astype(str).str.strip().str.zfill(6)
    renamed["trade_date"] = pd.to_datetime(renamed["trade_date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume", "amount"):
        if column in renamed.columns:
            renamed[column] = pd.to_numeric(renamed[column], errors="coerce")
    for column in ("open", "high", "low"):
        if column not in renamed.columns:
            renamed[column] = renamed["close"]
        else:
            renamed[column] = renamed[column].fillna(renamed["close"])
    if "volume" not in renamed.columns:
        renamed["volume"] = np.nan
    if "source" not in renamed.columns:
        renamed["source"] = "unknown"

    renamed = renamed.dropna(subset=["code", "trade_date", "close"])
    renamed = renamed[renamed["close"] > 0].copy()
    renamed["_source_priority"] = renamed["source"].map(SOURCE_PRIORITY).fillna(100)
    renamed = renamed.sort_values(["code", "trade_date", "_source_priority"])
    renamed = renamed.drop_duplicates(["code", "trade_date"], keep="first")
    columns = ["code", "trade_date", "open", "high", "low", "close", "volume", "source"]
    return renamed[columns].sort_values(["code", "trade_date"]).reset_index(drop=True)


def add_bollinger_features(df: pd.DataFrame, config: AnalysisConfig) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    min_periods = config.boll_window
    quantile_min_periods = max(config.boll_window, config.squeeze_lookback // 2)
    for _, group in df.groupby("code", sort=False):
        item = group.sort_values("trade_date").copy()
        close = item["close"]
        mid = close.rolling(config.boll_window, min_periods=min_periods).mean()
        std = close.rolling(config.boll_window, min_periods=min_periods).std(ddof=0)
        width = (2.0 * config.boll_k * std) / mid.replace(0, np.nan)
        width_threshold = width.rolling(
            config.squeeze_lookback,
            min_periods=quantile_min_periods,
        ).quantile(config.squeeze_quantile)
        item["boll_mid"] = mid
        item["boll_upper"] = mid + config.boll_k * std
        item["boll_lower"] = mid - config.boll_k * std
        item["boll_width"] = width
        item["boll_width_change"] = width.diff()
        item["squeeze_threshold"] = width_threshold
        item["is_low_width"] = width <= width_threshold
        frames.append(item)
    if not frames:
        return df.copy()
    return pd.concat(frames, ignore_index=True)


def _consecutive_true(mask: pd.Series, window: int) -> pd.Series:
    window = max(1, int(window))
    return mask.rolling(window, min_periods=window).sum() >= window


def event_indices(group: pd.DataFrame, config: AnalysisConfig) -> List[int]:
    width = group["boll_width"]
    contracting = width.diff() < 0
    contraction_streak = _consecutive_true(contracting.fillna(False), config.contraction_days)
    low_width = group["is_low_width"].fillna(False)

    if config.event_mode == "squeeze-start":
        previous_low = low_width.shift(1).fillna(False).astype(bool)
        candidates = low_width & contraction_streak & ~previous_low
    elif config.event_mode == "squeeze":
        candidates = low_width & contraction_streak
    else:
        previous_streak = contraction_streak.shift(1).fillna(False).astype(bool)
        candidates = contraction_streak & ~previous_streak

    selected: List[int] = []
    last_idx = -10**9
    max_horizon = max(config.horizons)
    for idx, is_candidate in enumerate(candidates.fillna(False).tolist()):
        if not is_candidate:
            continue
        if idx + max_horizon >= len(group):
            continue
        if idx - last_idx <= config.event_cooldown:
            continue
        selected.append(idx)
        last_idx = idx
    return selected


def fft_features(
    close: pd.Series,
    idx: int,
    window: int,
    top_k: int,
    min_period: float = 5.0,
    max_period: Optional[float] = None,
) -> Dict[str, Any]:
    start = idx - window + 1
    if start < 0:
        return {"periods": [], "top_period": None, "top_power_share": None}
    series = close.iloc[start : idx + 1].astype(float)
    if series.isna().any() or (series <= 0).any():
        return {"periods": [], "top_period": None, "top_power_share": None}
    returns = np.log(series).diff().dropna().to_numpy()
    if len(returns) < max(16, window // 2):
        return {"periods": [], "top_period": None, "top_power_share": None}
    returns = returns - np.mean(returns)
    tapered = returns * np.hanning(len(returns))
    spectrum = np.fft.rfft(tapered)
    power = np.abs(spectrum) ** 2
    if len(power) <= 2 or float(power[1:].sum()) <= 0:
        return {"periods": [], "top_period": None, "top_power_share": None}

    total_power = float(power[1:].sum())
    allowed_indices = []
    for frequency_index in range(1, len(power)):
        period = len(returns) / frequency_index
        if period < min_period:
            continue
        if max_period is not None and period > max_period:
            continue
        allowed_indices.append(frequency_index)
    if not allowed_indices:
        return {"periods": [], "top_period": None, "top_power_share": None}

    ranked_indices = sorted(allowed_indices, key=lambda frequency_index: power[frequency_index], reverse=True)[:top_k]
    periods = []
    for frequency_index in ranked_indices:
        periods.append(
            {
                "period": round(float(len(returns) / frequency_index), 2),
                "power_share": round(float(power[frequency_index] / total_power), 6),
            }
        )
    top = periods[0] if periods else {}
    return {
        "periods": periods,
        "top_period": top.get("period"),
        "top_power_share": top.get("power_share"),
    }


def build_outcome(
    group: pd.DataFrame,
    idx: int,
    horizon: int,
    kind: str,
    config: AnalysisConfig,
) -> Dict[str, Any]:
    row = group.iloc[idx]
    future = group.iloc[idx + 1 : idx + horizon + 1]
    end_row = group.iloc[idx + horizon]
    entry = float(row["close"])
    max_up = float(future["high"].max() / entry - 1.0)
    max_down = float(future["low"].min() / entry - 1.0)
    forward_return = float(end_row["close"] / entry - 1.0)
    max_abs_move = max(abs(max_up), abs(max_down))
    fft = fft_features(
        group["close"],
        idx,
        config.fft_window,
        config.fft_top_k,
        config.fft_min_period,
        config.fft_max_period,
    )
    return {
        "kind": kind,
        "code": str(row["code"]),
        "date": row["trade_date"].strftime("%Y-%m-%d"),
        "horizon": horizon,
        "close": round(entry, 6),
        "boll_width": round(float(row["boll_width"]), 8) if pd.notna(row["boll_width"]) else None,
        "squeeze_threshold": (
            round(float(row["squeeze_threshold"]), 8) if pd.notna(row["squeeze_threshold"]) else None
        ),
        "forward_return": round(forward_return, 8),
        "abs_forward_return": round(abs(forward_return), 8),
        "max_up": round(max_up, 8),
        "max_down": round(max_down, 8),
        "max_abs_move": round(max_abs_move, 8),
        "large_move": bool(max_abs_move >= config.large_move_threshold),
        "up_close": bool(forward_return > 0),
        "fft_top_period": fft["top_period"],
        "fft_top_power_share": fft["top_power_share"],
        "fft_periods": fft["periods"],
    }


def sample_control_indices(
    group: pd.DataFrame,
    events: List[int],
    config: AnalysisConfig,
    rng: random.Random,
) -> List[int]:
    max_horizon = max(config.horizons)
    excluded = set()
    for event_idx in events:
        start = max(0, event_idx - config.event_cooldown)
        end = min(len(group) - 1, event_idx + config.event_cooldown)
        excluded.update(range(start, end + 1))

    valid = []
    for idx in range(len(group) - max_horizon):
        if idx in excluded:
            continue
        row = group.iloc[idx]
        if pd.isna(row.get("boll_width")) or pd.isna(row.get("squeeze_threshold")):
            continue
        valid.append(idx)

    if not events or not valid:
        return []
    sample_size = min(len(valid), len(events) * max(1, config.control_samples_per_event))
    return sorted(rng.sample(valid, sample_size))


def build_event_study(df: pd.DataFrame, config: AnalysisConfig) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    featured = add_bollinger_features(df, config)
    rng = random.Random(config.seed)
    rows: List[Dict[str, Any]] = []
    event_counts: Dict[str, int] = {}
    control_counts: Dict[str, int] = {}

    for code, group in featured.groupby("code", sort=False):
        group = group.sort_values("trade_date").reset_index(drop=True)
        if len(group) < max(config.squeeze_lookback, config.fft_window, max(config.horizons)) + 5:
            continue
        events = event_indices(group, config)
        controls = sample_control_indices(group, events, config, rng)
        event_counts[str(code)] = len(events)
        control_counts[str(code)] = len(controls)
        for idx in events:
            for horizon in config.horizons:
                rows.append(build_outcome(group, idx, horizon, "event", config))
        for idx in controls:
            for horizon in config.horizons:
                rows.append(build_outcome(group, idx, horizon, "control", config))

    metadata = {
        "event_counts": event_counts,
        "control_counts": control_counts,
        "feature_rows": int(len(featured)),
    }
    if not rows:
        return pd.DataFrame(), metadata
    return pd.DataFrame(rows), metadata


def permutation_p_value(
    event_values: Sequence[bool],
    control_values: Sequence[bool],
    rounds: int,
    seed: int,
) -> Optional[float]:
    if rounds <= 0 or not event_values or not control_values:
        return None
    event = np.asarray(event_values, dtype=float)
    control = np.asarray(control_values, dtype=float)
    observed = float(event.mean() - control.mean())
    if observed <= 0:
        return 1.0
    combined = np.concatenate([event, control])
    event_n = len(event)
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(rounds):
        shuffled = rng.permutation(combined)
        diff = float(shuffled[:event_n].mean() - shuffled[event_n:].mean())
        if diff >= observed:
            hits += 1
    return round(float((hits + 1) / (rounds + 1)), 6)


def _safe_mean(values: pd.Series) -> Optional[float]:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return None
    return round(float(values.mean()), 6)


def _safe_median(values: pd.Series) -> Optional[float]:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return None
    return round(float(values.median()), 6)


def summarize_outcomes(outcomes: pd.DataFrame, config: AnalysisConfig) -> List[Dict[str, Any]]:
    if outcomes.empty:
        return []
    summary: List[Dict[str, Any]] = []
    for horizon in sorted(outcomes["horizon"].unique()):
        item: Dict[str, Any] = {"horizon": int(horizon)}
        by_horizon = outcomes[outcomes["horizon"] == horizon]
        for kind in ("event", "control"):
            part = by_horizon[by_horizon["kind"] == kind]
            prefix = f"{kind}_"
            item[prefix + "n"] = int(len(part))
            item[prefix + "large_move_rate"] = round(float(part["large_move"].mean()), 6) if len(part) else None
            item[prefix + "mean_abs_forward_return"] = _safe_mean(part["abs_forward_return"])
            item[prefix + "median_abs_forward_return"] = _safe_median(part["abs_forward_return"])
            item[prefix + "mean_max_abs_move"] = _safe_mean(part["max_abs_move"])
            item[prefix + "median_max_abs_move"] = _safe_median(part["max_abs_move"])
            item[prefix + "up_close_rate"] = round(float(part["up_close"].mean()), 6) if len(part) else None

        event_rate = item.get("event_large_move_rate")
        control_rate = item.get("control_large_move_rate")
        if event_rate is not None and control_rate is not None:
            item["large_move_lift"] = round(float(event_rate - control_rate), 6)
            item["large_move_ratio"] = round(float(event_rate / control_rate), 6) if control_rate > 0 else None
            event_large = by_horizon[by_horizon["kind"] == "event"]["large_move"].tolist()
            control_large = by_horizon[by_horizon["kind"] == "control"]["large_move"].tolist()
            item["large_move_perm_p"] = permutation_p_value(
                event_large,
                control_large,
                config.permutation_rounds,
                config.seed + int(horizon),
            )
        summary.append(item)
    return summary


def period_bucket(value: Any) -> Optional[int]:
    try:
        if value is None or pd.isna(value):
            return None
        value = float(value)
        if value <= 0 or not math.isfinite(value):
            return None
        return max(5, int(round(value / 5.0) * 5))
    except Exception:
        return None


def summarize_fft(outcomes: pd.DataFrame) -> Dict[str, Any]:
    if outcomes.empty:
        return {}
    primary = outcomes[outcomes["kind"] == "event"].drop_duplicates(["code", "date"]).copy()
    if primary.empty:
        return {}
    primary["period_bucket"] = primary["fft_top_period"].map(period_bucket)
    buckets = Counter(primary["period_bucket"].dropna().astype(int).tolist())
    large = primary[primary["large_move"]]
    quiet = primary[~primary["large_move"]]
    return {
        "event_fft_n": int(primary["fft_top_period"].notna().sum()),
        "median_top_period": _safe_median(primary["fft_top_period"]),
        "mean_top_power_share": _safe_mean(primary["fft_top_power_share"]),
        "top_period_buckets": [
            {"period": int(period), "count": int(count)} for period, count in buckets.most_common(8)
        ],
        "large_move_median_top_period": _safe_median(large["fft_top_period"]) if not large.empty else None,
        "quiet_median_top_period": _safe_median(quiet["fft_top_period"]) if not quiet.empty else None,
    }


def summarize_by_code(outcomes: pd.DataFrame, primary_horizon: int) -> List[Dict[str, Any]]:
    if outcomes.empty:
        return []
    event_rows = outcomes[(outcomes["kind"] == "event") & (outcomes["horizon"] == primary_horizon)]
    items: List[Dict[str, Any]] = []
    names = {item["code"]: item["name"] for item in DEFAULT_ETF_UNIVERSE}
    groups = {item["code"]: item["group"] for item in DEFAULT_ETF_UNIVERSE}
    for code, part in event_rows.groupby("code"):
        if part.empty:
            continue
        items.append(
            {
                "code": str(code),
                "name": names.get(str(code), str(code)),
                "group": groups.get(str(code), "unknown"),
                "events": int(len(part)),
                "large_move_rate": round(float(part["large_move"].mean()), 6),
                "mean_max_abs_move": _safe_mean(part["max_abs_move"]),
                "median_fft_period": _safe_median(part["fft_top_period"]),
            }
        )
    items.sort(key=lambda row: (row["large_move_rate"], row["events"], row["mean_max_abs_move"] or 0), reverse=True)
    return items


def global_fft_by_code(df: pd.DataFrame, config: AnalysisConfig) -> List[Dict[str, Any]]:
    rows = []
    names = {item["code"]: item["name"] for item in DEFAULT_ETF_UNIVERSE}
    for code, group in df.groupby("code"):
        group = group.sort_values("trade_date").reset_index(drop=True)
        if len(group) < config.fft_window:
            continue
        fft = fft_features(
            group["close"],
            len(group) - 1,
            config.fft_window,
            config.fft_top_k,
            config.fft_min_period,
            config.fft_max_period,
        )
        rows.append(
            {
                "code": str(code),
                "name": names.get(str(code), str(code)),
                "last_date": group.iloc[-1]["trade_date"].strftime("%Y-%m-%d"),
                "top_period": fft["top_period"],
                "top_power_share": fft["top_power_share"],
                "periods": fft["periods"],
            }
        )
    rows.sort(key=lambda row: row["top_power_share"] or 0, reverse=True)
    return rows


def build_report(df: pd.DataFrame, outcomes: pd.DataFrame, metadata: Dict[str, Any], config: AnalysisConfig) -> Dict[str, Any]:
    date_min = df["trade_date"].min().strftime("%Y-%m-%d") if not df.empty else None
    date_max = df["trade_date"].max().strftime("%Y-%m-%d") if not df.empty else None
    primary_horizon = config.horizons[min(2, len(config.horizons) - 1)]
    return {
        "data": {
            "rows": int(len(df)),
            "codes": int(df["code"].nunique()) if not df.empty else 0,
            "date_start": date_min,
            "date_end": date_max,
        },
        "definition": {
            "event_mode": config.event_mode,
            "boll_window": config.boll_window,
            "boll_k": config.boll_k,
            "squeeze_lookback": config.squeeze_lookback,
            "squeeze_quantile": config.squeeze_quantile,
            "contraction_days": config.contraction_days,
            "event_cooldown": config.event_cooldown,
            "large_move_threshold": config.large_move_threshold,
            "horizons": config.horizons,
            "fft_window": config.fft_window,
            "fft_min_period": config.fft_min_period,
            "fft_max_period": config.fft_max_period,
        },
        "event_counts": metadata.get("event_counts", {}),
        "control_counts": metadata.get("control_counts", {}),
        "summary": summarize_outcomes(outcomes, config),
        "fft": summarize_fft(outcomes),
        "by_code": summarize_by_code(outcomes, primary_horizon)[:12],
        "global_fft": global_fft_by_code(df, config)[:12],
    }


def print_report(report: Dict[str, Any]) -> None:
    data = report["data"]
    definition = report["definition"]
    print("ETF Bollinger/FFT event study")
    print(
        f"Data: rows={data['rows']} codes={data['codes']} range={data['date_start']}..{data['date_end']}"
    )
    if definition["event_mode"] == "narrowing-start":
        event_text = (
            f"first {definition['contraction_days']}d bandwidth contraction streak, "
            "regardless of low-width quantile"
        )
    elif definition["event_mode"] == "squeeze":
        event_text = (
            f"low-width contraction days: width <= rolling q{definition['squeeze_quantile']} "
            f"over {definition['squeeze_lookback']}d and contracting {definition['contraction_days']}d"
        )
    else:
        event_text = (
            f"first low-width contraction day: width <= rolling q{definition['squeeze_quantile']} "
            f"over {definition['squeeze_lookback']}d and contracting {definition['contraction_days']}d"
        )
    print(
        "Event: "
        f"{definition['event_mode']} | BOLL({definition['boll_window']}, {definition['boll_k']}) "
        f"{event_text}, cooldown={definition['event_cooldown']}d"
    )
    print(f"Large move: max future high/low move >= {definition['large_move_threshold']:.2%}")
    print("")
    print("Horizon | EventN | CtrlN | EventLarge | CtrlLarge | Lift | Ratio | EventMaxAbs | CtrlMaxAbs | p")
    for item in report["summary"]:
        print(
            f"{item['horizon']:>7} | "
            f"{item.get('event_n', 0):>6} | "
            f"{item.get('control_n', 0):>5} | "
            f"{_format_pct(item.get('event_large_move_rate')):>10} | "
            f"{_format_pct(item.get('control_large_move_rate')):>9} | "
            f"{_format_pct(item.get('large_move_lift')):>5} | "
            f"{_format_float(item.get('large_move_ratio')):>5} | "
            f"{_format_pct(item.get('event_mean_max_abs_move')):>11} | "
            f"{_format_pct(item.get('control_mean_max_abs_move')):>10} | "
            f"{_format_float(item.get('large_move_perm_p')):>5}"
        )

    print("")
    fft = report.get("fft") or {}
    if fft:
        buckets = ", ".join(f"{item['period']}d:{item['count']}" for item in fft.get("top_period_buckets", []))
        print(
            "FFT before events: "
            f"n={fft.get('event_fft_n')} median_period={_format_float(fft.get('median_top_period'))}d "
            f"mean_power_share={_format_pct(fft.get('mean_top_power_share'))}"
        )
        print(f"FFT period buckets: {buckets or '-'}")

    print("")
    print("Top event ETFs by primary horizon:")
    for item in report.get("by_code", [])[:8]:
        print(
            f"  {item['code']} {item['name']}: events={item['events']} "
            f"large={_format_pct(item['large_move_rate'])} "
            f"mean_max_abs={_format_pct(item['mean_max_abs_move'])} "
            f"fft_med={_format_float(item['median_fft_period'])}d"
        )

    print("")
    print("Current global FFT leaders:")
    for item in report.get("global_fft", [])[:8]:
        print(
            f"  {item['code']} {item['name']}: top_period={_format_float(item['top_period'])}d "
            f"power={_format_pct(item['top_power_share'])} last={item['last_date']}"
        )


def _format_pct(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.2%}"
    except Exception:
        return "-"


def _format_float(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.3f}"
    except Exception:
        return "-"


def load_history(args: argparse.Namespace, codes: List[str]) -> pd.DataFrame:
    if args.source == "csv":
        df = load_from_csv(args.csv)
    elif args.source == "akshare":
        df = load_from_akshare(args, codes)
    else:
        df = load_from_mongo(args, codes)

    available = set(df["code"].unique()) if not df.empty else set()
    missing = [code for code in codes if code not in available]
    if missing and args.fallback_akshare and args.source != "akshare":
        fetched = load_from_akshare(args, missing)
        if not fetched.empty:
            df = normalize_history(pd.concat([df, fetched], ignore_index=True))
    return df


def filter_min_rows(df: pd.DataFrame, min_rows: int) -> pd.DataFrame:
    if df.empty:
        return df
    counts = df.groupby("code")["close"].transform("count")
    return df[counts >= min_rows].copy()


def main() -> int:
    args = parse_args()
    try:
        horizons = parse_horizons(args.horizons)
        codes = normalize_codes(args.codes)
        config = AnalysisConfig(
            boll_window=max(2, args.boll_window),
            boll_k=float(args.boll_k),
            squeeze_lookback=max(args.boll_window, args.squeeze_lookback),
            squeeze_quantile=min(max(float(args.squeeze_quantile), 0.01), 0.99),
            contraction_days=max(1, args.contraction_days),
            event_mode=args.event_mode,
            event_cooldown=max(0, args.event_cooldown),
            horizons=horizons,
            large_move_threshold=max(0.0, float(args.large_move_threshold)),
            fft_window=max(16, int(args.fft_window)),
            fft_min_period=max(1.0, float(args.fft_min_period)),
            fft_max_period=float(args.fft_max_period) if args.fft_max_period is not None else None,
            fft_top_k=max(1, int(args.fft_top_k)),
            control_samples_per_event=max(1, args.control_samples_per_event),
            seed=int(args.seed),
            permutation_rounds=max(0, int(args.permutation_rounds)),
        )
        df = filter_min_rows(load_history(args, codes), args.min_rows)
        if df.empty:
            print("No usable ETF history loaded.")
            return 2

        outcomes, metadata = build_event_study(df, config)
        if outcomes.empty:
            print("No events found. Try --event-mode squeeze or lower --squeeze-quantile/--contraction-days.")
            return 3

        report = build_report(df, outcomes, metadata, config)
        if args.export_csv:
            export_path = Path(args.export_csv)
            export_path.parent.mkdir(parents=True, exist_ok=True)
            export_df = outcomes.copy()
            export_df["fft_periods"] = export_df["fft_periods"].map(json.dumps)
            export_df.to_csv(export_path, index=False, encoding="utf-8-sig")
            report["export_csv"] = str(export_path)

        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print_report(report)
            if args.export_csv:
                print("")
                print(f"Exported rows: {args.export_csv}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
