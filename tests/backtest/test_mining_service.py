from __future__ import annotations

import pandas as pd

from app.services.backtest.mining_service import DEFAULT_SEARCH_SPACE, MiningService


class _Collection:
    async def create_index(self, *args, **kwargs):
        return None


class _Db:
    def __getitem__(self, name: str):
        return _Collection()


def _service() -> MiningService:
    return MiningService(_Db())


def _records(days: int = 900) -> dict[str, list[dict]]:
    dates = pd.bdate_range("2021-01-01", periods=days)
    return {"510300": [{"trade_date": date.strftime("%Y-%m-%d")} for date in dates]}


def test_random_trials_are_unique_without_building_full_cartesian_product() -> None:
    service = _service()

    trials = service._generate_trials(
        templates=["industry_momentum_enhanced", "adaptive_regime_rotation"],
        search_space=DEFAULT_SEARCH_SPACE,
        search_method="random",
        max_trials=30,
        seed=3,
    )

    fingerprints = {service._trial_fingerprint(trial) for trial in trials}
    assert len(trials) == 30
    assert len(fingerprints) == len(trials)
    assert all("cash_entry_confirmations" in trial["params"] for trial in trials)


def test_grid_trials_cover_each_template_with_bounded_sample() -> None:
    service = _service()

    trials = service._generate_trials(
        templates=["industry_momentum_enhanced", "adaptive_regime_rotation"],
        search_space=DEFAULT_SEARCH_SPACE,
        search_method="grid",
        max_trials=12,
        seed=7,
    )

    assert len(trials) == 12
    assert {trial["strategy_id"] for trial in trials} == {
        "industry_momentum_enhanced",
        "adaptive_regime_rotation",
    }


def test_adaptive_params_use_regime_search_keys() -> None:
    service = _service()
    params = service._params_for_template(
        "adaptive_regime_rotation",
        {
            "rebalance_frequency": "biweekly",
            "momentum_window": 120,
            "absolute_window": 40,
            "trend_fast_ma": 40,
            "trend_ma": 200,
            "vol_window": 120,
            "regime_fast_ma": 60,
            "regime_slow_ma": 250,
            "regime_momentum_window": 120,
            "top_k_uptrend": 2,
            "top_k_range": 3,
            "top_k_downtrend": 0,
            "cash_entry_confirmations": 3,
            "min_days_to_rebalance_for_cash_entry": 5,
        },
    )

    assert params["rebalance_frequency"] == "biweekly"
    assert params["regime_fast_ma"] == 60
    assert params["regime_slow_ma"] == 250
    assert params["regime_momentum_window"] == 120
    assert params["top_k_uptrend"] == 2
    assert params["top_k_range"] == 3
    assert params["top_k_downtrend"] == 0
    assert params["cash_entry_confirmations"] == 3
    assert params["min_days_to_rebalance_for_cash_entry"] == 5


def test_biweekly_stable_mining_defaults_match_strategy_catalog() -> None:
    service = _service()

    params = service._params_for_template("biweekly_adaptive_stable_rotation", {})

    assert 10 in DEFAULT_SEARCH_SPACE["regime_fast_ma"]
    assert params["rebalance_frequency"] == "biweekly"
    assert params["momentum_windows"] == [20, 60, 120]
    assert params["trend_fast_ma"] == 10
    assert params["trend_ma"] == 60
    assert params["vol_window"] == 20
    assert params["absolute_window"] == 20
    assert params["regime_fast_ma"] == 10
    assert params["min_holding_days"] == 20
    assert params["rank_switch_buffer"] == 2


def test_industry_mining_can_generate_adaptive_top_k_rule() -> None:
    service = _service()

    params = service._params_for_template(
        "industry_momentum_enhanced",
        {"top_k": 1, "adaptive_top_k": True, "top_k_score_gap": 0.08},
    )

    assert params["adaptive_top_k"] is True
    assert params["top_k"] == 2
    assert params["top_k_score_gap"] == 0.08


def test_price_tool_strategy_mining_params_are_generated() -> None:
    service = _service()

    ema = service._params_for_template(
        "ema_momentum_rotation",
        {"fast_ema": 60, "slow_ema": 50, "momentum_window": 20, "trend_weight": 0.75},
    )
    price_action = service._params_for_template(
        "price_action_breakout_rotation",
        {"lookback": 60, "momentum_window": 40, "higher_low_window": 5, "require_higher_low": True},
    )
    fibonacci = service._params_for_template(
        "fibonacci_retracement_rotation",
        {"lookback": 120, "fib_low": 0.382, "fib_high": 0.618, "bounce_days": 3},
    )

    assert ema["fast_ema"] == 60
    assert ema["slow_ema"] > ema["fast_ema"]
    assert ema["trend_weight"] == 0.75
    assert price_action["lookback"] == 60
    assert price_action["higher_low_window"] == 5
    assert price_action["require_higher_low"] is True
    assert fibonacci["lookback"] == 120
    assert fibonacci["fib_low"] == 0.382
    assert fibonacci["fib_high"] == 0.618
    assert fibonacci["bounce_days"] == 3


