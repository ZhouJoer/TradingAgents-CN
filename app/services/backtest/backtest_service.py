from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median, pstdev
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from .engine import (
    BacktestConfig,
    BacktestEngine,
    DEFAULT_ROTATION_UNIVERSE,
)
from .etf_data_service import ETFDataService
from .etf_universe_service import ETFUniverseService
from .strategy_catalog import STRATEGY_DEFINITIONS


BACKTEST_WARMUP_CALENDAR_DAYS = 540


class BacktestService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.etf_data = ETFDataService(db)
        self.etf_universe_service = ETFUniverseService(db)
        self.engine = BacktestEngine()

    async def strategies(self) -> List[Dict[str, Any]]:
        return STRATEGY_DEFINITIONS

    async def etf_universe(self, user_id: Optional[str] = None, include_inactive: bool = False) -> List[Dict[str, Any]]:
        if user_id:
            return await self.etf_universe_service.list_universe(user_id, include_inactive=include_inactive)
        return await self.etf_data.get_universe()

    async def default_rotation_codes(self, user_id: Optional[str] = None) -> List[str]:
        if user_id:
            codes = await self.etf_universe_service.active_rotation_codes(user_id)
            if codes:
                return codes
        return [item["code"] for item in DEFAULT_ROTATION_UNIVERSE]

    async def run_backtest(
        self,
        strategy_id: str,
        start_date: str,
        end_date: str,
        universe: Optional[List[str]] = None,
        initial_cash: float = 1_000_000.0,
        commission_bps: float = 5.0,
        slippage_bps: float = 5.0,
        adjust: str = "qfq",
        params: Optional[Dict[str, Any]] = None,
        entry_delay_trading_days: int = 0,
        records_by_code: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        codes = await self._resolve_rotation_codes(universe, user_id)
        warnings: List[str] = []
        if records_by_code is None:
            records_by_code, warnings = await self.etf_data.get_history_map(
                codes,
                self.warmup_start_date(start_date),
                end_date,
                adjust=adjust,
            )
        config = self._build_config(
            strategy_id=strategy_id,
            start_date=start_date,
            end_date=end_date,
            universe=codes,
            initial_cash=initial_cash,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            adjust=adjust,
            entry_delay_trading_days=entry_delay_trading_days,
            params=params or {},
        )
        try:
            result = self.engine.run(records_by_code, config)
        except ValueError as exc:
            if "Not enough ETF daily data" not in str(exc):
                raise
            raise ValueError(self._data_error_message(records_by_code, codes, warnings)) from exc
        result["data_warnings"] = warnings
        return result

    async def entry_offset_stability(
        self,
        strategy_id: str,
        start_date: str,
        end_date: str,
        universe: Optional[List[str]] = None,
        initial_cash: float = 1_000_000.0,
        commission_bps: float = 5.0,
        slippage_bps: float = 5.0,
        adjust: str = "qfq",
        params: Optional[Dict[str, Any]] = None,
        offset_start: int = 0,
        offset_end: int = 20,
        offset_step: int = 1,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if offset_end < offset_start:
            raise ValueError("offset_end must be greater than or equal to offset_start")

        codes = await self._resolve_rotation_codes(universe, user_id)
        records_by_code, warnings = await self.etf_data.get_history_map(
            codes,
            self.warmup_start_date(start_date),
            end_date,
            adjust=adjust,
        )

        items: List[Dict[str, Any]] = []
        for offset in range(offset_start, offset_end + 1, offset_step):
            result = await self.run_backtest(
                strategy_id=strategy_id,
                start_date=start_date,
                end_date=end_date,
                universe=codes,
                initial_cash=initial_cash,
                commission_bps=commission_bps,
                slippage_bps=slippage_bps,
                adjust=adjust,
                params=params or {},
                entry_delay_trading_days=offset,
                records_by_code=records_by_code,
                user_id=user_id,
            )
            curve = result.get("equity_curve") or []
            entry_index = min(max(0, offset), max(0, len(curve) - 1))
            first_buy = next((trade for trade in result.get("trades", []) if trade.get("side") == "buy"), None)
            metrics = result.get("metrics", {})
            diagnostics = result.get("diagnostics", {})
            items.append(
                {
                    "offset": offset,
                    "entry_allowed_date": curve[entry_index]["date"] if curve else None,
                    "first_buy_date": first_buy.get("date") if first_buy else None,
                    "metrics": self._with_excess_return(metrics, diagnostics),
                    "diagnostics": diagnostics,
                }
            )

        return {
            "strategy_id": strategy_id,
            "params": params or {},
            "start_date": start_date,
            "end_date": end_date,
            "offset_start": offset_start,
            "offset_end": offset_end,
            "offset_step": offset_step,
            "items": items,
            "summary": self._entry_offset_summary(items),
            "data_warnings": warnings,
        }

    async def compare(
        self,
        requests: List[Dict[str, Any]],
        common: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        codes = await self._resolve_rotation_codes(common.get("universe"), user_id)
        records_by_code, warnings = await self.etf_data.get_history_map(
            codes,
            self.warmup_start_date(common["start_date"]),
            common["end_date"],
            adjust=common.get("adjust", "qfq"),
        )
        results = []
        adjust = common.get("adjust", "qfq")
        for item in requests:
            result = await self.run_backtest(
                strategy_id=item["strategy_id"],
                start_date=common["start_date"],
                end_date=common["end_date"],
                universe=codes,
                initial_cash=common.get("initial_cash", 1_000_000.0),
                commission_bps=common.get("commission_bps", 5.0),
                slippage_bps=common.get("slippage_bps", 5.0),
                adjust=adjust,
                params=item.get("params") or {},
                records_by_code=records_by_code,
                user_id=user_id,
            )
            result["label"] = item.get("label") or item["strategy_id"]
            results.append(result)
        return {"items": results, "data_warnings": warnings}

    @staticmethod
    def warmup_start_date(start_date: str, days: int = BACKTEST_WARMUP_CALENDAR_DAYS) -> str:
        parsed = datetime.strptime(start_date, "%Y-%m-%d").date()
        return (parsed - timedelta(days=days)).strftime("%Y-%m-%d")

    def _rotation_codes(self, universe: Optional[List[str]]) -> List[str]:
        raw_codes = universe or [item["code"] for item in DEFAULT_ROTATION_UNIVERSE]
        return [str(code).zfill(6) for code in raw_codes]

    async def _resolve_rotation_codes(self, universe: Optional[List[str]], user_id: Optional[str]) -> List[str]:
        if universe:
            return self._rotation_codes(universe)
        return [str(code).zfill(6) for code in await self.default_rotation_codes(user_id)]

    def _build_config(
        self,
        strategy_id: str,
        start_date: str,
        end_date: str,
        universe: List[str],
        initial_cash: float,
        commission_bps: float,
        slippage_bps: float,
        adjust: str,
        entry_delay_trading_days: int,
        params: Dict[str, Any],
    ) -> BacktestConfig:
        return BacktestConfig(
            strategy_id=strategy_id,
            start_date=start_date,
            end_date=end_date,
            universe=universe,
            initial_cash=initial_cash,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            price_adjust=adjust,
            entry_delay_trading_days=entry_delay_trading_days,
            params=params,
        )

    def _with_excess_return(self, metrics: Dict[str, Any], diagnostics: Dict[str, Any]) -> Dict[str, Any]:
        benchmark_return = diagnostics.get("benchmark_return")
        total_return = metrics.get("total_return")
        if benchmark_return is None or total_return is None:
            return metrics
        return {**metrics, "excess_return": round(float(total_return) - float(benchmark_return), 6)}

    def _data_error_message(
        self,
        records_by_code: Dict[str, List[Dict[str, Any]]],
        codes: List[str],
        warnings: List[str],
    ) -> str:
        counts = {str(code).zfill(6): len(records_by_code.get(str(code).zfill(6), [])) for code in codes}
        available = sum(1 for count in counts.values() if count > 0)
        sample_counts = ", ".join(f"{code}:{count}" for code, count in list(counts.items())[:8])
        sample_warnings = "; ".join(warnings[:5])
        message = (
            f"ETF 日线数据不足，无法回测。已取得 {available}/{len(codes)} 个 ETF 的数据；"
            f"样例行数 {sample_counts}。"
        )
        if sample_warnings:
            message += f" 数据告警：{sample_warnings}"
        message += " 请稍后重试，或缩小 ETF 池/改用不复权口径。"
        return message

    def _entry_offset_summary(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        returns = [float(item["metrics"]["total_return"]) for item in items if "total_return" in item["metrics"]]
        drawdowns = [float(item["metrics"]["max_drawdown"]) for item in items if "max_drawdown" in item["metrics"]]
        calmars = [float(item["metrics"]["calmar"]) for item in items if "calmar" in item["metrics"]]
        trade_counts = [float(item["metrics"]["trade_count"]) for item in items if "trade_count" in item["metrics"]]
        excess_returns = [
            float(item["metrics"]["excess_return"])
            for item in items
            if item["metrics"].get("excess_return") is not None
        ]

        def rounded(value: float) -> float:
            return round(float(value), 6)

        summary: Dict[str, Any] = {
            "sample_count": len(items),
            "positive_ratio": rounded(sum(1 for value in returns if value > 0) / len(returns)) if returns else 0.0,
            "beat_benchmark_ratio": (
                rounded(sum(1 for value in excess_returns if value > 0) / len(excess_returns))
                if excess_returns
                else 0.0
            ),
        }
        if returns:
            best = max(items, key=lambda item: item["metrics"].get("total_return", float("-inf")))
            worst = min(items, key=lambda item: item["metrics"].get("total_return", float("inf")))
            summary.update(
                {
                    "total_return_mean": rounded(sum(returns) / len(returns)),
                    "total_return_median": rounded(median(returns)),
                    "total_return_min": rounded(min(returns)),
                    "total_return_max": rounded(max(returns)),
                    "total_return_std": rounded(pstdev(returns)) if len(returns) > 1 else 0.0,
                    "best_offset": best.get("offset"),
                    "worst_offset": worst.get("offset"),
                }
            )
        if excess_returns:
            summary.update(
                {
                    "excess_return_mean": rounded(sum(excess_returns) / len(excess_returns)),
                    "excess_return_median": rounded(median(excess_returns)),
                    "excess_return_min": rounded(min(excess_returns)),
                }
            )
        if drawdowns:
            summary["max_drawdown_worst"] = rounded(min(drawdowns))
            summary["max_drawdown_median"] = rounded(median(drawdowns))
        if calmars:
            summary["calmar_median"] = rounded(median(calmars))
        if trade_counts:
            summary["trade_count_median"] = rounded(median(trade_counts))
        return summary
