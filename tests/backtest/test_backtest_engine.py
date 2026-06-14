from __future__ import annotations

import asyncio
from math import isclose, isfinite

import pandas as pd

from app.services.backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    DEFAULT_ETF_UNIVERSE,
    DEFAULT_ROTATION_UNIVERSE,
    STRATEGIES,
    StrategyContext,
    _empty_rule_mask,
    _rebalance_dates,
)
import app.services.backtest.etf_data_service as etf_data_module
from app.services.backtest.etf_data_service import (
    ETFDataService,
    _dedupe_history_by_source,
    verify_adjustment_factor_rows,
)
from app.services.backtest.strategy_catalog import STRATEGY_TEMPLATES, strategy_default_params


def _records(prices: list[float], start: str = "2021-01-01") -> list[dict]:
    import pandas as pd

    dates = pd.bdate_range(start=start, periods=len(prices))
    rows = []
    for date, close in zip(dates, prices):
        rows.append(
            {
                "trade_date": date.strftime("%Y-%m-%d"),
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 1_000_000,
            }
        )
    return rows


def test_default_universe_includes_chinext_index_etfs() -> None:
    by_code = {item["code"]: item for item in DEFAULT_ETF_UNIVERSE}

    assert by_code["159915"]["name"] == "创业板ETF易方达"
    assert by_code["159952"]["name"] == "创业板ETF广发"
    assert by_code["159956"]["name"] == "创业板ETF建信"


def test_default_universe_includes_dividend_low_volatility_etfs() -> None:
    by_code = {item["code"]: item for item in DEFAULT_ETF_UNIVERSE}

    assert by_code["512890"]["name"] == "红利低波ETF华泰柏瑞"
    assert by_code["515100"]["name"] == "红利低波100ETF景顺"
    assert by_code["515300"]["name"] == "300红利低波ETF嘉实"
    assert by_code["563020"]["name"] == "红利低波ETF易方达"
    assert {by_code[code]["group"] for code in ["512890", "515100", "515300", "563020"]} == {"factor"}


def test_default_rotation_universe_excludes_cash_watch_etfs() -> None:
    assert "511880" in {item["code"] for item in DEFAULT_ETF_UNIVERSE}
    assert "511880" not in {item["code"] for item in DEFAULT_ROTATION_UNIVERSE}


def test_strategy_catalog_matches_engine_registry() -> None:
    assert set(STRATEGY_TEMPLATES) == set(STRATEGIES)
    params = strategy_default_params("industry_momentum_enhanced", {"top_k": 2})
    assert params["top_k"] == 2
    assert params["momentum_windows"] == [40, 120, 250]
    assert params["trend_fast_ma"] == 20
    assert params["trend_ma"] == 120
    assert params["empty_threshold"] == "trend_filter"


def test_biweekly_rebalance_dates_use_every_other_week() -> None:
    dates = pd.bdate_range("2021-01-01", "2021-01-29")

    weekly = [date.strftime("%Y-%m-%d") for date in _rebalance_dates(dates, "weekly")]
    biweekly = [date.strftime("%Y-%m-%d") for date in _rebalance_dates(dates, "biweekly")]

    assert weekly == ["2021-01-01", "2021-01-08", "2021-01-15", "2021-01-22"]
    assert biweekly == ["2021-01-01", "2021-01-15"]


def test_trend_filter_can_require_fast_ma_above_slow_ma() -> None:
    dates = pd.bdate_range("2021-01-01", periods=41)
    prices = [100.0] * 30 + [90.0] * 10 + [101.0]
    close = pd.DataFrame({"510300": prices}, index=dates)
    ctx = StrategyContext(
        close=close,
        open=close,
        high=close,
        low=close,
        volume=pd.DataFrame({"510300": [1_000_000] * len(dates)}, index=dates),
        returns=close.pct_change().replace([float("inf"), float("-inf")], pd.NA).fillna(0),
    )
    idx = len(close.index) - 1
    score = pd.Series({"510300": 1.0})
    ret = pd.Series({"510300": close.iloc[idx]["510300"] / close.iloc[idx - 5]["510300"] - 1})

    loose = _empty_rule_mask(ctx, idx, "trend_filter", score, ret, trend_ma=20)
    strict = _empty_rule_mask(ctx, idx, "trend_filter", score, ret, trend_ma=20, trend_fast_ma=5)

    assert bool(loose["510300"])
    assert not bool(strict["510300"])


