from __future__ import annotations

import asyncio
import json
import random
import uuid
from datetime import datetime
from statistics import median, pstdev
from typing import Any, Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase

from .backtest_service import BacktestService
from .engine import DEFAULT_ROTATION_UNIVERSE, STRATEGIES
from .strategy_catalog import STRATEGY_TEMPLATES


DEFAULT_SEARCH_SPACE: Dict[str, List[Any]] = {
    "momentum_window": [10, 20, 40, 60, 120, 250],
    "lookback": [20, 40, 60, 120, 180, 250],
    "absolute_window": [10, 20, 40, 60, 120],
    "trend_fast_ma": [0, 10, 20, 40, 60],
    "trend_ma": [20, 60, 120, 200],
    "fast_ema": [10, 20, 30, 40, 60],
    "slow_ema": [50, 80, 120, 200],
    "trend_ema": [20, 60, 120],
    "trend_weight": [0.25, 0.5, 0.75],
    "vol_window": [20, 60, 120],
    "min_momentum": [0.0, 0.02],
    "higher_low_window": [5, 10, 20],
    "breakout_buffer": [0.97, 0.99, 1.0],
    "require_higher_low": [True, False],
    "fib_low": [0.236, 0.382],
    "fib_high": [0.5, 0.618, 0.786],
    "zone_tolerance": [0.0, 0.02, 0.05],
    "bounce_days": [1, 3, 5],
    "bounce_threshold": [0.0, 0.01],
    "min_leg_return": [0.08, 0.15, 0.25],
    "regime_fast_ma": [10, 20, 40, 60],
    "regime_slow_ma": [120, 200, 250],
    "regime_momentum_window": [40, 60, 120],
    "rebalance_frequency": ["weekly", "biweekly", "monthly"],
    "top_k": [1, 2, 3, 5],
    "adaptive_top_k": [False, True],
    "top_k_score_gap": [0.02, 0.05, 0.08, 0.10],
    "top_k_uptrend": [1, 2],
    "top_k_range": [1, 2, 3],
    "top_k_downtrend": [0, 1, 2],
    "empty_threshold": ["ret_gt_0", "score_gt_0", "trend_filter"],
    "cash_entry_mode": ["daily_when_cash", "rebalance_only"],
    "cash_entry_confirmations": [1, 2, 3],
    "min_days_to_rebalance_for_cash_entry": [0, 2, 5],
    "min_holding_days": [0, 10, 20, 30],
    "rank_switch_buffer": [0, 1, 2],
    "rebalance_turnover_threshold": [0.0, 0.1, 0.18, 0.25],
}


DEFAULT_TEMPLATES = [
    strategy_id
    for strategy_id in STRATEGY_TEMPLATES
    if strategy_id != "fibonacci_retracement_rotation"
]

AUTO_ROBUST_TEMPLATES = [
    "industry_momentum_enhanced",
    "biweekly_adaptive_stable_rotation",
    "dual_momentum_core",
    "trend_following_equal_weight",
    "ema_momentum_rotation",
    "price_action_breakout_rotation",
]

AUTO_ROBUST_SEARCH_SPACE: Dict[str, List[Any]] = {
    "momentum_window": [20, 40, 60, 120],
    "lookback": [40, 60, 120, 180],
    "absolute_window": [20, 40, 60],
    "trend_fast_ma": [10, 20, 40],
    "trend_ma": [60, 120, 200],
    "fast_ema": [20, 30, 40, 60],
    "slow_ema": [50, 80, 120, 200],
    "trend_weight": [0.25, 0.5, 0.75],
    "vol_window": [20, 60],
    "vol_penalty": [0.0, 0.02, 0.03, 0.04],
    "min_momentum": [0.0, 0.02],
    "higher_low_window": [5, 10],
    "breakout_buffer": [0.99, 1.0],
    "require_higher_low": [True],
    "regime_fast_ma": [10, 20, 40],
    "regime_slow_ma": [120, 200],
    "regime_momentum_window": [40, 60, 120],
    "rebalance_frequency": ["weekly", "biweekly", "monthly"],
    "top_k": [1, 2, 3],
    "adaptive_top_k": [False, True],
    "top_k_score_gap": [0.02, 0.05, 0.08, 0.10],
    "top_k_uptrend": [1, 2],
    "top_k_range": [1, 2],
    "top_k_downtrend": [0, 1],
    "empty_threshold": ["ret_gt_0", "score_gt_0", "trend_filter"],
    "cash_entry_mode": ["daily_when_cash", "rebalance_only"],
    "cash_entry_confirmations": [2, 3],
    "min_days_to_rebalance_for_cash_entry": [0, 2, 5],
    "min_holding_days": [10, 20, 30],
    "rank_switch_buffer": [1, 2],
    "rebalance_turnover_threshold": [0.1, 0.18, 0.25],
}

AUTO_ROBUST_CONSTRAINTS: Dict[str, Any] = {
    "max_drawdown": 0.30,
    "min_trades": 6,
    "min_walk_forward_sample_count": 3,
    "min_walk_forward_positive_ratio": 0.60,
    "min_walk_forward_beat_benchmark_ratio": 0.50,
    "min_validation_return": 0.0,
    "min_test_calmar": 0.0,
    "max_calmar_gap": 2.5,
}


