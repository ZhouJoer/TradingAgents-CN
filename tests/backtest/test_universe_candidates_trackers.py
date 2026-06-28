from __future__ import annotations

import asyncio
import re
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from app.services.backtest.etf_universe_service import ETFUniverseService, normalize_tags
from app.services.backtest.mining_service import MiningService, discovered_adaptive_topk_strategy_pack
from app.services.paper_strategy_tracker_service import PaperStrategyTrackerService


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows

    def sort(self, field: str, direction: int):
        reverse = direction < 0
        self.rows.sort(key=lambda item: item.get(field) is None or item.get(field), reverse=reverse)
        return self

    def limit(self, count: int):
        self.rows = self.rows[:count]
        return self

    async def to_list(self, _count):
        return deepcopy(self.rows)


class _Collection:
    def __init__(self):
        self.docs: list[dict[str, Any]] = []

    async def create_index(self, *args, **kwargs):
        return None

    def find(self, query=None, projection=None):
        query = query or {}
        return _Cursor([doc for doc in self.docs if _matches(doc, query)])

    async def find_one(self, query=None, projection=None):
        query = query or {}
        for doc in self.docs:
            if _matches(doc, query):
                return deepcopy(doc)
        return None

    async def insert_one(self, doc):
        self.docs.append(deepcopy(doc))
        return SimpleNamespace(inserted_id=doc.get("_id"))

    async def insert_many(self, docs):
        self.docs.extend(deepcopy(list(docs)))
        return SimpleNamespace(inserted_ids=[doc.get("_id") for doc in docs])

    async def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if _matches(doc, query):
                if "$set" in update:
                    doc.update(deepcopy(update["$set"]))
                if "$inc" in update:
                    for key, value in update["$inc"].items():
                        doc[key] = doc.get(key, 0) + value
                if "$push" in update:
                    for key, value in update["$push"].items():
                        doc.setdefault(key, []).append(deepcopy(value))
                return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)
        if not upsert:
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)
        doc = deepcopy(query)
        doc.update(deepcopy(update.get("$setOnInsert", {})))
        doc.update(deepcopy(update.get("$set", {})))
        self.docs.append(doc)
        return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=doc.get("_id"))

    async def delete_one(self, query):
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if not _matches(doc, query)]
        return SimpleNamespace(deleted_count=before - len(self.docs))

    async def delete_many(self, query):
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if not _matches(doc, query)]
        return SimpleNamespace(deleted_count=before - len(self.docs))


class _Db:
    def __init__(self):
        self.collections: dict[str, _Collection] = {}

    def __getitem__(self, name: str):
        self.collections.setdefault(name, _Collection())
        return self.collections[name]


class _BacktestStub:
    def __init__(self, result: dict[str, Any]):
        self.result = result

    async def run_backtest(self, **kwargs):
        return deepcopy(self.result)


class _ETFDataStub:
    def __init__(self, prices_by_date: dict[str, dict[str, float]]):
        self.prices_by_date = prices_by_date

    async def get_history_map(self, codes, start_date, end_date, adjust="qfq", auto_fetch=False):
        prices = self.prices_by_date.get(start_date, {})
        rows = {
            code: [{"trade_date": start_date, "open": prices[code], "close": prices[code]}]
            for code in codes
            if code in prices
        }
        return rows, []


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(doc, part) for part in expected):
                return False
            continue
        actual = doc.get(key)
        if isinstance(expected, dict) and "$regex" in expected:
            flags = re.I if "i" in expected.get("$options", "") else 0
            if isinstance(actual, list):
                text = " ".join(str(item) for item in actual)
            else:
                text = str(actual or "")
            if not re.search(expected["$regex"], text, flags):
                return False
            continue
        if isinstance(actual, list):
            if expected not in actual:
                return False
        elif actual != expected:
            return False
    return True