def test_etf_history_standardizes_chinese_columns() -> None:
    service = ETFDataService({"etf_basic_info": None, "etf_daily_quotes": None})
    frame = pd.DataFrame(
        [
            {
                "\u65e5\u671f": "2025-06-03",
                "\u5f00\u76d8": 0.807,
                "\u6536\u76d8": 0.822,
                "\u6700\u9ad8": 0.826,
                "\u6700\u4f4e": 0.806,
                "\u6210\u4ea4\u91cf": 100,
                "\u6210\u4ea4\u989d": 200,
            }
        ]
    )

    rows = service._standardize_history(frame, "unit", "2025-06-01", "2025-06-30")

    assert rows[0]["trade_date"] == "2025-06-03"
    assert rows[0]["close"] == 0.822


def test_history_source_priority_prefers_tushare() -> None:
    records = [
        {
            "trade_date": "2025-01-02",
            "close": 1.0,
            "source": "akshare_fund_etf_hist_em",
        },
        {
            "trade_date": "2025-01-02",
            "close": 2.0,
            "source": "tushare_fund_daily_factor_qfq",
        },
    ]

    deduped = _dedupe_history_by_source(records)

    assert len(deduped) == 1
    assert deduped[0]["close"] == 2.0


def test_qfq_history_does_not_fallback_to_unadjusted_sina() -> None:
    class Service(ETFDataService):
        def _should_prefer_tushare(self) -> bool:
            return False

        def _fetch_history_em(self, code: str, start_date: str, end_date: str, adjust: str):
            return []

        def _fetch_history_sina(self, code: str, start_date: str, end_date: str):
            raise AssertionError("qfq should not fallback to unadjusted sina data")

    service = Service({"etf_basic_info": None, "etf_daily_quotes": None})

    assert service._fetch_history("512800", "2025-06-01", "2025-08-31", "qfq") == []


def test_tushare_history_failure_falls_back_to_eastmoney() -> None:
    class Service(ETFDataService):
        def _should_prefer_tushare(self) -> bool:
            return True

        def _fetch_history_tushare(self, code: str, start_date: str, end_date: str, adjust: str):
            raise ConnectionError("tushare unavailable")

        def _fetch_history_em(self, code: str, start_date: str, end_date: str, adjust: str):
            return [{"trade_date": "2025-01-02", "close": 1.0, "source": "akshare_fund_etf_hist_em"}]

    service = Service({"etf_basic_info": None, "etf_daily_quotes": None, "etf_adjustment_factors": None})

    rows = service._fetch_history("510300", "2025-01-01", "2025-01-31", "qfq")

    assert rows[0]["source"] == "akshare_fund_etf_hist_em"


def test_qfq_history_map_does_not_use_unadjusted_cache() -> None:
    class Service(ETFDataService):
        async def ensure_indexes(self) -> None:
            return None

        async def _query_history(self, code: str, start_date: str, end_date: str, adjust: str):
            if adjust == "none":
                return _records([1.0 + i * 0.01 for i in range(40)], start=start_date)
            return []

        async def fetch_and_cache_history(
            self,
            code: str,
            start_date: str,
            end_date: str,
            adjust: str = "qfq",
        ) -> int:
            return 0

    service = Service({"etf_basic_info": None, "etf_daily_quotes": None})

    history, warnings = asyncio.run(
        service.get_history_map(["512800"], "2025-06-01", "2025-08-31", "qfq")
    )

    assert history == {}
    assert "512800: no cached ETF history" in warnings


