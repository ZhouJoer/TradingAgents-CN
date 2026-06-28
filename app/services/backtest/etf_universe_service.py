from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from .engine import DEFAULT_ETF_UNIVERSE
from .etf_data_service import ETFDataService


VALID_GROUPS = {"broad", "sector", "factor", "commodity", "cash_watch"}


def normalize_etf_code(code: Any) -> str:
    text = str(code or "").strip()
    if not text:
        raise ValueError("ETF code is required")
    return text.zfill(6) if text.isdigit() else text


def normalize_etf_group(group: Any) -> str:
    text = str(group or "sector").strip()
    return text if text in VALID_GROUPS else "sector"


def normalize_tags(values: Any) -> List[str]:
    if not values:
        return []
    if isinstance(values, str):
        raw = re.split(r"[,，\s]+", values)
    else:
        raw = list(values)
    result: List[str] = []
    seen = set()
    for item in raw:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


class ETFUniverseService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.items = db["backtest_etf_universe_items"]
        self.etf_data = ETFDataService(db)

    async def ensure_indexes(self) -> None:
        await self.items.create_index([("user_id", 1), ("code", 1)], unique=True, background=True)
        await self.items.create_index([("user_id", 1), ("active", 1), ("group", 1)], background=True)
        await self.etf_data.ensure_indexes()

    async def list_universe(self, user_id: str, include_inactive: bool = False) -> List[Dict[str, Any]]:
        await self.ensure_indexes()
        default_items = {item["code"]: self._default_item(item) for item in DEFAULT_ETF_UNIVERSE}
        docs = await self.items.find({"user_id": user_id}, {"_id": 0}).to_list(None)

        merged = dict(default_items)
        for doc in docs:
            item = self._normalize_item(doc)
            code = item["code"]
            item["is_default"] = code in default_items
            if code in default_items:
                base = dict(default_items[code])
                base.update(item)
                item = base
            if not item.get("active", True) and not include_inactive:
                merged.pop(code, None)
                continue
            merged[code] = item

        values = list(merged.values())
        if not include_inactive:
            values = [item for item in values if item.get("active", True)]
        order = {item["code"]: index for index, item in enumerate(DEFAULT_ETF_UNIVERSE)}
        values.sort(key=lambda item: (order.get(item["code"], 10_000), item.get("group", ""), item["code"]))
        return values

    async def active_rotation_codes(self, user_id: str) -> List[str]:
        items = await self.list_universe(user_id, include_inactive=False)
        return [item["code"] for item in items if item.get("group") != "cash_watch" and item.get("active", True)]

    async def upsert_item(self, user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        await self.ensure_indexes()
        now = datetime.utcnow()
        code = normalize_etf_code(payload.get("code"))
        doc = {
            "user_id": user_id,
            "code": code,
            "name": str(payload.get("name") or code).strip(),
            "group": normalize_etf_group(payload.get("group")),
            "active": bool(payload.get("active", True)),
            "source": str(payload.get("source") or "manual"),
            "tags": normalize_tags(payload.get("tags")),
            "note": str(payload.get("note") or "").strip(),
            "updated_at": now,
        }
        existing = await self.items.find_one({"user_id": user_id, "code": code}, {"_id": 0, "created_at": 1})
        doc["created_at"] = existing.get("created_at") if existing else now
        await self.items.update_one({"user_id": user_id, "code": code}, {"$set": doc}, upsert=True)
        return self._normalize_item({**doc, "is_default": code in {item["code"] for item in DEFAULT_ETF_UNIVERSE}})

    async def update_item(self, user_id: str, code: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        await self.ensure_indexes()
        normalized_code = normalize_etf_code(code)
        allowed: Dict[str, Any] = {"updated_at": datetime.utcnow()}
        if "name" in updates and updates["name"] is not None:
            allowed["name"] = str(updates["name"]).strip() or normalized_code
        if "group" in updates and updates["group"] is not None:
            allowed["group"] = normalize_etf_group(updates["group"])
        if "active" in updates and updates["active"] is not None:
            allowed["active"] = bool(updates["active"])
        if "tags" in updates and updates["tags"] is not None:
            allowed["tags"] = normalize_tags(updates["tags"])
        if "note" in updates and updates["note"] is not None:
            allowed["note"] = str(updates["note"]).strip()

        default = next((item for item in DEFAULT_ETF_UNIVERSE if item["code"] == normalized_code), None)
        set_on_insert = {
            "user_id": user_id,
            "code": normalized_code,
            "name": default["name"] if default else normalized_code,
            "group": default["group"] if default else "sector",
            "source": "manual",
            "created_at": datetime.utcnow(),
        }
        for key in allowed:
            set_on_insert.pop(key, None)
        await self.items.update_one(
            {"user_id": user_id, "code": normalized_code},
            {"$set": allowed, "$setOnInsert": set_on_insert},
            upsert=True,
        )
        item = await self.items.find_one({"user_id": user_id, "code": normalized_code}, {"_id": 0})
        if not item:
            raise ValueError("ETF item not found")
        normalized = self._normalize_item(item)
        normalized["is_default"] = default is not None
        return normalized

    async def refresh_basic_info(self, source: str = "akshare") -> Dict[str, Any]:
        saved = await self.etf_data.refresh_basic_info(source=source)
        return {"source": source, "saved": saved}

    async def search_basic(self, query: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        await self.ensure_indexes()
        limit = max(1, min(int(limit or 50), 200))
        text = str(query or "").strip()
        mongo_query: Dict[str, Any] = {}
        if text:
            mongo_query = {
                "$or": [
                    {"code": {"$regex": re.escape(text), "$options": "i"}},
                    {"name": {"$regex": re.escape(text), "$options": "i"}},
                ]
            }
        cursor = self.etf_data.basic_collection.find(mongo_query, {"_id": 0}).sort("amount", -1).limit(limit)
        rows = await cursor.to_list(None)
        if rows:
            return [self._normalize_basic(row) for row in rows]

        defaults = [self._default_item(item) for item in DEFAULT_ETF_UNIVERSE]
        if text:
            defaults = [
                item for item in defaults if text.lower() in item["code"].lower() or text.lower() in item["name"].lower()
            ]
        return defaults[:limit]

    def _default_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "code": normalize_etf_code(item.get("code")),
            "name": str(item.get("name") or item.get("code")),
            "group": normalize_etf_group(item.get("group")),
            "active": True,
            "source": "default",
            "tags": [],
            "note": "",
            "is_default": True,
        }

    def _normalize_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(item)
        result.pop("_id", None)
        result["code"] = normalize_etf_code(result.get("code"))
        result["name"] = str(result.get("name") or result["code"])
        result["group"] = normalize_etf_group(result.get("group"))
        result["active"] = bool(result.get("active", True))
        result["source"] = str(result.get("source") or "manual")
        result["tags"] = normalize_tags(result.get("tags"))
        result["note"] = str(result.get("note") or "")
        result.setdefault("is_default", False)
        return result

    def _normalize_basic(self, item: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(item)
        result.pop("_id", None)
        result["code"] = normalize_etf_code(result.get("code"))
        result["name"] = str(result.get("name") or result["code"])
        result["group"] = normalize_etf_group(result.get("group"))
        result["active"] = True
        result["is_default"] = result["code"] in {item["code"] for item in DEFAULT_ETF_UNIVERSE}
        return result