TEMPLATE_SEARCH_KEYS: Dict[str, List[str]] = {
    "industry_momentum_enhanced": [
        "rebalance_frequency",
        "top_k",
        "adaptive_top_k",
        "top_k_score_gap",
        "momentum_window",
        "absolute_window",
        "trend_fast_ma",
        "trend_ma",
        "vol_window",
        "empty_threshold",
        "cash_entry_mode",
        "cash_entry_confirmations",
        "min_days_to_rebalance_for_cash_entry",
    ],
    "vol_adjusted_momentum": [
        "rebalance_frequency",
        "top_k",
        "momentum_window",
        "trend_ma",
        "vol_window",
        "empty_threshold",
        "cash_entry_mode",
        "cash_entry_confirmations",
        "min_days_to_rebalance_for_cash_entry",
    ],
    "dual_momentum_core": [
        "rebalance_frequency",
        "top_k",
        "momentum_window",
        "trend_fast_ma",
        "trend_ma",
        "empty_threshold",
        "cash_entry_mode",
        "cash_entry_confirmations",
        "min_days_to_rebalance_for_cash_entry",
    ],
    "trend_following_equal_weight": [
        "rebalance_frequency",
        "top_k",
        "momentum_window",
        "trend_fast_ma",
        "trend_ma",
        "empty_threshold",
        "cash_entry_mode",
        "cash_entry_confirmations",
        "min_days_to_rebalance_for_cash_entry",
    ],
    "ema_momentum_rotation": [
        "rebalance_frequency",
        "top_k",
        "fast_ema",
        "slow_ema",
        "momentum_window",
        "vol_window",
        "trend_weight",
        "vol_penalty",
        "min_momentum",
        "cash_entry_mode",
        "cash_entry_confirmations",
        "min_days_to_rebalance_for_cash_entry",
    ],
    "price_action_breakout_rotation": [
        "rebalance_frequency",
        "top_k",
        "momentum_window",
        "lookback",
        "vol_window",
        "higher_low_window",
        "breakout_buffer",
        "require_higher_low",
        "min_momentum",
        "vol_penalty",
        "cash_entry_mode",
        "cash_entry_confirmations",
        "min_days_to_rebalance_for_cash_entry",
    ],
    "fibonacci_retracement_rotation": [
        "rebalance_frequency",
        "top_k",
        "momentum_window",
        "lookback",
        "trend_ema",
        "vol_window",
        "fib_low",
        "fib_high",
        "zone_tolerance",
        "bounce_days",
        "bounce_threshold",
        "min_leg_return",
        "vol_penalty",
        "cash_entry_mode",
        "cash_entry_confirmations",
        "min_days_to_rebalance_for_cash_entry",
    ],
    "adaptive_regime_rotation": [
        "rebalance_frequency",
        "momentum_window",
        "absolute_window",
        "trend_fast_ma",
        "trend_ma",
        "vol_window",
        "regime_fast_ma",
        "regime_slow_ma",
        "regime_momentum_window",
        "top_k_uptrend",
        "top_k_range",
        "top_k_downtrend",
        "cash_entry_mode",
        "cash_entry_confirmations",
        "min_days_to_rebalance_for_cash_entry",
    ],
    "biweekly_adaptive_stable_rotation": [
        "momentum_window",
        "absolute_window",
        "trend_fast_ma",
        "trend_ma",
        "vol_window",
        "regime_fast_ma",
        "regime_slow_ma",
        "regime_momentum_window",
        "top_k_uptrend",
        "top_k_range",
        "top_k_downtrend",
        "cash_entry_mode",
        "cash_entry_confirmations",
        "min_days_to_rebalance_for_cash_entry",
        "min_holding_days",
        "rank_switch_buffer",
        "rebalance_turnover_threshold",
    ],
    "donchian_breakout_rotation": [
        "rebalance_frequency",
        "top_k",
        "momentum_window",
        "vol_window",
        "cash_entry_mode",
        "cash_entry_confirmations",
        "min_days_to_rebalance_for_cash_entry",
    ],
    "rsrs_timing_rotation": [
        "rebalance_frequency",
        "top_k",
        "momentum_window",
        "cash_entry_mode",
        "cash_entry_confirmations",
        "min_days_to_rebalance_for_cash_entry",
    ],
    "chan_fractal_rotation": [
        "rebalance_frequency",
        "top_k",
        "momentum_window",
        "trend_ma",
        "cash_entry_mode",
        "cash_entry_confirmations",
        "min_days_to_rebalance_for_cash_entry",
    ],
    "chan_center_breakout": [
        "rebalance_frequency",
        "top_k",
        "momentum_window",
        "cash_entry_mode",
        "cash_entry_confirmations",
        "min_days_to_rebalance_for_cash_entry",
    ],
}