def test_verify_adjustment_factor_rows_matches_qfq_prices() -> None:
    raw_records = [
        {"trade_date": "2025-01-02", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0},
        {"trade_date": "2025-01-03", "open": 20.0, "high": 22.0, "low": 18.0, "close": 20.0},
    ]
    factor_records = [
        {"trade_date": "2025-01-02", "factor": 0.5},
        {"trade_date": "2025-01-03", "factor": 1.0},
    ]
    qfq_records = [
        {"trade_date": "2025-01-02", "open": 5.0, "high": 5.5, "low": 4.5, "close": 5.0},
        {"trade_date": "2025-01-03", "open": 20.0, "high": 22.0, "low": 18.0, "close": 20.0},
    ]

    report = verify_adjustment_factor_rows(raw_records, qfq_records, factor_records, tolerance=1e-9)

    assert report["common_count"] == 2
    assert report["max_abs_error"] == 0
    assert report["mismatch_count"] == 0


def test_cached_history_covers_weekend_end_date() -> None:
    service = ETFDataService({"etf_basic_info": None, "etf_daily_quotes": None})
    records = [{"trade_date": date.strftime("%Y-%m-%d")} for date in pd.bdate_range("2026-05-01", "2026-06-12")]

    assert service._covers_range(records, "2026-05-01", "2026-06-13")


def test_qfq_history_retries_transient_disconnect() -> None:
    class Service(ETFDataService):
        def __init__(self):
            super().__init__({"etf_basic_info": None, "etf_daily_quotes": None})
            self.calls = 0

        def _should_prefer_tushare(self) -> bool:
            return False

        def _fetch_history_em(self, code: str, start_date: str, end_date: str, adjust: str):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("Remote end closed connection without response")
            return [
                {
                    "trade_date": "2025-06-03",
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "volume": 1_000,
                    "source": "unit",
                }
            ]

    service = Service()
    original_delay = etf_data_module.FETCH_RETRY_DELAY_SECONDS
    etf_data_module.FETCH_RETRY_DELAY_SECONDS = 0
    try:
        rows = service._fetch_history("512800", "2025-06-01", "2025-08-31", "qfq")
    finally:
        etf_data_module.FETCH_RETRY_DELAY_SECONDS = original_delay

    assert service.calls == 2
    assert rows[0]["trade_date"] == "2025-06-03"


def test_empty_qualified_universe_stays_in_cash() -> None:
    engine = BacktestEngine()
    records_by_code = {
        "510300": _records([100 - i * 0.10 for i in range(260)]),
        "510500": _records([90 - i * 0.08 for i in range(260)]),
    }

    result = engine.run(
        records_by_code,
        BacktestConfig(
            strategy_id="dual_momentum_core",
            start_date="2021-01-01",
            end_date="2021-12-31",
            universe=["510300", "510500"],
            params={
                "momentum_window": 20,
                "trend_ma": 20,
                "rebalance_frequency": "weekly",
                "top_k": 1,
                "empty_threshold": "trend_filter",
            },
        ),
    )

    assert result["trades"] == []
    assert result["metrics"]["cash_days_ratio"] == 1.0
    assert all(not item["weights"] for item in result["positions"])


def test_rotation_buys_positive_momentum_and_charges_commission() -> None:
    engine = BacktestEngine()
    records_by_code = {
        "510300": _records([100 + i * 0.20 for i in range(260)]),
        "510500": _records([100 - i * 0.05 for i in range(260)]),
    }

    result = engine.run(
        records_by_code,
        BacktestConfig(
            strategy_id="dual_momentum_core",
            start_date="2021-01-01",
            end_date="2021-12-31",
            universe=["510300", "510500"],
            commission_bps=5,
            slippage_bps=5,
            params={
                "momentum_window": 20,
                "trend_ma": 20,
                "rebalance_frequency": "weekly",
                "top_k": 1,
                "empty_threshold": "trend_filter",
            },
        ),
    )

    buy_trades = [trade for trade in result["trades"] if trade["side"] == "buy"]

    assert buy_trades
    assert {trade["code"] for trade in buy_trades} == {"510300"}
    assert result["metrics"]["trade_count"] > 0
    assert all(isclose(trade["commission"], trade["amount"] * 0.0005, rel_tol=1e-4) for trade in buy_trades)