def test_etf_universe_merges_default_items_with_user_overrides() -> None:
    async def _run():
        service = ETFUniverseService(_Db())

        await service.update_item("u1", "159915", {"active": False})
        await service.upsert_item(
            "u1",
            {"code": "588000", "name": "科创50ETF", "group": "broad", "tags": "tech, core"},
        )

        items = await service.list_universe("u1")
        codes = {item["code"] for item in items}

        assert "159915" not in codes
        assert "588000" in codes
        added = next(item for item in items if item["code"] == "588000")
        assert added["group"] == "broad"
        assert added["tags"] == ["tech", "core"]
        assert "511880" not in await service.active_rotation_codes("u1")

    asyncio.run(_run())


def test_candidate_library_filters_updates_and_apply_counts() -> None:
    async def _run():
        service = MiningService(_Db())
        first = await service.save_candidate(
            {
                "name": "Momentum Low Turnover",
                "strategy_id": "ema_momentum_rotation",
                "params": {"top_k": 2},
                "score": 1.2,
                "metrics": {"total_return": 0.1},
                "tags": "low_turnover, accepted",
                "favorite": True,
                "universe": ["510300"],
            },
            "u1",
        )
        await service.save_candidate(
            {
                "name": "Archived",
                "strategy_id": "dual_momentum_core",
                "params": {},
                "score": 0.2,
                "status": "archived",
            },
            "u1",
        )

        filtered = await service.list_candidates("u1", tag="accepted", favorite=True, keyword="momentum", sort_by="score")
        assert [item["candidate_id"] for item in filtered] == [first["candidate_id"]]

        updated = await service.update_candidate(
            first["candidate_id"],
            {"name": "Renamed", "tags": ["core"], "note": "checked", "favorite": False},
            "u1",
        )
        assert updated["name"] == "Renamed"
        assert updated["tags"] == ["core"]
        assert updated["note"] == "checked"
        assert updated["favorite"] is False

        applied = await service.apply_candidate(first["candidate_id"], "u1")
        assert applied["strategy_id"] == "ema_momentum_rotation"
        assert applied["params"] == {"top_k": 2}
        assert applied["universe"] == ["510300"]
        assert applied["candidate"]["applied_count"] == 1
        assert applied["candidate"]["last_applied_at"] is not None

        assert await service.delete_candidate(first["candidate_id"], "u1") is True
        assert await service.list_candidates("u1", status="all") and len(await service.list_candidates("u1", status="all")) == 1

    asyncio.run(_run())


def test_discovered_adaptive_topk_candidate_saves_idempotently_and_creates_tracker() -> None:
    async def _run():
        db = _Db()
        mining = MiningService(db)
        first = await mining.save_discovered_adaptive_topk_candidate("u1", universe=["510300", "512400"])
        second = await mining.save_discovered_adaptive_topk_candidate("u1", universe=["510300", "512400"])

        assert first["candidate_id"] == second["candidate_id"]
        assert first["strategy_id"] == "industry_momentum_enhanced"
        assert first["params"]["top_k"] == 2
        assert first["params"]["adaptive_top_k"] is True
        assert first["params"]["top_k_score_gap"] == 0.02
        assert first["metrics"]["total_return"] == 5.114146
        assert len(db["backtest_candidate_strategies"].docs) == 1

        applied = await mining.apply_candidate(first["candidate_id"], "u1")
        paper = PaperStrategyTrackerService(db)
        tracker = await paper.create_tracker(
            "u1",
            {
                "name": "Paper",
                "strategy_id": applied["strategy_id"],
                "params": applied["params"],
                "universe": applied["universe"],
                "candidate_id": first["candidate_id"],
                "initial_cash": 1000,
            },
        )

        assert tracker["candidate_id"] == first["candidate_id"]
        assert tracker["params"]["adaptive_top_k"] is True
        assert tracker["universe"] == ["510300", "512400"]

    asyncio.run(_run())


