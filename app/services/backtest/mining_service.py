from __future__ import annotations

import asyncio
import itertools
import random
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase

from .backtest_service import BacktestService
from .engine import DEFAULT_ROTATION_UNIVERSE, STRATEGIES
from .strategy_catalog import STRATEGY_TEMPLATES


DEFAULT_SEARCH_SPACE: Dict[str, List[Any]] = {
    "momentum_window": [20, 40, 60, 120, 250],
    "absolute_window": [20, 40, 60, 120],
    "trend_fast_ma": [0, 20, 40, 60],
    "trend_ma": [20, 60, 120, 200],
    "vol_window": [20, 60, 120],
    "rebalance_frequency": ["weekly", "biweekly", "monthly"],
    "top_k": [1, 2, 3, 5],
    "empty_threshold": ["ret_gt_0", "score_gt_0", "trend_filter"],
    "cash_entry_mode": ["daily_when_cash", "rebalance_only"],
    "cash_entry_confirmations": [1, 2, 3],
    "min_days_to_rebalance_for_cash_entry": [0, 2, 5],
}


DEFAULT_TEMPLATES = list(STRATEGY_TEMPLATES.keys())


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
        await self.candidates.create_index([("candidate_id", 1)], unique=True, background=True)
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
        run_id = uuid.uuid4().hex
        now = datetime.utcnow()
        doc = {
            "run_id": run_id,
            "user_id": user_id,
            "status": "pending",
            "progress": 0,
            "message": "queued",
            "payload": payload,
            "created_at": now,
            "updated_at": now,
        }
        await self.runs.insert_one(doc)
        asyncio.create_task(self._run(run_id, payload, user_id))
        return run_id

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
            splits = self._splits(records_by_code, start_date, end_date)
            if not splits:
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
                    splits=splits,
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
        splits: Dict[str, Dict[str, str]],
    ) -> Dict[str, Any]:
        common = {
            "universe": payload.get("universe") or [item["code"] for item in DEFAULT_ROTATION_UNIVERSE],
            "initial_cash": float(payload.get("initial_cash", 1_000_000.0)),
            "commission_bps": float(payload.get("commission_bps", 5.0)),
            "slippage_bps": float(payload.get("slippage_bps", 5.0)),
            "adjust": payload.get("adjust", "qfq"),
        }
        metrics_by_split: Dict[str, Dict[str, Any]] = {}
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
        accepted, reasons = self._accepted(metrics_by_split, stress_metrics, payload)
        score = self._score(metrics_by_split, stress_metrics)
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
        keys = list(search_space.keys())
        values = [search_space[key] for key in keys]
        combos = [dict(zip(keys, combo)) for combo in itertools.product(*values)]
        if search_method == "grid":
            random_gen.shuffle(combos)
            combos = combos[:max_trials]
        else:
            combos = [random_gen.choice(combos) for _ in range(max_trials)]
        trials = []
        for combo in combos:
            template = random_gen.choice(templates)
            params = self._params_for_template(template, combo)
            trials.append({"strategy_id": template, "params": params})
        return trials

    def _params_for_template(self, template: str, combo: Dict[str, Any]) -> Dict[str, Any]:
        params = {
            "rebalance_frequency": combo.get("rebalance_frequency", "weekly"),
            "top_k": combo.get("top_k", 2),
            "empty_threshold": combo.get("empty_threshold", "ret_gt_0"),
            "cash_entry_mode": combo.get("cash_entry_mode", "daily_when_cash"),
        }
        window = int(combo.get("momentum_window", 60))
        params["momentum_window"] = window
        params["trend_ma"] = int(combo.get("trend_ma", 120))
        params["vol_window"] = int(combo.get("vol_window", 60))
        if template == "industry_momentum_enhanced":
            params["momentum_windows"] = [20, window, 120]
            params["momentum_weights"] = [0.3, 0.5, 0.2]
            params["absolute_window"] = min(window, 120)
        elif template == "vol_adjusted_momentum":
            params["fast_window"] = window
            params["slow_window"] = max(window, 120)
            params["fast_vol_window"] = int(combo.get("vol_window", 60))
            params["slow_vol_window"] = 120
        elif template == "trend_following_equal_weight":
            params["fast_ma"] = min(20, int(combo.get("trend_ma", 60)))
            params["slow_ma"] = int(combo.get("trend_ma", 60))
            params["score_window"] = window
        elif template == "donchian_breakout_rotation":
            params["lookback"] = max(40, window)
            params["momentum_window"] = min(20, window)
        elif template == "rsrs_timing_rotation":
            params["momentum_window"] = window
            params["z_threshold"] = 0.7
        return params

    def _splits(
        self,
        records_by_code: Dict[str, List[Dict[str, Any]]],
        start_date: str,
        end_date: str,
    ) -> Dict[str, Dict[str, str]]:
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
        train_end = int(len(dates) * 0.6)
        validation_end = int(len(dates) * 0.8)
        return {
            "train": {"start_date": dates[0], "end_date": dates[train_end - 1]},
            "validation": {"start_date": dates[train_end], "end_date": dates[validation_end - 1]},
            "test": {"start_date": dates[validation_end], "end_date": dates[-1]},
        }

    def _accepted(
        self,
        metrics: Dict[str, Dict[str, Any]],
        stress_metrics: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> tuple[bool, List[str]]:
        constraints = payload.get("constraints") or {}
        max_drawdown = float(constraints.get("max_drawdown", 0.35))
        min_trades = int(constraints.get("min_trades", 4))
        reasons = []
        test = metrics["test"]
        if test.get("total_return", 0) <= 0:
            reasons.append("test_return_not_positive")
        if test.get("excess_return", test.get("total_return", 0)) <= 0:
            reasons.append("test_excess_not_positive")
        if abs(test.get("max_drawdown", 0)) > max_drawdown:
            reasons.append("drawdown_too_high")
        if test.get("trade_count", 0) < min_trades:
            reasons.append("too_few_trades")
        positive_slices = sum(1 for item in metrics.values() if item.get("total_return", 0) > 0)
        if positive_slices < 2:
            reasons.append("performance_too_concentrated")
        if stress_metrics.get("total_return", 0) <= 0:
            reasons.append("failed_2x_cost_stress")
        return not reasons, reasons

    def _score(self, metrics: Dict[str, Dict[str, Any]], stress_metrics: Dict[str, Any]) -> float:
        test = metrics["test"]
        validation = metrics["validation"]
        penalty = abs(test.get("max_drawdown", 0)) * 0.5
        turnover_penalty = test.get("avg_turnover", 0) * 0.1
        stability = abs(test.get("calmar", 0) - validation.get("calmar", 0)) * 0.1
        stress_bonus = max(0.0, stress_metrics.get("total_return", 0)) * 0.2
        excess_bonus = max(0.0, test.get("excess_return", 0)) * 0.5
        validation_excess_bonus = max(0.0, validation.get("excess_return", 0)) * 0.2
        return (
            test.get("calmar", 0)
            + 0.3 * validation.get("calmar", 0)
            + excess_bonus
            + validation_excess_bonus
            + stress_bonus
            - penalty
            - turnover_penalty
            - stability
        )

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