def test_missing_early_prices_do_not_pollute_equity_or_trades() -> None:
    engine = BacktestEngine()
    records_by_code = {
        "510300": _records([100 + i * 0.20 for i in range(90)], start="2021-01-01"),
        "512480": _records([80 + i * 0.50 for i in range(40)], start="2021-03-01"),
    }

    result = engine.run(
        records_by_code,
        BacktestConfig(
            strategy_id="dual_momentum_core",
            start_date="2021-01-01",
            end_date="2021-04-30",
            universe=["510300", "512480"],
            params={
                "momentum_window": 5,
                "trend_ma": 3,
                "rebalance_frequency": "weekly",
                "top_k": 1,
                "empty_threshold": "ret_gt_0",
            },
        ),
    )

    assert result["equity_curve"][0]["equity"] == 1_000_000.0
    assert all(isfinite(row["equity"]) for row in result["equity_curve"])
    assert all(isfinite(trade["amount"]) and isfinite(trade["commission"]) for trade in result["trades"])


def test_indicator_warmup_uses_records_before_requested_start() -> None:
    engine = BacktestEngine()
    records_by_code = {
        "510300": _records([100 + i * 0.2 for i in range(70)], start="2020-12-01"),
    }

    result = engine.run(
        records_by_code,
        BacktestConfig(
            strategy_id="dual_momentum_core",
            start_date="2021-01-04",
            end_date="2021-02-26",
            universe=["510300"],
            params={
                "momentum_window": 20,
                "trend_ma": 20,
                "rebalance_frequency": "weekly",
                "top_k": 1,
                "empty_threshold": "ret_gt_0",
                "cash_entry_mode": "rebalance_only",
            },
        ),
    )

    first_buy = next(trade for trade in result["trades"] if trade["side"] == "buy")

    assert result["equity_curve"][0]["date"] == "2021-01-04"
    assert result["diagnostics"]["data_start"] == "2021-01-04"
    assert first_buy["date"] == "2021-01-11"


def test_cash_scan_requires_two_confirmations_before_next_monthly_rebalance() -> None:
    engine = BacktestEngine()
    prices = [100 - i * 0.5 for i in range(21)] + [90 + i * 1.0 for i in range(44)]
    records_by_code = {"510300": _records(prices)}
    common_params = {
        "momentum_window": 5,
        "trend_ma": 3,
        "rebalance_frequency": "monthly",
        "top_k": 1,
        "empty_threshold": "ret_gt_0",
    }

    daily_scan = engine.run(
        records_by_code,
        BacktestConfig(
            strategy_id="dual_momentum_core",
            start_date="2021-01-01",
            end_date="2021-03-31",
            universe=["510300"],
            params={
                **common_params,
                "cash_entry_mode": "daily_when_cash",
                "cash_entry_confirmations": 2,
                "min_days_to_rebalance_for_cash_entry": 2,
            },
        ),
    )
    rebalance_only = engine.run(
        records_by_code,
        BacktestConfig(
            strategy_id="dual_momentum_core",
            start_date="2021-01-01",
            end_date="2021-03-31",
            universe=["510300"],
            params={**common_params, "cash_entry_mode": "rebalance_only"},
        ),
    )

    first_daily_buy = next(trade["date"] for trade in daily_scan["trades"] if trade["side"] == "buy")
    first_periodic_buy = next(trade["date"] for trade in rebalance_only["trades"] if trade["side"] == "buy")
    confirmed_signal = next(
        signal for signal in daily_scan["signals"] if signal.get("trigger") == "cash_confirmed_scan"
    )

    assert first_daily_buy < first_periodic_buy
    assert first_daily_buy == confirmed_signal["execute_date"]
    assert confirmed_signal["cash_entry_streak"] == 2
    assert confirmed_signal["days_to_next_rebalance"] > 2