def test_discovered_strategy_pack_documents_saved_params() -> None:
    pack = discovered_adaptive_topk_strategy_pack()

    assert pack["pack_id"] == "industry_momentum_enhanced_adaptive_topk_gap02"
    assert pack["strategy_id"] == "industry_momentum_enhanced"
    assert pack["params"]["adaptive_top_k"] is True
    assert pack["params"]["top_k_score_gap"] == 0.02
    assert pack["metrics"]["total_return"] == 5.114146
    assert pack["comparison"]["default_top1_total_return"] > pack["comparison"]["hybrid_gap02_total_return"]


def test_tracker_rebalance_sells_before_buying_and_scales_to_cash() -> None:
    service = object.__new__(PaperStrategyTrackerService)
    tracker = {
        "tracker_id": "t1",
        "user_id": "u1",
        "cash": 0,
        "initial_cash": 1000,
        "commission_bps": 5,
        "slippage_bps": 5,
        "positions": {"510300": {"quantity": 100, "avg_cost": 8}},
    }

    orders, cash, positions, equity = service._build_rebalance_orders(
        tracker,
        {"159915": 1.0},
        {"510300": 10, "159915": 10},
        "2026-06-26",
    )

    assert [order["side"] for order in orders] == ["sell", "buy"]
    assert "510300" not in positions
    assert positions["159915"]["quantity"] > 0
    assert cash >= 0
    assert equity > 990


def test_tracker_target_signature_is_stable_and_versioned() -> None:
    service = object.__new__(PaperStrategyTrackerService)
    tracker = {"version": 1, "strategy_id": "ema_momentum_rotation"}

    first = service._target_signature(tracker, "2026-06-26", {"510300": 0.5, "159915": 0.5})
    second = service._target_signature(tracker, "2026-06-26", {"159915": 0.5, "510300": 0.5})
    changed = service._target_signature({**tracker, "version": 2}, "2026-06-26", {"159915": 0.5, "510300": 0.5})

    assert first == second
    assert len(first) == 24
    assert changed != first


def test_new_tracker_waits_for_signal_after_tracking_start_date() -> None:
    async def _run():
        db = _Db()
        service = PaperStrategyTrackerService(db)
        service.backtest = _BacktestStub(
            {
                "positions": [{"date": "2026-06-28", "weights": {"512480": 1.0}}],
                "signals": [
                    {
                        "date": "2026-06-01",
                        "execute_date": "2026-06-02",
                        "target_weights": {"512480": 1.0},
                    },
                    {
                        "date": "2026-06-21",
                        "execute_date": "2026-06-22",
                        "target_weights": {"512480": 1.0},
                    },
                ],
            }
        )
        service.etf_data = _ETFDataStub({"2026-06-28": {"512480": 2.73}})
        await service.trackers.insert_one(
            {
                "tracker_id": "t-new",
                "user_id": "u1",
                "name": "New Tracker",
                "strategy_id": "biweekly_adaptive_stable_rotation",
                "params": {},
                "universe": ["512480"],
                "status": "active",
                "start_date": "2022-06-28",
                "tracking_start_date": "2026-06-28",
                "open_policy": "next_signal",
                "adjust": "qfq",
                "initial_cash": 1000,
                "cash": 1000,
                "positions": {},
                "commission_bps": 0,
                "slippage_bps": 0,
                "version": 1,
            }
        )

        result = await service.run_tracker("t-new", "u1")
        tracker = await service.trackers.find_one({"tracker_id": "t-new", "user_id": "u1"})

        assert result["status"] == "waiting_signal"
        assert result["processed"] == 0
        assert service.orders.docs == []
        assert tracker["positions"] == {}
        assert tracker.get("last_processed_trade_date") is None
        assert tracker["last_replay_status"] == "waiting_signal"

    asyncio.run(_run())


