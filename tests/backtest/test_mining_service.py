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