def test_cash_scan_waits_when_next_rebalance_is_too_close() -> None:
    engine = BacktestEngine()
    prices = [100 - i * 0.5 for i in range(21)] + [90 + i * 1.0 for i in range(44)]
    records_by_code = {"510300": _records(prices)}
    common_params = {
        "momentum_window": 5,
        "trend_ma": 3,
        "rebalance_frequency": "monthly",
        "top_k": 1,
        "empty_threshold": "ret_gt_0",
    }

    blocked_scan = engine.run(
        records_by_code,
        BacktestConfig(
            strategy_id="dual_momentum_core",
            start_date="2021-01-01",
            end_date="2021-03-31",
            universe=["510300"],
            params={
                **common_params,
                "cash_entry_mode": "daily_when_cash",
                "cash_entry_confirmations": 2,
                "min_days_to_rebalance_for_cash_entry": 999,
            },
        ),
    )
    rebalance_only = engine.run(
        records_by_code,
        BacktestConfig(
            strategy_id="dual_momentum_core",
            start_date="2021-01-01",
            end_date="2021-03-31",
            universe=["510300"],
            params={**common_params, "cash_entry_mode": "rebalance_only"},
        ),
    )

    first_blocked_buy = next(trade["date"] for trade in blocked_scan["trades"] if trade["side"] == "buy")
    first_periodic_buy = next(trade["date"] for trade in rebalance_only["trades"] if trade["side"] == "buy")

    assert first_blocked_buy == first_periodic_buy
    assert all(signal.get("trigger") != "cash_confirmed_scan" for signal in blocked_scan["signals"])


def test_entry_delay_keeps_cash_until_allowed_trading_day() -> None:
    engine = BacktestEngine()
    records_by_code = {
        "510300": _records([100 + i * 0.30 for i in range(80)]),
    }

    result = engine.run(
        records_by_code,
        BacktestConfig(
            strategy_id="dual_momentum_core",
            start_date="2021-01-01",
            end_date="2021-04-30",
            universe=["510300"],
            entry_delay_trading_days=10,
            params={
                "momentum_window": 5,
                "trend_ma": 3,
                "rebalance_frequency": "weekly",
                "top_k": 1,
                "empty_threshold": "ret_gt_0",
                "cash_entry_mode": "daily_when_cash",
                "cash_entry_confirmations": 1,
                "min_days_to_rebalance_for_cash_entry": 0,
            },
        ),
    )

    first_buy = next(trade for trade in result["trades"] if trade["side"] == "buy")
    allowed_date = result["equity_curve"][10]["date"]

    assert all(not row["weights"] for row in result["positions"][:10])
    assert first_buy["date"] >= allowed_date
    assert result["diagnostics"]["entry_delay_trading_days"] == 10


def test_full_exit_does_not_leave_zero_weight_dust_position() -> None:
    engine = BacktestEngine()
    prices = [100 + i * 0.5 for i in range(40)] + [120 - i * 1.0 for i in range(50)]
    records_by_code = {"510300": _records(prices)}

    result = engine.run(
        records_by_code,
        BacktestConfig(
            strategy_id="dual_momentum_core",
            start_date="2021-01-01",
            end_date="2021-04-30",
            universe=["510300"],
            commission_bps=0,
            slippage_bps=0,
            params={
                "momentum_window": 5,
                "trend_ma": 3,
                "rebalance_frequency": "monthly",
                "top_k": 1,
                "empty_threshold": "ret_gt_0",
                "cash_entry_mode": "rebalance_only",
            },
        ),
    )

    first_sell_date = next(trade["date"] for trade in result["trades"] if trade["side"] == "sell")
    after_exit = [row for row in result["positions"] if row["date"] >= first_sell_date]

    assert after_exit
    assert all(not row["weights"] for row in after_exit)