def test_new_tracker_opens_on_first_signal_after_tracking_start_date() -> None:
    async def _run():
        db = _Db()
        service = PaperStrategyTrackerService(db)
        service.backtest = _BacktestStub(
            {
                "positions": [{"date": "2026-06-29", "weights": {"512480": 1.0}}],
                "signals": [
                    {
                        "date": "2026-06-28",
                        "execute_date": "2026-06-29",
                        "target_weights": {"512480": 1.0},
                    }
                ],
            }
        )
        service.etf_data = _ETFDataStub({"2026-06-29": {"512480": 2.73}})
        await service.trackers.insert_one(
            {
                "tracker_id": "t-open",
                "user_id": "u1",
                "name": "Open Tracker",
                "strategy_id": "biweekly_adaptive_stable_rotation",
                "params": {},
                "universe": ["512480"],
                "status": "active",
                "start_date": "2022-06-28",
                "tracking_start_date": "2026-06-28",
                "open_policy": "next_signal",
                "adjust": "qfq",
                "initial_cash": 1000,
                "cash": 1000,
                "positions": {},
                "commission_bps": 0,
                "slippage_bps": 0,
                "version": 1,
            }
        )

        result = await service.run_tracker("t-open", "u1")
        tracker = await service.trackers.find_one({"tracker_id": "t-open", "user_id": "u1"})

        assert result["status"] == "completed"
        assert result["processed"] == 1
        assert [(order["trade_date"], order["side"], order["code"]) for order in service.orders.docs] == [
            ("2026-06-29", "buy", "512480")
        ]
        assert tracker["last_processed_trade_date"] == "2026-06-29"
        assert tracker["first_open_trade_date"] == "2026-06-29"
        assert tracker["positions"]["512480"]["quantity"] > 0

    asyncio.run(_run())


def test_tracker_replays_missed_signal_events_in_order_without_duplicates() -> None:
    async def _run():
        db = _Db()
        service = PaperStrategyTrackerService(db)
        service.backtest = _BacktestStub(
            {
                "positions": [{"date": "2026-01-12", "weights": {"159915": 1.0}}],
                "signals": [
                    {
                        "date": "2026-01-05",
                        "execute_date": "2026-01-06",
                        "target_weights": {"510300": 1.0},
                    },
                    {
                        "date": "2026-01-10",
                        "execute_date": "2026-01-11",
                        "target_weights": {"159915": 1.0},
                    },
                ],
            }
        )
        service.etf_data = _ETFDataStub(
            {
                "2026-01-06": {"510300": 10.0},
                "2026-01-11": {"510300": 10.0, "159915": 20.0},
            }
        )
        await service.trackers.insert_one(
            {
                "tracker_id": "t1",
                "user_id": "u1",
                "name": "Replay",
                "strategy_id": "ema_momentum_rotation",
                "params": {},
                "universe": ["510300", "159915"],
                "status": "active",
                "start_date": "2025-01-01",
                "adjust": "qfq",
                "initial_cash": 1000,
                "cash": 1000,
                "positions": {},
                "commission_bps": 0,
                "slippage_bps": 0,
                "version": 1,
                "last_processed_trade_date": "2026-01-02",
            }
        )

        result = await service.run_tracker("t1", "u1")
        orders = service.orders.docs
        tracker = await service.trackers.find_one({"tracker_id": "t1", "user_id": "u1"})

        assert result["processed"] == 2
        assert result["last_processed_trade_date"] == "2026-01-11"
        assert [(order["trade_date"], order["side"], order["code"]) for order in orders] == [
            ("2026-01-06", "buy", "510300"),
            ("2026-01-11", "sell", "510300"),
            ("2026-01-11", "buy", "159915"),
        ]
        assert tracker["last_processed_trade_date"] == "2026-01-11"
        assert tracker["positions"]["159915"]["quantity"] == 50

        second = await service.run_tracker("t1", "u1")
        assert second["status"] == "skipped"
        assert len(service.orders.docs) == 3

    asyncio.run(_run())