def test_auto_robust_profile_uses_stable_templates_and_constraints() -> None:
    service = _service()

    payload = service._prepare_payload(
        {
            "mode": "auto_robust",
            "templates": ["fibonacci_retracement_rotation"],
            "search_method": "grid",
            "max_trials": 10,
            "constraints": {"max_drawdown": 0.9},
        }
    )

    assert payload["mode"] == "auto_robust"
    assert payload["search_method"] == "random"
    assert payload["max_trials"] == 120
    assert "fibonacci_retracement_rotation" not in payload["templates"]
    assert "ema_momentum_rotation" in payload["templates"]
    assert payload["search_space"]["require_higher_low"] == [True]
    assert payload["constraints"]["max_drawdown"] == 0.30
    assert payload["constraints"]["min_walk_forward_sample_count"] == 3


def test_split_plan_adds_walk_forward_slices() -> None:
    service = _service()

    plan = service._split_plan(
        _records(),
        "2021-01-01",
        "2024-06-30",
        {
            "walk_forward": True,
            "walk_forward_train_days": 252,
            "walk_forward_validation_days": 63,
            "walk_forward_test_days": 63,
            "walk_forward_step_days": 63,
            "max_walk_forward_slices": 3,
        },
    )

    assert set(plan["holdout"]) == {"train", "validation", "test"}
    assert len(plan["walk_forward"]) == 3
    assert plan["walk_forward"][0]["label"] == "WF1"
    assert plan["walk_forward"][0]["test"]["start_date"] > plan["walk_forward"][0]["validation"]["end_date"]


def test_walk_forward_summary_feeds_acceptance_rules() -> None:
    service = _service()
    metrics = {
        "train": {"total_return": 0.1, "max_drawdown": -0.1, "trade_count": 5},
        "validation": {"total_return": 0.08, "calmar": 0.5, "max_drawdown": -0.1, "trade_count": 5},
        "test": {
            "total_return": 0.06,
            "excess_return": 0.02,
            "calmar": 0.4,
            "max_drawdown": -0.12,
            "trade_count": 5,
            "avg_turnover": 0.3,
        },
    }
    stress = {"total_return": 0.03}
    unstable = {
        "sample_count": 3,
        "positive_ratio": 0.333333,
        "beat_benchmark_ratio": 0.333333,
        "calmar_median": 0.2,
        "calmar_std": 0.4,
    }

    accepted, reasons = service._accepted(metrics, stress, unstable, {"constraints": {}})
    score = service._score(metrics, stress, unstable)

    assert not accepted
    assert "walk_forward_return_unstable" in reasons
    assert "walk_forward_excess_unstable" in reasons
    assert score < 1


def test_explain_trial_returns_checks_and_score_components() -> None:
    service = _service()
    payload = service._prepare_payload({"mode": "auto_robust"})
    metrics = {
        "train": {"total_return": 0.10, "max_drawdown": -0.08, "trade_count": 10},
        "validation": {
            "total_return": 0.08,
            "excess_return": 0.02,
            "calmar": 0.6,
            "max_drawdown": -0.10,
            "trade_count": 8,
        },
        "test": {
            "total_return": 0.07,
            "excess_return": 0.03,
            "calmar": 0.5,
            "max_drawdown": -0.12,
            "trade_count": 8,
            "avg_turnover": 0.2,
        },
    }
    stress = {"total_return": 0.04}
    walk_forward = {
        "sample_count": 3,
        "positive_ratio": 0.666667,
        "beat_benchmark_ratio": 0.666667,
        "calmar_median": 0.4,
        "calmar_std": 0.2,
        "excess_return_median": 0.02,
    }

    accepted, reasons = service._accepted(metrics, stress, walk_forward, payload)
    components = service._score_components(metrics, stress, walk_forward)
    explanation = service._explain_trial(accepted, metrics, stress, walk_forward, components, payload)

    assert accepted
    assert reasons == []
    assert explanation["decision"] == "accepted"
    assert explanation["failed_checks"] == []
    assert any(item["key"] == "walk_forward_positive_ratio" for item in explanation["passed_checks"])
    assert explanation["score_components"]["positive"]["test_calmar"] == 0.5
    assert explanation["robustness"]["walk_forward_sample_count"] == 3
