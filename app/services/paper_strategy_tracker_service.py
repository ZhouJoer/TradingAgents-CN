from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_mongo_db
from app.services.backtest.backtest_service import BacktestService
from app.services.backtest.etf_data_service import ETFDataService
from app.utils.timezone import now_tz


def _today() -> str:
    return now_tz().date().isoformat()


def _default_start_date() -> str:
    return (now_tz().date() - timedelta(days=365 * 4)).isoformat()


def _default_tracking_start_date() -> str:
    return now_tz().date().isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _normalize_codes(values: Optional[List[str]]) -> List[str]:
    return [str(code).strip().zfill(6) for code in values or [] if str(code).strip()]


class PaperStrategyTrackerService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.trackers = db["paper_strategy_trackers"]
        self.orders = db["paper_strategy_tracker_orders"]
        self.runs = db["paper_strategy_tracker_runs"]
        self.backtest = BacktestService(db)
        self.etf_data = ETFDataService(db)

    async def ensure_indexes(self) -> None:
        await self.trackers.create_index([("tracker_id", 1)], unique=True, background=True)
        await self.trackers.create_index([("user_id", 1), ("status", 1), ("updated_at", -1)], background=True)
        await self.orders.create_index([("tracker_id", 1), ("created_at", -1)], background=True)
        await self.runs.create_index([("tracker_id", 1), ("trade_date", -1)], background=True)
        await self.runs.create_index(
            [("tracker_id", 1), ("trade_date", 1), ("target_signature", 1)],
            unique=True,
            background=True,
            name="tracker_date_signature_unique",
        )

    async def list_trackers(self, user_id: str, include_paused: bool = True) -> List[Dict[str, Any]]:
        await self.ensure_indexes()
        query: Dict[str, Any] = {"user_id": user_id}
        if not include_paused:
            query["status"] = "active"
        rows = await self.trackers.find(query, {"_id": 0}).sort("updated_at", -1).to_list(None)
        return [self._normalize_tracker(row) for row in rows]

    async def get_tracker(self, tracker_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        await self.ensure_indexes()
        doc = await self.trackers.find_one({"tracker_id": tracker_id, "user_id": user_id}, {"_id": 0})
        if not doc:
            return None
        tracker = self._normalize_tracker(doc)
        tracker["recent_orders"] = await self.orders.find({"tracker_id": tracker_id}, {"_id": 0}).sort("created_at", -1).limit(50).to_list(None)
        tracker["recent_runs"] = await self.runs.find({"tracker_id": tracker_id}, {"_id": 0}).sort("created_at", -1).limit(30).to_list(None)
        return tracker

    async def create_tracker(self, user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        await self.ensure_indexes()
        now = datetime.utcnow()
        tracker_id = uuid.uuid4().hex
        initial_cash = float(payload.get("initial_cash") or 1_000_000.0)
        universe = _normalize_codes(payload.get("universe"))
        if not universe:
            universe = await self.backtest.default_rotation_codes(user_id)
        doc = {
            "tracker_id": tracker_id,
            "user_id": user_id,
            "name": payload.get("name") or payload["strategy_id"],
            "strategy_id": payload["strategy_id"],
            "params": payload.get("params") or {},
            "universe": universe,
            "candidate_id": payload.get("candidate_id"),
            "status": payload.get("status") or "active",
            "start_date": payload.get("start_date") or _default_start_date(),
            "adjust": payload.get("adjust") or "qfq",
            "initial_cash": initial_cash,
            "cash": initial_cash,
            "positions": {},
            "commission_bps": float(payload.get("commission_bps") or 5.0),
            "slippage_bps": float(payload.get("slippage_bps") or 5.0),
            "version": 1,
            "version_history": [],
            "last_signal": None,
            "last_equity": initial_cash,
            "last_run_at": None,
            "tracking_start_date": payload.get("tracking_start_date") or _default_tracking_start_date(),
            "open_policy": payload.get("open_policy") or "next_signal",
            "first_open_trade_date": None,
            "last_processed_trade_date": None,
            "pending_replay_date": None,
            "last_replay_status": None,
            "created_at": now,
            "updated_at": now,
        }
        await self.trackers.insert_one(doc)
        return self._normalize_tracker(doc)

    async def update_tracker(self, tracker_id: str, user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        await self.ensure_indexes()
        existing = await self.trackers.find_one({"tracker_id": tracker_id, "user_id": user_id}, {"_id": 0})
        if not existing:
            raise ValueError("Tracker not found")
        updates: Dict[str, Any] = {"updated_at": datetime.utcnow()}
        versioned = False
        for key in ("name", "status", "start_date", "tracking_start_date", "open_policy", "adjust", "candidate_id"):
            if key in payload and payload[key] is not None:
                updates[key] = payload[key]
        for key in ("initial_cash", "commission_bps", "slippage_bps"):
            if key in payload and payload[key] is not None:
                updates[key] = float(payload[key])
        if "params" in payload and payload["params"] is not None:
            updates["params"] = payload["params"]
            versioned = True
        if "universe" in payload and payload["universe"] is not None:
            updates["universe"] = _normalize_codes(payload["universe"])
            versioned = True

        update_doc: Dict[str, Any] = {"$set": updates}
        if versioned:
            update_doc["$inc"] = {"version": 1}
            update_doc["$push"] = {
                "version_history": {
                    "version": int(existing.get("version") or 1),
                    "params": existing.get("params") or {},
                    "universe": existing.get("universe") or [],
                    "ended_at": datetime.utcnow(),
                }
            }
        await self.trackers.update_one({"tracker_id": tracker_id, "user_id": user_id}, update_doc)
        doc = await self.trackers.find_one({"tracker_id": tracker_id, "user_id": user_id}, {"_id": 0})
        if not doc:
            raise ValueError("Tracker not found")
        return self._normalize_tracker(doc)

    async def delete_tracker(self, tracker_id: str, user_id: str) -> bool:
        await self.ensure_indexes()
        result = await self.trackers.delete_one({"tracker_id": tracker_id, "user_id": user_id})
        if result.deleted_count:
            await self.orders.delete_many({"tracker_id": tracker_id})
            await self.runs.delete_many({"tracker_id": tracker_id})
        return result.deleted_count > 0

    async def run_tracker(self, tracker_id: str, user_id: str, force: bool = False) -> Dict[str, Any]:
        await self.ensure_indexes()
        doc = await self.trackers.find_one({"tracker_id": tracker_id, "user_id": user_id}, {"_id": 0})
        if not doc:
            raise ValueError("Tracker not found")
        return await self._run_tracker_doc(doc, force=force)

    async def run_all_active(self) -> Dict[str, Any]:
        await self.ensure_indexes()
        docs = await self.trackers.find({"status": "active"}, {"_id": 0}).to_list(None)
        results = []
        for doc in docs:
            try:
                results.append(await self._run_tracker_doc(doc, force=False))
            except Exception as exc:
                results.append({"tracker_id": doc.get("tracker_id"), "status": "failed", "message": str(exc)})
        return {"processed": len(results), "items": results}

    async def _run_tracker_doc(self, tracker: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
        tracker = self._normalize_tracker(tracker)
        if tracker["status"] != "active" and not force:
            return {"tracker_id": tracker["tracker_id"], "status": "skipped", "message": "tracker is not active"}
        await self._hydrate_replay_cursor(tracker)

        result = await self.backtest.run_backtest(
            strategy_id=tracker["strategy_id"],
            start_date=tracker["start_date"],
            end_date=_today(),
            universe=tracker["universe"],
            initial_cash=tracker["initial_cash"],
            commission_bps=tracker["commission_bps"],
            slippage_bps=tracker["slippage_bps"],
            adjust=tracker["adjust"],
            params=tracker["params"],
            user_id=tracker["user_id"],
        )
        events = self._target_replay_events(result, tracker)
        if not events:
            waiting_for_open = not tracker.get("last_processed_trade_date") and not tracker.get("positions")
            status = "waiting_signal" if waiting_for_open else "skipped"
            message = (
                f"waiting for first signal after {tracker.get('tracking_start_date')}"
                if waiting_for_open
                else "no new target events"
            )
            now = datetime.utcnow()
            await self.trackers.update_one(
                {"tracker_id": tracker["tracker_id"]},
                {"$set": {"last_run_at": now, "last_replay_status": status, "updated_at": now}},
            )
            return {
                "tracker_id": tracker["tracker_id"],
                "status": status,
                "skipped": True,
                "message": message,
                "processed": 0,
                "items": [],
            }

        items = []
        for event in events:
            item = await self._execute_target_event(
                tracker,
                event["trade_date"],
                event["target_weights"],
                event.get("signal"),
            )
            items.append(item)
            if item.get("status") == "pending_data":
                break

        final_status = items[-1].get("status", "completed") if items else "skipped"
        return {
            "tracker_id": tracker["tracker_id"],
            "status": final_status,
            "skipped": bool(items) and all(item.get("skipped") for item in items),
            "processed": sum(1 for item in items if item.get("status") == "completed" and not item.get("skipped")),
            "pending": sum(1 for item in items if item.get("status") == "pending_data"),
            "items": items,
            "last_processed_trade_date": tracker.get("last_processed_trade_date"),
        }

    async def _execute_target_event(
        self,
        tracker: Dict[str, Any],
        trade_date: str,
        target_weights: Dict[str, float],
        signal: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        signature = self._target_signature(tracker, trade_date, target_weights)
        run_filter = {
            "tracker_id": tracker["tracker_id"],
            "trade_date": trade_date,
            "target_signature": signature,
        }
        existing = await self.runs.find_one(run_filter, {"_id": 0})
        if existing and existing.get("status") == "completed":
            await self._mark_tracker_progress(tracker, trade_date, "skipped")
            return {**existing, "skipped": True}

        prices, warnings, missing = await self._latest_open_prices(tracker, trade_date, target_weights)
        now = datetime.utcnow()
        if missing:
            run_doc = {
                "run_id": existing.get("run_id") if existing else uuid.uuid4().hex,
                "tracker_id": tracker["tracker_id"],
                "user_id": tracker["user_id"],
                "trade_date": trade_date,
                "strategy_id": tracker["strategy_id"],
                "target_weights": target_weights,
                "target_signature": signature,
                "signal": signal,
                "orders_count": 0,
                "equity": round(self._mark_to_market_equity(tracker, prices), 4),
                "cash": round(_safe_float(tracker.get("cash"), _safe_float(tracker.get("initial_cash"))), 4),
                "data_warnings": warnings,
                "missing_prices": missing,
                "status": "pending_data",
                "message": f"missing execution prices: {', '.join(missing[:8])}",
                "created_at": existing.get("created_at") if existing else now,
                "updated_at": now,
            }
            if existing:
                await self.runs.update_one(run_filter, {"$set": run_doc})
            else:
                await self.runs.update_one(run_filter, {"$setOnInsert": run_doc}, upsert=True)
            await self.trackers.update_one(
                {"tracker_id": tracker["tracker_id"]},
                {
                    "$set": {
                        "pending_replay_date": trade_date,
                        "last_replay_status": "pending_data",
                        "last_run_at": now,
                        "updated_at": now,
                    }
                },
            )
            tracker["pending_replay_date"] = trade_date
            tracker["last_replay_status"] = "pending_data"
            tracker["last_run_at"] = now
            return run_doc

        orders, new_cash, new_positions, equity = self._build_rebalance_orders(tracker, target_weights, prices, trade_date)
        run_doc = {
            "run_id": existing.get("run_id") if existing else uuid.uuid4().hex,
            "tracker_id": tracker["tracker_id"],
            "user_id": tracker["user_id"],
            "trade_date": trade_date,
            "strategy_id": tracker["strategy_id"],
            "target_weights": target_weights,
            "target_signature": signature,
            "signal": signal,
            "orders_count": len(orders),
            "equity": round(equity, 4),
            "cash": round(new_cash, 4),
            "data_warnings": warnings,
            "missing_prices": [],
            "status": "completed",
            "message": "completed",
            "created_at": existing.get("created_at") if existing else now,
            "updated_at": now,
        }
        if existing:
            await self.runs.update_one(run_filter, {"$set": run_doc})
        else:
            run_write = await self.runs.update_one(run_filter, {"$setOnInsert": run_doc}, upsert=True)
            if getattr(run_write, "matched_count", 0):
                existing = await self.runs.find_one(run_filter, {"_id": 0})
                return {**(existing or run_doc), "skipped": True}
        if orders:
            await self.orders.insert_many(orders)
        await self.trackers.update_one(
            {"tracker_id": tracker["tracker_id"]},
            {
                "$set": {
                    "cash": new_cash,
                    "positions": new_positions,
                    "last_signal": signal,
                    "last_equity": round(equity, 4),
                    "last_run_at": now,
                    "first_open_trade_date": tracker.get("first_open_trade_date") or (trade_date if orders else None),
                    "last_processed_trade_date": trade_date,
                    "pending_replay_date": None,
                    "last_replay_status": "completed",
                    "updated_at": now,
                }
            },
        )
        tracker["cash"] = new_cash
        tracker["positions"] = new_positions
        tracker["last_signal"] = signal
        tracker["last_equity"] = round(equity, 4)
        tracker["last_run_at"] = now
        tracker["first_open_trade_date"] = tracker.get("first_open_trade_date") or (trade_date if orders else None)
        tracker["last_processed_trade_date"] = trade_date
        tracker["pending_replay_date"] = None
        tracker["last_replay_status"] = "completed"
        return run_doc

    async def _hydrate_replay_cursor(self, tracker: Dict[str, Any]) -> None:
        if tracker.get("last_processed_trade_date"):
            return
        rows = await (
            self.runs.find({"tracker_id": tracker["tracker_id"], "status": "completed"}, {"_id": 0})
            .sort("trade_date", -1)
            .limit(1)
            .to_list(None)
        )
        if not rows:
            return
        trade_date = rows[0].get("trade_date")
        if not trade_date:
            return
        tracker["last_processed_trade_date"] = trade_date
        await self.trackers.update_one(
            {"tracker_id": tracker["tracker_id"]},
            {"$set": {"last_processed_trade_date": trade_date, "updated_at": datetime.utcnow()}},
        )

    async def _latest_open_prices(
        self,
        tracker: Dict[str, Any],
        trade_date: str,
        target_weights: Dict[str, float],
    ) -> Tuple[Dict[str, float], List[str], List[str]]:
        codes = sorted(set(target_weights) | set(tracker.get("positions") or {}))
        if not codes:
            return {}, [], []
        history, warnings = await self.etf_data.get_history_map(
            codes,
            trade_date,
            trade_date,
            adjust=tracker["adjust"],
            auto_fetch=False,
        )
        prices: Dict[str, float] = {}
        for code, rows in history.items():
            if not rows:
                continue
            row = rows[-1]
            price = _safe_float(row.get("open") or row.get("close"))
            if price > 0:
                prices[code] = price
        missing = [code for code in codes if code not in prices]
        if missing:
            warnings.append(f"missing execution prices: {', '.join(missing[:8])}")
        return prices, warnings, missing

    def _build_rebalance_orders(
        self,
        tracker: Dict[str, Any],
        target_weights: Dict[str, float],
        prices: Dict[str, float],
        trade_date: str,
    ) -> Tuple[List[Dict[str, Any]], float, Dict[str, Dict[str, float]], float]:
        cash = _safe_float(tracker.get("cash"), _safe_float(tracker.get("initial_cash")))
        positions = {
            str(code).zfill(6): {
                "quantity": _safe_float(pos.get("quantity")),
                "avg_cost": _safe_float(pos.get("avg_cost")),
            }
            for code, pos in (tracker.get("positions") or {}).items()
        }
        equity = cash + sum(pos["quantity"] * prices.get(code, 0.0) for code, pos in positions.items())
        if equity <= 0:
            return [], cash, positions, equity

        commission_rate = _safe_float(tracker.get("commission_bps")) / 10000.0
        slippage_rate = _safe_float(tracker.get("slippage_bps")) / 10000.0
        planned = []
        for code in sorted(set(positions) | set(target_weights)):
            price = prices.get(code)
            if not price:
                continue
            current_qty = positions.get(code, {}).get("quantity", 0.0)
            current_value = current_qty * price
            target_value = equity * max(0.0, float(target_weights.get(code, 0.0)))
            delta_value = target_value - current_value
            if abs(delta_value) < max(1.0, equity * 0.0001):
                continue
            side = "buy" if delta_value > 0 else "sell"
            planned.append((0 if side == "sell" else 1, code, side, price, delta_value))

        orders: List[Dict[str, Any]] = []
        now = datetime.utcnow()
        for _, code, side, price, delta_value in sorted(planned):
            execution_price = price * (1 + slippage_rate) if side == "buy" else price * (1 - slippage_rate)
            if execution_price <= 0:
                continue
            quantity = abs(delta_value) / execution_price
            if side == "sell":
                current_qty = positions.get(code, {}).get("quantity", 0.0)
                quantity = min(quantity, current_qty)
            amount = quantity * execution_price
            commission = amount * commission_rate
            if side == "buy" and amount + commission > cash:
                scale = cash / (amount + commission) if amount + commission > 0 else 0.0
                quantity *= scale
                amount *= scale
                commission *= scale
            if quantity <= 0:
                continue

            if side == "buy":
                old = positions.setdefault(code, {"quantity": 0.0, "avg_cost": execution_price})
                old_qty = old["quantity"]
                new_qty = old_qty + quantity
                old["avg_cost"] = ((old["avg_cost"] * old_qty) + amount) / new_qty if new_qty > 0 else execution_price
                old["quantity"] = new_qty
                cash -= amount + commission
            else:
                pos = positions.setdefault(code, {"quantity": 0.0, "avg_cost": execution_price})
                pos["quantity"] = max(0.0, pos["quantity"] - quantity)
                cash += amount - commission
                if pos["quantity"] <= 1e-8:
                    positions.pop(code, None)

            orders.append(
                {
                    "order_id": uuid.uuid4().hex,
                    "tracker_id": tracker["tracker_id"],
                    "user_id": tracker["user_id"],
                    "trade_date": trade_date,
                    "code": code,
                    "market": "CN",
                    "currency": "CNY",
                    "side": side,
                    "quantity": round(quantity, 4),
                    "price": round(execution_price, 4),
                    "amount": round(amount, 4),
                    "commission": round(commission, 4),
                    "status": "filled",
                    "created_at": now,
                    "filled_at": now,
                    "source": "strategy_tracker",
                }
            )

        final_equity = cash + sum(pos["quantity"] * prices.get(code, 0.0) for code, pos in positions.items())
        cleaned_positions = {
            code: {"quantity": round(pos["quantity"], 4), "avg_cost": round(pos["avg_cost"], 4)}
            for code, pos in positions.items()
            if pos["quantity"] > 1e-8
        }
        return orders, round(cash, 4), cleaned_positions, final_equity

    def _latest_signal(self, result: Dict[str, Any], trade_date: str) -> Optional[Dict[str, Any]]:
        signals = result.get("signals") or []
        eligible = [item for item in signals if str(item.get("execute_date") or "") <= trade_date]
        return eligible[-1] if eligible else None

    def _target_replay_events(self, result: Dict[str, Any], tracker: Dict[str, Any]) -> List[Dict[str, Any]]:
        positions = result.get("positions") or []
        if not positions:
            raise ValueError("No strategy position snapshot generated")
        last_processed = str(tracker.get("last_processed_trade_date") or "")
        if not last_processed:
            if tracker.get("open_policy") == "sync_current":
                snapshot = positions[-1]
                trade_date = str(snapshot["date"])
                return [
                    {
                        "trade_date": trade_date,
                        "target_weights": self._normalize_target_weights(snapshot.get("weights") or {}),
                        "signal": self._latest_signal(result, trade_date),
                    }
                ]
            last_processed = str(tracker.get("tracking_start_date") or _default_tracking_start_date())

        events_by_date: Dict[str, Dict[str, Any]] = {}
        for signal in result.get("signals") or []:
            trade_date = str(signal.get("execute_date") or "")
            if not trade_date or trade_date <= last_processed:
                continue
            events_by_date[trade_date] = {
                "trade_date": trade_date,
                "target_weights": self._normalize_target_weights(signal.get("target_weights") or {}),
                "signal": signal,
            }
        return [events_by_date[date] for date in sorted(events_by_date)]

    def _normalize_target_weights(self, weights: Dict[str, Any]) -> Dict[str, float]:
        return {
            str(code).zfill(6): float(weight)
            for code, weight in (weights or {}).items()
            if weight is not None and float(weight) > 0
        }

    def _mark_to_market_equity(self, tracker: Dict[str, Any], prices: Dict[str, float]) -> float:
        cash = _safe_float(tracker.get("cash"), _safe_float(tracker.get("initial_cash")))
        return cash + sum(
            _safe_float(pos.get("quantity")) * prices.get(str(code).zfill(6), 0.0)
            for code, pos in (tracker.get("positions") or {}).items()
        )

    async def _mark_tracker_progress(self, tracker: Dict[str, Any], trade_date: str, status: str) -> None:
        now = datetime.utcnow()
        await self.trackers.update_one(
            {"tracker_id": tracker["tracker_id"]},
            {
                "$set": {
                    "last_processed_trade_date": trade_date,
                    "pending_replay_date": None,
                    "last_replay_status": status,
                    "last_run_at": now,
                    "updated_at": now,
                }
            },
        )
        tracker["last_processed_trade_date"] = trade_date
        tracker["pending_replay_date"] = None
        tracker["last_replay_status"] = status
        tracker["last_run_at"] = now

    def _target_signature(self, tracker: Dict[str, Any], trade_date: str, target_weights: Dict[str, float]) -> str:
        payload = {
            "version": tracker.get("version", 1),
            "trade_date": trade_date,
            "strategy_id": tracker["strategy_id"],
            "target_weights": {code: round(float(weight), 6) for code, weight in sorted(target_weights.items())},
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _normalize_tracker(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        tracker = dict(doc)
        tracker.pop("_id", None)
        tracker.setdefault("status", "active")
        tracker.setdefault("params", {})
        tracker["universe"] = _normalize_codes(tracker.get("universe"))
        tracker.setdefault("positions", {})
        tracker["initial_cash"] = _safe_float(tracker.get("initial_cash"), 1_000_000.0)
        tracker["cash"] = _safe_float(tracker.get("cash"), tracker["initial_cash"])
        tracker["commission_bps"] = _safe_float(tracker.get("commission_bps"), 5.0)
        tracker["slippage_bps"] = _safe_float(tracker.get("slippage_bps"), 5.0)
        tracker.setdefault("adjust", "qfq")
        tracker.setdefault("start_date", _default_start_date())
        if not tracker.get("tracking_start_date"):
            created_at = tracker.get("created_at")
            if isinstance(created_at, datetime):
                tracker["tracking_start_date"] = created_at.date().isoformat()
            else:
                tracker["tracking_start_date"] = _default_tracking_start_date()
        tracker.setdefault("open_policy", "next_signal")
        tracker.setdefault("first_open_trade_date", None)
        tracker.setdefault("version", 1)
        tracker.setdefault("last_equity", tracker["cash"])
        tracker.setdefault("last_processed_trade_date", None)
        tracker.setdefault("pending_replay_date", None)
        tracker.setdefault("last_replay_status", None)
        return tracker


async def run_paper_strategy_tracking() -> Dict[str, Any]:
    service = PaperStrategyTrackerService(get_mongo_db())
    return await service.run_all_active()