class MiningService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.backtest = BacktestService(db)
        self.runs = db["backtest_mining_runs"]
        self.trials = db["backtest_mining_trials"]
        self.candidates = db["backtest_candidate_strategies"]

    async def ensure_indexes(self) -> None:
        await self.runs.create_index([("run_id", 1)], unique=True, background=True)
        await self.trials.create_index([("run_id", 1), ("rank", 1)], background=True)
        await self.trials.create_index([("run_id", 1), ("accepted", 1), ("score", -1)], background=True)
        await self.candidates.create_index([("candidate_id", 1)], unique=True, background=True)
        await self.candidates.create_index([("run_id", 1), ("score", -1)], background=True)
        await self.candidates.create_index([("user_id", 1), ("created_at", -1)], background=True)

    async def list_candidates(self, user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        await self.ensure_indexes()
        return await self.candidates.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(None)

    async def save_candidate(self, payload: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        await self.ensure_indexes()
        now = datetime.utcnow()
        doc = {
            "candidate_id": uuid.uuid4().hex,
            "user_id": user_id,
            "name": payload.get("name") or payload["strategy_id"],
            "strategy_id": payload["strategy_id"],
            "params": payload.get("params") or {},
            "score": payload.get("score"),
            "metrics": payload.get("metrics") or {},
            "evaluation": payload.get("evaluation") or {},
            "run_id": payload.get("run_id"),
            "source_run_id": payload.get("run_id"),
            "source_trial_index": payload.get("trial_index"),
            "created_at": now,
            "updated_at": now,
        }
        await self.candidates.insert_one(doc)
        doc.pop("_id", None)
        return doc

    async def start(self, payload: Dict[str, Any], user_id: str) -> str:
        await self.ensure_indexes()
        payload = self._prepare_payload(payload)
        run_id = uuid.uuid4().hex
        now = datetime.utcnow()
        doc = {
            "run_id": run_id,
            "user_id": user_id,
            "status": "pending",
            "progress": 0,
            "message": "queued",
            "payload": payload,
            "mode": payload.get("mode", "custom"),
            "policy": self._policy_summary(payload),
            "created_at": now,
            "updated_at": now,
        }
        await self.runs.insert_one(doc)
        asyncio.create_task(self._run(run_id, payload, user_id))
        return run_id

    def _prepare_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        prepared = dict(payload)
        if prepared.get("mode") != "auto_robust":
            return prepared

        prepared["templates"] = [item for item in AUTO_ROBUST_TEMPLATES if item in STRATEGIES]
        prepared["search_method"] = "random"
        prepared["search_space"] = {key: list(values) for key, values in AUTO_ROBUST_SEARCH_SPACE.items()}
        prepared["max_trials"] = min(300, max(120, int(prepared.get("max_trials") or 0)))
        prepared["walk_forward"] = True
        prepared["walk_forward_train_days"] = 504
        prepared["walk_forward_validation_days"] = 126
        prepared["walk_forward_test_days"] = 126
        prepared["walk_forward_step_days"] = 126
        prepared["max_walk_forward_slices"] = max(5, int(prepared.get("max_walk_forward_slices") or 0))
        prepared["objective"] = "robust_walk_forward_calmar"
        prepared["constraints"] = dict(AUTO_ROBUST_CONSTRAINTS)
        prepared["profile"] = {
            "id": "auto_robust",
            "name": "稳健自动挖掘",
            "method": "模板池随机采样 + 训练/验证/样本外切分 + walk-forward + 2 倍成本压力测试",
        }
        return prepared

    async def get(self, run_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        await self.ensure_indexes()
        run = await self.runs.find_one({"run_id": run_id, "user_id": user_id}, {"_id": 0})
        if not run:
            return None
        trials = await self.trials.find({"run_id": run_id}, {"_id": 0}).sort("rank", 1).limit(100).to_list(None)
        candidates = await self.candidates.find({"run_id": run_id}, {"_id": 0}).sort("score", -1).to_list(None)
        run["trials"] = trials
        run["candidates"] = candidates
        return run

    async def _run(self, run_id: str, payload: Dict[str, Any], user_id: str) -> None:
        try:
            await self._update(run_id, "running", 5, "loading ETF data")
            start_date = payload["start_date"]
            end_date = payload["end_date"]
            universe = payload.get("universe") or [item["code"] for item in DEFAULT_ROTATION_UNIVERSE]
            adjust = payload.get("adjust", "qfq")
            records_by_code, warnings = await self.backtest.etf_data.get_history_map(
                universe,
                self.backtest.warmup_start_date(start_date),
                end_date,
                adjust=adjust,
            )
            split_plan = self._split_plan(records_by_code, start_date, end_date, payload)
            if not split_plan:
                raise ValueError("Not enough data to create train/validation/test splits")

            templates = [item for item in payload.get("templates", DEFAULT_TEMPLATES) if item in STRATEGIES]
            trials = self._generate_trials(
                templates=templates,
                search_space=payload.get("search_space") or DEFAULT_SEARCH_SPACE,
                search_method=payload.get("search_method", "random"),
                max_trials=int(payload.get("max_trials", 40)),
                seed=int(payload.get("seed", 7)),
            )
            if not trials:
                raise ValueError("No mining trials generated")

            results = []
            for index, trial in enumerate(trials, 1):
                trial_result = await self._evaluate_trial(
                    run_id=run_id,
                    trial_index=index,
                    trial=trial,
                    payload=payload,
                    records_by_code=records_by_code,
                    split_plan=split_plan,
                )
                results.append(trial_result)
                progress = 10 + int(80 * index / len(trials))
                await self._update(run_id, "running", progress, f"evaluated {index}/{len(trials)} trials")

            ranked = sorted(results, key=lambda item: item["score"], reverse=True)
            await self.trials.delete_many({"run_id": run_id})
            if ranked:
                docs = []
                for rank, item in enumerate(ranked, 1):
                    doc = dict(item)
                    doc["rank"] = rank
                    docs.append(doc)
                await self.trials.insert_many(docs)

            accepted = [item for item in ranked if item["accepted"]][:20]
            if accepted:
                docs = []
                for item in accepted:
                    docs.append(
                        {
                            "candidate_id": uuid.uuid4().hex,
                            "run_id": run_id,
                            "user_id": user_id,
                            "strategy_id": item["strategy_id"],
                            "params": item["params"],
                            "score": item["score"],
                            "metrics": item["test_metrics"],
                            "evaluation": {
                                "train_metrics": item["train_metrics"],
                                "validation_metrics": item["validation_metrics"],
                                "test_metrics": item["test_metrics"],
                                "walk_forward_summary": item.get("walk_forward_summary") or {},
                                "stress_2x_metrics": item["stress_2x_metrics"],
                                "reasons": item["reasons"],
                                "explanation": item.get("explanation") or {},
                            },
                            "created_at": datetime.utcnow(),
                        }
                    )
                await self.candidates.insert_many(docs)

            await self.runs.update_one(
                {"run_id": run_id},
                {
                    "$set": {
                        "status": "completed",
                        "progress": 100,
                        "message": "completed",
                        "trial_count": len(ranked),
                        "candidate_count": len(accepted),
                        "data_warnings": warnings,
                        "split_plan": self._split_plan_summary(split_plan),
                        "mode": payload.get("mode", "custom"),
                        "policy": self._policy_summary(payload),
                        "updated_at": datetime.utcnow(),
                    }
                },
            )
        except Exception as exc:
            await self.runs.update_one(
                {"run_id": run_id},
                {
                    "$set": {
                        "status": "failed",
                        "progress": 100,
                        "message": str(exc),
                        "updated_at": datetime.utcnow(),
                    }
                },
            )

    async def _evaluate_trial(
        self,
        run_id: str,
        trial_index: int,
        trial: Dict[str, Any],
        payload: Dict[str, Any],
        records_by_code: Dict[str, List[Dict[str, Any]]],
        split_plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        common = {
            "universe": payload.get("universe") or [item["code"] for item in DEFAULT_ROTATION_UNIVERSE],
            "initial_cash": float(payload.get("initial_cash", 1_000_000.0)),
            "commission_bps": float(payload.get("commission_bps", 5.0)),
            "slippage_bps": float(payload.get("slippage_bps", 5.0)),
            "adjust": payload.get("adjust", "qfq"),
        }
        metrics_by_split: Dict[str, Dict[str, Any]] = {}
        splits = split_plan["holdout"]
        for split_name, split in splits.items():
            result = await self.backtest.run_backtest(
                strategy_id=trial["strategy_id"],
                start_date=split["start_date"],
                end_date=split["end_date"],
                universe=common["universe"],
                initial_cash=common["initial_cash"],
                commission_bps=common["commission_bps"],
                slippage_bps=common["slippage_bps"],
                adjust=common["adjust"],
                params=trial["params"],
                records_by_code=records_by_code,
            )
            metrics_by_split[split_name] = self._with_benchmark_metrics(
                result["metrics"],
                result.get("diagnostics") or {},
            )

        walk_forward_slices: List[Dict[str, Any]] = []
        for fold in split_plan.get("walk_forward", []):
            result = await self.backtest.run_backtest(
                strategy_id=trial["strategy_id"],
                start_date=fold["test"]["start_date"],
                end_date=fold["test"]["end_date"],
                universe=common["universe"],
                initial_cash=common["initial_cash"],
                commission_bps=common["commission_bps"],
                slippage_bps=common["slippage_bps"],
                adjust=common["adjust"],
                params=trial["params"],
                records_by_code=records_by_code,
            )
            walk_forward_slices.append(
                {
                    "label": fold["label"],
                    "train": fold["train"],
                    "validation": fold["validation"],
                    "test": fold["test"],
                    "metrics": self._with_benchmark_metrics(
                        result["metrics"],
                        result.get("diagnostics") or {},
                    ),
                }
            )
        walk_forward_summary = self._walk_forward_summary(walk_forward_slices)

        stress = await self.backtest.run_backtest(
            strategy_id=trial["strategy_id"],
            start_date=splits["test"]["start_date"],
            end_date=splits["test"]["end_date"],
            universe=common["universe"],
            initial_cash=common["initial_cash"],
            commission_bps=common["commission_bps"] * 2,
            slippage_bps=common["slippage_bps"] * 2,
            adjust=common["adjust"],
            params=trial["params"],
            records_by_code=records_by_code,
        )
        stress_metrics = self._with_benchmark_metrics(stress["metrics"], stress.get("diagnostics") or {})
        accepted, reasons = self._accepted(metrics_by_split, stress_metrics, walk_forward_summary, payload)
        score_components = self._score_components(metrics_by_split, stress_metrics, walk_forward_summary)
        score = self._score(metrics_by_split, stress_metrics, walk_forward_summary)
        explanation = self._explain_trial(
            accepted,
            metrics_by_split,
            stress_metrics,
            walk_forward_summary,
            score_components,
            payload,
        )
        return {
            "run_id": run_id,
            "trial_index": trial_index,
            "strategy_id": trial["strategy_id"],
            "params": trial["params"],
            "score": round(float(score), 6),
            "accepted": accepted,
            "reasons": reasons,
            "train_metrics": metrics_by_split["train"],
            "validation_metrics": metrics_by_split["validation"],
            "test_metrics": metrics_by_split["test"],
            "stress_2x_metrics": stress_metrics,
            "walk_forward_slices": walk_forward_slices,
            "walk_forward_summary": walk_forward_summary,
            "explanation": explanation,
            "created_at": datetime.utcnow(),
        }

    def _generate_trials(
        self,
        templates: List[str],
        search_space: Dict[str, List[Any]],
        search_method: str,
        max_trials: int,
        seed: int,
    ) -> List[Dict[str, Any]]:
        random_gen = random.Random(seed)
        templates = [template for template in templates if template in STRATEGIES]
        if not templates:
            return []
        max_trials = max(1, max_trials)
        if search_method == "grid":
            return self._generate_grid_trials(templates, search_space, max_trials, random_gen)

        trials: List[Dict[str, Any]] = []
        seen: set[str] = set()
        max_attempts = max_trials * 30
        for _ in range(max_attempts):
            if len(trials) >= max_trials:
                break
            template = random_gen.choice(templates)
            keys = self._search_keys_for_template(template, search_space)
            combo = {key: random_gen.choice(search_space[key]) for key in keys}
            trial = {"strategy_id": template, "params": self._params_for_template(template, combo)}
            fingerprint = self._trial_fingerprint(trial)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            trials.append(trial)
        return trials

    def _generate_grid_trials(
        self,
        templates: List[str],
        search_space: Dict[str, List[Any]],
        max_trials: int,
        random_gen: random.Random,
    ) -> List[Dict[str, Any]]:
        trials: List[Dict[str, Any]] = []
        seen: set[str] = set()
        quota = max(1, max_trials // len(templates))
        for template in templates:
            keys = self._search_keys_for_template(template, search_space)
            values = [search_space[key] for key in keys]
            total = 1
            for options in values:
                total *= len(options)
            sample_count = min(quota, total)
            indexes = self._grid_indexes(total, sample_count)
            for index in indexes:
                combo = self._combo_at_index(keys, values, index)
                trial = {"strategy_id": template, "params": self._params_for_template(template, combo)}
                fingerprint = self._trial_fingerprint(trial)
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                trials.append(trial)

        attempts = 0
        while len(trials) < max_trials and attempts < max_trials * 30:
            attempts += 1
            template = random_gen.choice(templates)
            keys = self._search_keys_for_template(template, search_space)
            values = [search_space[key] for key in keys]
            total = 1
            for options in values:
                total *= len(options)
            combo = self._combo_at_index(keys, values, random_gen.randrange(total))
            trial = {"strategy_id": template, "params": self._params_for_template(template, combo)}
            fingerprint = self._trial_fingerprint(trial)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            trials.append(trial)
        return trials[:max_trials]

    def _search_keys_for_template(self, template: str, search_space: Dict[str, List[Any]]) -> List[str]:
        keys = TEMPLATE_SEARCH_KEYS.get(template, list(search_space.keys()))
        return [key for key in keys if search_space.get(key)]

    @staticmethod
    def _grid_indexes(total: int, sample_count: int) -> List[int]:
        if sample_count <= 0:
            return []
        if sample_count >= total:
            return list(range(total))
        if sample_count == 1:
            return [0]
        step = (total - 1) / (sample_count - 1)
        return sorted({min(total - 1, round(index * step)) for index in range(sample_count)})

    @staticmethod
    def _combo_at_index(keys: List[str], values: List[List[Any]], index: int) -> Dict[str, Any]:
        combo: Dict[str, Any] = {}
        for key, options in reversed(list(zip(keys, values))):
            option_index = index % len(options)
            combo[key] = options[option_index]
            index //= len(options)
        return combo

    @staticmethod
    def _trial_fingerprint(trial: Dict[str, Any]) -> str:
        return json.dumps(trial, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def _params_for_template(self, template: str, combo: Dict[str, Any]) -> Dict[str, Any]:
        params = {
            "rebalance_frequency": combo.get("rebalance_frequency", "weekly"),
            "top_k": int(combo.get("top_k", 2)),
            "empty_threshold": combo.get("empty_threshold", "ret_gt_0"),
            "cash_entry_mode": combo.get("cash_entry_mode", "daily_when_cash"),
            "cash_entry_confirmations": int(combo.get("cash_entry_confirmations", 2)),
            "min_days_to_rebalance_for_cash_entry": int(combo.get("min_days_to_rebalance_for_cash_entry", 2)),
        }
        is_biweekly_stable = template == "biweekly_adaptive_stable_rotation"
        window = int(combo.get("momentum_window", 60))
        trend_fast_default = 10 if template == "biweekly_adaptive_stable_rotation" else 20
        trend_fast_ma = int(combo.get("trend_fast_ma", trend_fast_default))
        trend_ma = int(combo.get("trend_ma", 60 if is_biweekly_stable else 120))
        vol_window = int(combo.get("vol_window", 20 if is_biweekly_stable else 60))
        absolute_window = int(combo.get("absolute_window", 20 if is_biweekly_stable else min(window, 120)))
        params["momentum_window"] = window
        params["trend_fast_ma"] = trend_fast_ma
        params["trend_ma"] = trend_ma
        params["vol_window"] = vol_window
        params["absolute_window"] = absolute_window
        if template == "industry_momentum_enhanced":
            middle_window = max(20, min(window, 120))
            params["momentum_windows"] = sorted({20, middle_window, max(window, 120)})
            params["momentum_weights"] = self._momentum_weights(len(params["momentum_windows"]))
            params["vol_penalty"] = 0.03
            params["adaptive_top_k"] = bool(combo.get("adaptive_top_k", False))
            params["top_k_score_gap"] = float(combo.get("top_k_score_gap", 0.05))
            if params["adaptive_top_k"]:
                params["top_k"] = max(2, int(params.get("top_k", 1)))
        elif template == "vol_adjusted_momentum":
            params["fast_window"] = min(window, 60)
            params["slow_window"] = max(window, 120)
            params["fast_vol_window"] = vol_window
            params["slow_vol_window"] = max(vol_window, 120)
            params["max_weight"] = 0.45
        elif template == "dual_momentum_core":
            params["momentum_window"] = window
        elif template == "trend_following_equal_weight":
            params["fast_ma"] = max(5, min(trend_fast_ma or 20, trend_ma))
            params["slow_ma"] = trend_ma
            params["score_window"] = window
        elif template == "ema_momentum_rotation":
            fast_ema = int(combo.get("fast_ema", 30))
            slow_ema = int(combo.get("slow_ema", 50))
            if slow_ema <= fast_ema:
                slow_ema = fast_ema + 20
            params.update(
                {
                    "fast_ema": fast_ema,
                    "slow_ema": slow_ema,
                    "momentum_window": window,
                    "vol_window": vol_window,
                    "trend_weight": float(combo.get("trend_weight", 0.5)),
                    "vol_penalty": float(combo.get("vol_penalty", 0.02)),
                    "min_momentum": float(combo.get("min_momentum", 0.0)),
                }
            )
        elif template == "price_action_breakout_rotation":
            params.update(
                {
                    "lookback": int(combo.get("lookback", max(40, window))),
                    "momentum_window": min(window, 120),
                    "higher_low_window": int(combo.get("higher_low_window", 10)),
                    "breakout_buffer": float(combo.get("breakout_buffer", 0.99)),
                    "require_higher_low": bool(combo.get("require_higher_low", True)),
                    "breakout_weight": 1.5,
                    "range_weight": 0.05,
                    "vol_window": vol_window,
                    "vol_penalty": float(combo.get("vol_penalty", 0.02)),
                    "min_momentum": float(combo.get("min_momentum", 0.0)),
                }
            )
        elif template == "fibonacci_retracement_rotation":
            fib_low = float(combo.get("fib_low", 0.382))
            fib_high = float(combo.get("fib_high", 0.618))
            if fib_high <= fib_low:
                fib_high = min(0.95, fib_low + 0.236)
            params.update(
                {
                    "lookback": int(combo.get("lookback", max(60, window))),
                    "fib_low": fib_low,
                    "fib_high": fib_high,
                    "zone_tolerance": float(combo.get("zone_tolerance", 0.02)),
                    "bounce_days": int(combo.get("bounce_days", 3)),
                    "bounce_threshold": float(combo.get("bounce_threshold", 0.0)),
                    "min_leg_return": float(combo.get("min_leg_return", 0.10)),
                    "trend_ema": int(combo.get("trend_ema", 60)),
                    "vol_window": vol_window,
                    "bounce_weight": 2.0,
                    "fib_distance_penalty": 0.25,
                    "vol_penalty": float(combo.get("vol_penalty", 0.02)),
                }
            )
        elif template in {"adaptive_regime_rotation", "biweekly_adaptive_stable_rotation"}:
            if is_biweekly_stable:
                params["rebalance_frequency"] = "biweekly"
                params["top_k"] = int(combo.get("top_k_uptrend", 2))
                params["momentum_windows"] = [20, 60, 120]
                params["momentum_weights"] = [0.25, 0.45, 0.3]
                params["absolute_window"] = min(max(20, absolute_window), 60)
                params["trend_fast_ma"] = min(max(10, trend_fast_ma), 20)
                params["trend_ma"] = min(max(60, trend_ma), 120)
                params["vol_window"] = min(max(20, vol_window), 60)
                params["min_holding_days"] = int(combo.get("min_holding_days", 20))
                params["rank_switch_buffer"] = int(combo.get("rank_switch_buffer", 2))
                params["rebalance_turnover_threshold"] = float(combo.get("rebalance_turnover_threshold", 0.18))
            else:
                params["top_k"] = int(combo.get("top_k_uptrend", combo.get("top_k", 1)))
                params["momentum_windows"] = [40, max(60, window), 250]
                params["momentum_weights"] = [0.3, 0.5, 0.2]
            params.update(
                {
                    "top_k_uptrend": int(combo.get("top_k_uptrend", 2 if is_biweekly_stable else 1)),
                    "top_k_range": int(combo.get("top_k_range", 2)),
                    "top_k_downtrend": int(combo.get("top_k_downtrend", 1)),
                    "vol_penalty": 0.04 if is_biweekly_stable else 0.03,
                    "regime_fast_ma": (
                        min(max(10, int(combo.get("regime_fast_ma", 10))), 20)
                        if is_biweekly_stable
                        else int(combo.get("regime_fast_ma", 20))
                    ),
                    "regime_slow_ma": int(combo.get("regime_slow_ma", 120)),
                    "regime_momentum_window": int(combo.get("regime_momentum_window", 60 if is_biweekly_stable else 60)),
                    "regime_up_threshold": 0.015 if is_biweekly_stable else 0.02,
                    "regime_down_threshold": -0.025 if is_biweekly_stable else -0.03,
                    "range_window": max(20, min(window, 60)) if is_biweekly_stable else min(window, 60),
                    "range_ma": min(trend_ma, 60 if is_biweekly_stable else 120),
                    "range_vol_window": max(20, min(vol_window, 60)) if is_biweekly_stable else min(vol_window, 60),
                    "range_vol_penalty": 0.02,
                    "defensive_window": min(max(window, 60), 120),
                    "defensive_ma": 120 if is_biweekly_stable else max(60, min(trend_ma, 200)),
                }
            )
        elif template == "donchian_breakout_rotation":
            params["lookback"] = max(40, window)
            params["momentum_window"] = min(20, window)
            params["breakout_buffer"] = 0.98
        elif template == "rsrs_timing_rotation":
            params["momentum_window"] = window
            params["rsrs_window"] = 18
            params["z_window"] = max(80, trend_ma)
            params["z_threshold"] = 0.7
        elif template == "chan_fractal_rotation":
            params["lookback"] = max(40, window)
            params["ma"] = max(10, min(trend_ma, 60))
        elif template == "chan_center_breakout":
            params["segment"] = max(10, min(window, 60))
        return params

    @staticmethod
    def _momentum_weights(count: int) -> List[float]:
        if count == 1:
            return [1.0]
        if count == 2:
            return [0.4, 0.6]
        return [0.3, 0.5, 0.2]

    def _split_plan(
        self,
        records_by_code: Dict[str, List[Dict[str, Any]]],
        start_date: str,
        end_date: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        dates = sorted(
            {
                row["trade_date"]
                for rows in records_by_code.values()
                for row in rows
                if start_date <= row.get("trade_date", "") <= end_date
            }
        )
        if len(dates) < 180:
            return {}
        holdout = self._holdout_splits(dates)
        walk_forward = self._walk_forward_splits(dates, payload) if payload.get("walk_forward", True) else []
        return {"holdout": holdout, "walk_forward": walk_forward}

    def _holdout_splits(self, dates: List[str]) -> Dict[str, Dict[str, str]]:
        train_end = int(len(dates) * 0.6)
        validation_end = int(len(dates) * 0.8)
        return {
            "train": {"start_date": dates[0], "end_date": dates[train_end - 1]},
            "validation": {"start_date": dates[train_end], "end_date": dates[validation_end - 1]},
            "test": {"start_date": dates[validation_end], "end_date": dates[-1]},
        }

    def _splits(
        self,
        records_by_code: Dict[str, List[Dict[str, Any]]],
        start_date: str,
        end_date: str,
    ) -> Dict[str, Dict[str, str]]:
        plan = self._split_plan(records_by_code, start_date, end_date, {"walk_forward": False})
        return plan.get("holdout", {}) if plan else {}

    def _walk_forward_splits(self, dates: List[str], payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        max_slices = int(payload.get("max_walk_forward_slices", 4))
        if max_slices <= 0:
            return []
        train_days = int(payload.get("walk_forward_train_days", 504))
        validation_days = int(payload.get("walk_forward_validation_days", 126))
        test_days = int(payload.get("walk_forward_test_days", 126))
        total_required = train_days + validation_days + test_days
        if len(dates) < total_required:
            train_days = max(90, int(len(dates) * 0.5))
            validation_days = max(45, int(len(dates) * 0.15))
            test_days = max(45, int(len(dates) * 0.15))
            total_required = train_days + validation_days + test_days
        if len(dates) < total_required:
            return []

        step = max(test_days, int(payload.get("walk_forward_step_days", test_days)))
        folds: List[Dict[str, Any]] = []
        start = 0
        while start + total_required <= len(dates) and len(folds) < max_slices:
            train_start = start
            train_end = train_start + train_days
            validation_end = train_end + validation_days
            test_end = validation_end + test_days
            folds.append(
                {
                    "label": f"WF{len(folds) + 1}",
                    "train": {"start_date": dates[train_start], "end_date": dates[train_end - 1]},
                    "validation": {"start_date": dates[train_end], "end_date": dates[validation_end - 1]},
                    "test": {"start_date": dates[validation_end], "end_date": dates[test_end - 1]},
                }
            )
            start += step
        return folds

    @staticmethod
    def _split_plan_summary(split_plan: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "holdout": split_plan.get("holdout") or {},
            "walk_forward": [
                {
                    "label": fold["label"],
                    "train": fold["train"],
                    "validation": fold["validation"],
                    "test": fold["test"],
                }
                for fold in split_plan.get("walk_forward", [])
            ],
        }

    def _walk_forward_summary(self, slices: List[Dict[str, Any]]) -> Dict[str, Any]:
        metrics = [item.get("metrics") or {} for item in slices]
        if not metrics:
            return {"sample_count": 0}

        def values(key: str) -> List[float]:
            return [float(item[key]) for item in metrics if item.get(key) is not None]

        def rounded(value: float) -> float:
            return round(float(value), 6)

        returns = values("total_return")
        excess_returns = values("excess_return")
        calmars = values("calmar")
        sharpes = values("sharpe")
        drawdowns = values("max_drawdown")
        trades = values("trade_count")
        summary: Dict[str, Any] = {
            "sample_count": len(metrics),
            "positive_ratio": rounded(sum(1 for value in returns if value > 0) / len(returns)) if returns else 0.0,
            "beat_benchmark_ratio": (
                rounded(sum(1 for value in excess_returns if value > 0) / len(excess_returns))
                if excess_returns
                else 0.0
            ),
        }
        for key, source in (
            ("total_return", returns),
            ("excess_return", excess_returns),
            ("calmar", calmars),
            ("sharpe", sharpes),
        ):
            if source:
                summary[f"{key}_mean"] = rounded(sum(source) / len(source))
                summary[f"{key}_median"] = rounded(median(source))
                summary[f"{key}_std"] = rounded(pstdev(source)) if len(source) > 1 else 0.0
                summary[f"{key}_min"] = rounded(min(source))
        if drawdowns:
            summary["max_drawdown_worst"] = rounded(min(drawdowns))
            summary["max_drawdown_median"] = rounded(median(drawdowns))
        if trades:
            summary["trade_count_total"] = int(sum(trades))
            summary["trade_count_min"] = int(min(trades))
        return summary

    def _acceptance_checks(
        self,
        metrics: Dict[str, Dict[str, Any]],
        stress_metrics: Dict[str, Any],
        walk_forward_summary: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        constraints = payload.get("constraints") or {}
        max_drawdown = float(constraints.get("max_drawdown", 0.35))
        min_trades = int(constraints.get("min_trades", 4))
        min_walk_forward_positive_ratio = float(constraints.get("min_walk_forward_positive_ratio", 0.5))
        min_walk_forward_beat_ratio = float(constraints.get("min_walk_forward_beat_benchmark_ratio", 0.4))
        min_walk_forward_sample_count = int(constraints.get("min_walk_forward_sample_count", 0))
        min_validation_return = constraints.get("min_validation_return")
        min_test_calmar = constraints.get("min_test_calmar")
        max_calmar_gap = constraints.get("max_calmar_gap")
        test = metrics["test"]
        validation = metrics["validation"]
        positive_slices = sum(1 for item in metrics.values() if item.get("total_return", 0) > 0)
        checks = [
            {
                "key": "test_return_positive",
                "label": "样本外收益为正",
                "passed": test.get("total_return", 0) > 0,
                "value": self._round_metric(test.get("total_return")),
                "threshold": "> 0",
                "failure": "test_return_not_positive",
            },
            {
                "key": "test_excess_positive",
                "label": "样本外跑赢基准",
                "passed": test.get("excess_return", test.get("total_return", 0)) > 0,
                "value": self._round_metric(test.get("excess_return", test.get("total_return"))),
                "threshold": "> 0",
                "failure": "test_excess_not_positive",
            },
            {
                "key": "drawdown_limit",
                "label": "样本外最大回撤可控",
                "passed": abs(test.get("max_drawdown", 0)) <= max_drawdown,
                "value": self._round_metric(test.get("max_drawdown")),
                "threshold": f"abs <= {max_drawdown:.2f}",
                "failure": "drawdown_too_high",
            },
            {
                "key": "trade_count",
                "label": "交易次数足够",
                "passed": test.get("trade_count", 0) >= min_trades,
                "value": int(test.get("trade_count", 0)),
                "threshold": f">= {min_trades}",
                "failure": "too_few_trades",
            },
            {
                "key": "split_concentration",
                "label": "训练/验证/样本外不集中",
                "passed": positive_slices >= 2,
                "value": positive_slices,
                "threshold": ">= 2 段正收益",
                "failure": "performance_too_concentrated",
            },
            {
                "key": "cost_stress",
                "label": "2 倍成本压力测试为正",
                "passed": stress_metrics.get("total_return", 0) > 0,
                "value": self._round_metric(stress_metrics.get("total_return")),
                "threshold": "> 0",
                "failure": "failed_2x_cost_stress",
            },
        ]

        if min_validation_return is not None:
            min_value = float(min_validation_return)
            checks.append(
                {
                    "key": "validation_return",
                    "label": "验证集收益为正",
                    "passed": validation.get("total_return", 0) > min_value,
                    "value": self._round_metric(validation.get("total_return")),
                    "threshold": f"> {min_value:.2f}",
                    "failure": "validation_return_below_threshold",
                }
            )
        if min_test_calmar is not None:
            min_value = float(min_test_calmar)
            checks.append(
                {
                    "key": "test_calmar",
                    "label": "样本外 Calmar 达标",
                    "passed": test.get("calmar", 0) > min_value,
                    "value": self._round_metric(test.get("calmar")),
                    "threshold": f"> {min_value:.2f}",
                    "failure": "test_calmar_below_threshold",
                }
            )
        if max_calmar_gap is not None:
            max_value = float(max_calmar_gap)
            calmar_gap = abs(float(test.get("calmar", 0)) - float(validation.get("calmar", 0)))
            checks.append(
                {
                    "key": "calmar_gap",
                    "label": "验证/样本外 Calmar 差距不过大",
                    "passed": calmar_gap <= max_value,
                    "value": self._round_metric(calmar_gap),
                    "threshold": f"<= {max_value:.2f}",
                    "failure": "calmar_gap_too_large",
                }
            )
        if min_walk_forward_sample_count > 0:
            checks.append(
                {
                    "key": "walk_forward_sample_count",
                    "label": "walk-forward 样本数足够",
                    "passed": walk_forward_summary.get("sample_count", 0) >= min_walk_forward_sample_count,
                    "value": int(walk_forward_summary.get("sample_count", 0)),
                    "threshold": f">= {min_walk_forward_sample_count}",
                    "failure": "walk_forward_too_few_slices",
                }
            )
        if walk_forward_summary.get("sample_count", 0) >= 2:
            checks.extend(
                [
                    {
                        "key": "walk_forward_positive_ratio",
                        "label": "walk-forward 正收益占比达标",
                        "passed": walk_forward_summary.get("positive_ratio", 0) >= min_walk_forward_positive_ratio,
                        "value": self._round_metric(walk_forward_summary.get("positive_ratio")),
                        "threshold": f">= {min_walk_forward_positive_ratio:.2f}",
                        "failure": "walk_forward_return_unstable",
                    },
                    {
                        "key": "walk_forward_beat_ratio",
                        "label": "walk-forward 跑赢基准占比达标",
                        "passed": walk_forward_summary.get("beat_benchmark_ratio", 0) >= min_walk_forward_beat_ratio,
                        "value": self._round_metric(walk_forward_summary.get("beat_benchmark_ratio")),
                        "threshold": f">= {min_walk_forward_beat_ratio:.2f}",
                        "failure": "walk_forward_excess_unstable",
                    },
                ]
            )
        return checks

    def _accepted(
        self,
        metrics: Dict[str, Dict[str, Any]],
        stress_metrics: Dict[str, Any],
        walk_forward_summary: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> tuple[bool, List[str]]:
        checks = self._acceptance_checks(metrics, stress_metrics, walk_forward_summary, payload)
        reasons = [item["failure"] for item in checks if not item["passed"]]
        return not reasons, reasons

    def _score_components(
        self,
        metrics: Dict[str, Dict[str, Any]],
        stress_metrics: Dict[str, Any],
        walk_forward_summary: Dict[str, Any],
    ) -> Dict[str, Dict[str, float]]:
        test = metrics["test"]
        validation = metrics["validation"]
        penalty = abs(test.get("max_drawdown", 0)) * 0.5
        turnover_penalty = test.get("avg_turnover", 0) * 0.1
        stability = abs(test.get("calmar", 0) - validation.get("calmar", 0)) * 0.1
        stress_bonus = max(0.0, stress_metrics.get("total_return", 0)) * 0.2
        excess_bonus = max(0.0, test.get("excess_return", 0)) * 0.5
        validation_excess_bonus = max(0.0, validation.get("excess_return", 0)) * 0.2
        walk_forward_bonus = (
            0.4 * walk_forward_summary.get("calmar_median", 0)
            + 0.25 * max(0.0, walk_forward_summary.get("excess_return_median", 0))
            + 0.15 * walk_forward_summary.get("positive_ratio", 0)
            + 0.15 * walk_forward_summary.get("beat_benchmark_ratio", 0)
        )
        walk_forward_penalty = (
            0.08 * walk_forward_summary.get("calmar_std", 0)
            + 0.5 * max(0.0, 0.5 - walk_forward_summary.get("positive_ratio", 0))
            + 0.5 * max(0.0, 0.4 - walk_forward_summary.get("beat_benchmark_ratio", 0))
        )
        return {
            "positive": {
                "test_calmar": self._round_metric(test.get("calmar", 0)),
                "validation_calmar": self._round_metric(0.3 * validation.get("calmar", 0)),
                "test_excess_return": self._round_metric(excess_bonus),
                "validation_excess_return": self._round_metric(validation_excess_bonus),
                "stress_return": self._round_metric(stress_bonus),
                "walk_forward": self._round_metric(walk_forward_bonus),
            },
            "penalty": {
                "drawdown": self._round_metric(-penalty),
                "turnover": self._round_metric(-turnover_penalty),
                "calmar_gap": self._round_metric(-stability),
                "walk_forward_instability": self._round_metric(-walk_forward_penalty),
            },
        }

    def _score(
        self,
        metrics: Dict[str, Dict[str, Any]],
        stress_metrics: Dict[str, Any],
        walk_forward_summary: Dict[str, Any],
    ) -> float:
        components = self._score_components(metrics, stress_metrics, walk_forward_summary)
        return sum(components["positive"].values()) + sum(components["penalty"].values())

    def _explain_trial(
        self,
        accepted: bool,
        metrics: Dict[str, Dict[str, Any]],
        stress_metrics: Dict[str, Any],
        walk_forward_summary: Dict[str, Any],
        score_components: Dict[str, Dict[str, float]],
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        checks = self._acceptance_checks(metrics, stress_metrics, walk_forward_summary, payload)
        return {
            "method": payload.get("profile", {}).get(
                "method",
                "训练/验证/样本外切分 + walk-forward + 2 倍成本压力测试",
            ),
            "decision": "accepted" if accepted else "rejected",
            "passed_checks": [item for item in checks if item["passed"]],
            "failed_checks": [item for item in checks if not item["passed"]],
            "score_components": score_components,
            "robustness": {
                "validation_return": self._round_metric(metrics["validation"].get("total_return")),
                "test_return": self._round_metric(metrics["test"].get("total_return")),
                "test_excess_return": self._round_metric(metrics["test"].get("excess_return")),
                "test_max_drawdown": self._round_metric(metrics["test"].get("max_drawdown")),
                "stress_2x_return": self._round_metric(stress_metrics.get("total_return")),
                "walk_forward_sample_count": int(walk_forward_summary.get("sample_count", 0)),
                "walk_forward_positive_ratio": self._round_metric(walk_forward_summary.get("positive_ratio")),
                "walk_forward_beat_benchmark_ratio": self._round_metric(
                    walk_forward_summary.get("beat_benchmark_ratio")
                ),
            },
        }

    @staticmethod
    def _round_metric(value: Any) -> float:
        if value is None:
            return 0.0
        return round(float(value), 6)

    @staticmethod
    def _policy_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
        constraints = payload.get("constraints") or {}
        return {
            "mode": payload.get("mode", "custom"),
            "profile": payload.get("profile") or {},
            "templates": payload.get("templates") or [],
            "search_method": payload.get("search_method", "random"),
            "max_trials": int(payload.get("max_trials", 40)),
            "walk_forward": {
                "enabled": bool(payload.get("walk_forward", True)),
                "train_days": int(payload.get("walk_forward_train_days", 504)),
                "validation_days": int(payload.get("walk_forward_validation_days", 126)),
                "test_days": int(payload.get("walk_forward_test_days", 126)),
                "max_slices": int(payload.get("max_walk_forward_slices", 4)),
            },
            "constraints": constraints,
        }

    def _with_benchmark_metrics(self, metrics: Dict[str, Any], diagnostics: Dict[str, Any]) -> Dict[str, Any]:
        enriched = dict(metrics)
        benchmark_return = diagnostics.get("benchmark_return")
        total_return = enriched.get("total_return")
        if benchmark_return is not None and total_return is not None:
            enriched["benchmark_return"] = round(float(benchmark_return), 6)
            enriched["excess_return"] = round(float(total_return) - float(benchmark_return), 6)
        return enriched

    async def _update(self, run_id: str, status: str, progress: int, message: str) -> None:
        await self.runs.update_one(
            {"run_id": run_id},
            {"$set": {"status": status, "progress": progress, "message": message, "updated_at": datetime.utcnow()}},
        )