def test_tracker_replay_marks_pending_data_and_retries_after_prices_arrive() -> None:
    async def _run():
        db = _Db()
        service = PaperStrategyTrackerService(db)
        service.backtest = _BacktestStub(
            {
                "positions": [{"date": "2026-01-07", "weights": {"510300": 1.0}}],
                "signals": [
                    {
                        "date": "2026-01-05",
                        "execute_date": "2026-01-06",
                        "target_weights": {"510300": 1.0},
                    }
                ],
            }
        )
        etf_data = _ETFDataStub({})
        service.etf_data = etf_data
        await service.trackers.insert_one(
            {
                "tracker_id": "t2",
                "user_id": "u1",
                "name": "Pending",
                "strategy_id": "ema_momentum_rotation",
                "params": {},
                "universe": ["510300"],
                "status": "active",
                "start_date": "2025-01-01",
                "adjust": "qfq",
                "initial_cash": 1000,
                "cash": 1000,
                "positions": {},
                "commission_bps": 0,
                "slippage_bps": 0,
                "version": 1,
                "last_processed_trade_date": "2026-01-02",
            }
        )

        pending = await service.run_tracker("t2", "u1")
        tracker = await service.trackers.find_one({"tracker_id": "t2", "user_id": "u1"})

        assert pending["status"] == "pending_data"
        assert pending["pending"] == 1
        assert tracker["last_processed_trade_date"] == "2026-01-02"
        assert tracker["pending_replay_date"] == "2026-01-06"
        assert service.runs.docs[0]["status"] == "pending_data"
        assert service.orders.docs == []

        etf_data.prices_by_date["2026-01-06"] = {"510300": 10.0}
        completed = await service.run_tracker("t2", "u1")
        tracker = await service.trackers.find_one({"tracker_id": "t2", "user_id": "u1"})

        assert completed["status"] == "completed"
        assert completed["processed"] == 1
        assert tracker["last_processed_trade_date"] == "2026-01-06"
        assert tracker["pending_replay_date"] is None
        assert service.runs.docs[0]["status"] == "completed"
        assert len(service.orders.docs) == 1

    asyncio.run(_run())


def test_tracker_replay_hydrates_cursor_from_existing_completed_runs() -> None:
    async def _run():
        db = _Db()
        service = PaperStrategyTrackerService(db)
        service.backtest = _BacktestStub(
            {
                "positions": [{"date": "2026-01-12", "weights": {"159915": 1.0}}],
                "signals": [
                    {
                        "date": "2026-01-10",
                        "execute_date": "2026-01-11",
                        "target_weights": {"159915": 1.0},
                    }
                ],
            }
        )
        service.etf_data = _ETFDataStub({"2026-01-11": {"510300": 10.0, "159915": 20.0}})
        await service.trackers.insert_one(
            {
                "tracker_id": "t3",
                "user_id": "u1",
                "name": "Migrated",
                "strategy_id": "ema_momentum_rotation",
                "params": {},
                "universe": ["510300", "159915"],
                "status": "active",
                "start_date": "2025-01-01",
                "adjust": "qfq",
                "initial_cash": 1000,
                "cash": 0,
                "positions": {"510300": {"quantity": 100, "avg_cost": 10}},
                "commission_bps": 0,
                "slippage_bps": 0,
                "version": 1,
            }
        )
        await service.runs.insert_one(
            {
                "run_id": "old",
                "tracker_id": "t3",
                "user_id": "u1",
                "trade_date": "2026-01-06",
                "target_signature": "old",
                "status": "completed",
            }
        )

        result = await service.run_tracker("t3", "u1")
        tracker = await service.trackers.find_one({"tracker_id": "t3", "user_id": "u1"})

        assert result["processed"] == 1
        assert tracker["last_processed_trade_date"] == "2026-01-11"
        assert [(order["side"], order["code"]) for order in service.orders.docs] == [("sell", "510300"), ("buy", "159915")]

    asyncio.run(_run())


def test_normalize_tags_accepts_commas_spaces_and_deduplicates() -> None:
    assert normalize_tags("core, accepted core，low") == ["core", "accepted", "low"]
