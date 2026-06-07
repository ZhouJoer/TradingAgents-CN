from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bson import ObjectId
from fastapi import HTTPException

from app.core.database import get_mongo_db
from app.utils.timezone import now_tz


CORE_REVIEW_MODULES = (
    "market_report",
    "fundamentals_report",
    "news_report",
    "investment_plan",
    "trader_investment_plan",
    "final_trade_decision",
)

EXCLUDED_REVIEW_MODULES = (
    "research_team_decision",
    "risk_management_decision",
)


def _build_report_query(report_id: str) -> Dict[str, Any]:
    ors: List[Dict[str, Any]] = [
        {"analysis_id": report_id},
        {"task_id": report_id},
    ]
    try:
        ors.append({"_id": ObjectId(report_id)})
    except Exception:
        pass
    return {"$or": ors}


def _jsonable(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(_jsonable(value), ensure_ascii=False)


def _parse_json_object(text: str) -> Dict[str, Any]:
    cleaned = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def _estimate_tokens_cn(text: str) -> int:
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    ascii_chars = sum(1 for ch in text if ord(ch) < 128 and not ch.isspace())
    other = max(0, len(text) - cjk - ascii_chars)
    return int(cjk + ascii_chars / 4 + other * 0.6)


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


class ReportReviewService:
    """Report snapshot, comparison, review task, and LLM review helpers."""

    def __init__(self) -> None:
        self.db = get_mongo_db()

    async def resolve_report(self, report_id: str, user: dict) -> Dict[str, Any]:
        doc = await self.db.analysis_reports.find_one(_build_report_query(report_id))
        if doc:
            await self._assert_report_access(doc, user)
            return self._normalize_report_doc(doc)

        task_doc = await self.db.analysis_tasks.find_one(
            {"$or": [{"task_id": report_id}, {"result.analysis_id": report_id}]}
        )
        if not task_doc or not task_doc.get("result"):
            raise HTTPException(status_code=404, detail="报告不存在")
        await self._assert_task_access(task_doc, user)
        return self._normalize_task_result(task_doc, report_id)

    async def get_or_create_snapshot(
        self,
        report_id: str,
        user: dict,
        regenerate: bool = False,
    ) -> Dict[str, Any]:
        report = await self.resolve_report(report_id, user)
        report_hash = self._hash_report(report)
        existing = await self.db.analysis_report_snapshots.find_one(
            {"report_id": report["id"], "report_hash": report_hash}
        )
        if existing and not regenerate:
            return _jsonable(existing)

        snapshot = self._build_snapshot(report, user, report_hash)
        await self.db.analysis_report_snapshots.update_one(
            {"report_id": report["id"]},
            {"$set": snapshot},
            upsert=True,
        )
        saved = await self.db.analysis_report_snapshots.find_one({"report_id": report["id"]})
        return _jsonable(saved or snapshot)

    async def get_stock_timeline(self, stock_symbol: str, user: dict, limit: int = 10) -> Dict[str, Any]:
        query: Dict[str, Any] = {"stock_symbol": str(stock_symbol).zfill(6)}
        accessible: List[Dict[str, Any]] = []
        cursor = self.db.analysis_reports.find(query).sort("created_at", -1).limit(max(1, min(limit, 50)))
        async for doc in cursor:
            try:
                await self._assert_report_access(doc, user)
            except HTTPException:
                continue
            snapshot = await self.get_or_create_snapshot(str(doc["_id"]), user)
            accessible.append(
                {
                    "report_id": snapshot.get("report_id"),
                    "analysis_id": snapshot.get("analysis_id"),
                    "created_at": snapshot.get("created_at"),
                    "analysis_date": snapshot.get("analysis_date"),
                    "viewpoint": snapshot.get("viewpoint", {}),
                    "summary": snapshot.get("summary", ""),
                    "review_status": None,
                }
            )
        return {"stock_symbol": query["stock_symbol"], "items": accessible}

    async def compare_reports(self, base_report_id: str, current_report_id: str, user: dict) -> Dict[str, Any]:
        base = await self.get_or_create_snapshot(base_report_id, user)
        current = await self.get_or_create_snapshot(current_report_id, user)
        if base.get("stock_symbol") != current.get("stock_symbol"):
            raise HTTPException(status_code=400, detail="只能对比同一只股票的报告")

        cache_query = {
            "base_report_id": base.get("report_id"),
            "current_report_id": current.get("report_id"),
            "base_report_hash": base.get("report_hash"),
            "current_report_hash": current.get("report_hash"),
        }
        cached = await self.db.analysis_report_comparisons.find_one(cache_query)
        if cached:
            return _jsonable(cached)

        comparison = self._build_comparison(base, current, user)
        await self.db.analysis_report_comparisons.insert_one(comparison)
        return _jsonable(comparison)

    async def latest_comparison(self, stock_symbol: str, user: dict) -> Dict[str, Any]:
        query = {"stock_symbol": str(stock_symbol).zfill(6)}
        docs: List[Dict[str, Any]] = []
        cursor = self.db.analysis_reports.find(query).sort("created_at", -1).limit(6)
        async for doc in cursor:
            try:
                await self._assert_report_access(doc, user)
            except HTTPException:
                continue
            docs.append(doc)
            if len(docs) >= 2:
                break

        if len(docs) < 2:
            return {"comparison_available": False, "stock_symbol": query["stock_symbol"], "message": "历史报告不足两份"}

        comparison = await self.compare_reports(str(docs[1]["_id"]), str(docs[0]["_id"]), user)
        comparison["comparison_available"] = True
        return comparison

    async def create_review_task(
        self,
        report_id: str,
        user: dict,
        review_window_days: int = 30,
        review_mode: str = "hybrid",
    ) -> Dict[str, Any]:
        snapshot = await self.get_or_create_snapshot(report_id, user)
        existing = await self.db.analysis_review_tasks.find_one(
            {
                "source_report_id": snapshot.get("report_id"),
                "user_id": str(user.get("id")),
                "status": {"$in": ["pending", "running", "completed"]},
            }
        )
        if existing:
            return _jsonable(existing)

        now = now_tz()
        due_at = now + timedelta(days=max(1, min(review_window_days, 365)))
        task = {
            "review_id": str(uuid.uuid4()),
            "source_report_id": snapshot.get("report_id"),
            "snapshot_id": snapshot.get("snapshot_id"),
            "user_id": str(user.get("id")),
            "stock_symbol": snapshot.get("stock_symbol"),
            "stock_name": snapshot.get("stock_name"),
            "status": "pending",
            "review_mode": review_mode if review_mode in {"rule_only", "llm_judge", "hybrid"} else "hybrid",
            "review_window_days": review_window_days,
            "due_at": due_at,
            "items": self._build_review_items(snapshot),
            "evidence_pack_id": None,
            "latest_evaluation_id": None,
            "overall_review_result": None,
            "needs_manual_review": False,
            "manual_notes": "",
            "created_at": now,
            "updated_at": now,
        }
        await self.db.analysis_review_tasks.insert_one(task)
        return _jsonable(task)

    async def list_review_tasks(
        self,
        user: dict,
        stock_symbol: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        query: Dict[str, Any] = {}
        if not user.get("is_admin"):
            query["user_id"] = str(user.get("id"))
        if stock_symbol:
            query["stock_symbol"] = str(stock_symbol).zfill(6)
        if status:
            query["status"] = status
        total = await self.db.analysis_review_tasks.count_documents(query)
        cursor = (
            self.db.analysis_review_tasks.find(query)
            .sort("created_at", -1)
            .skip(max(0, offset))
            .limit(max(1, min(limit, 100)))
        )
        items = [_jsonable(doc) async for doc in cursor]
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    async def get_review_task(self, review_id: str, user: dict) -> Dict[str, Any]:
        task = await self._get_review_task_doc(review_id, user)
        result = _jsonable(task)
        if task.get("latest_evaluation_id"):
            evaluation = await self.db.analysis_review_evaluations.find_one(
                {"evaluation_id": task.get("latest_evaluation_id")}
            )
            result["latest_evaluation"] = _jsonable(evaluation) if evaluation else None
        return result

    async def run_review_task(self, review_id: str, user: dict) -> Dict[str, Any]:
        task = await self._get_review_task_doc(review_id, user)
        snapshot = await self.db.analysis_report_snapshots.find_one({"snapshot_id": task.get("snapshot_id")})
        if not snapshot:
            snapshot = await self.get_or_create_snapshot(task["source_report_id"], user)

        await self.db.analysis_review_tasks.update_one(
            {"review_id": review_id},
            {"$set": {"status": "running", "updated_at": now_tz()}},
        )

        evidence_pack = await self._build_evidence_pack(task, snapshot, user)
        updated_items = self._evaluate_rule_items(task.get("items", []), evidence_pack)
        overall = self._build_rule_overall(updated_items)

        await self.db.analysis_evidence_packs.update_one(
            {"evidence_pack_id": evidence_pack["evidence_pack_id"]},
            {"$set": evidence_pack},
            upsert=True,
        )
        await self.db.analysis_review_tasks.update_one(
            {"review_id": review_id},
            {
                "$set": {
                    "status": "completed",
                    "items": updated_items,
                    "evidence_pack_id": evidence_pack["evidence_pack_id"],
                    "overall_review_result": overall,
                    "updated_at": now_tz(),
                }
            },
        )
        return await self.get_review_task(review_id, user)

    async def llm_evaluate_review_task(self, review_id: str, user: dict) -> Dict[str, Any]:
        task = await self._get_review_task_doc(review_id, user)
        evidence_pack = None
        if task.get("evidence_pack_id"):
            evidence_pack = await self.db.analysis_evidence_packs.find_one(
                {"evidence_pack_id": task.get("evidence_pack_id")}
            )
        if not evidence_pack:
            await self.run_review_task(review_id, user)
            task = await self._get_review_task_doc(review_id, user)
            evidence_pack = await self.db.analysis_evidence_packs.find_one(
                {"evidence_pack_id": task.get("evidence_pack_id")}
            )

        evaluation_id = str(uuid.uuid4())
        created_at = now_tz()
        evidence_hash = hashlib.sha256(
            json.dumps(_jsonable(evidence_pack), ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

        try:
            llm, model_info = self._create_review_llm()
            prompt = self._build_llm_review_prompt(evidence_pack)
            response_text = await self._invoke_llm(llm, prompt)
            parsed = _parse_json_object(response_text)
            status = "completed"
            error = None
        except Exception as exc:
            response_text = locals().get("response_text", "")
            model_info = locals().get("model_info", {"provider": "unknown", "model": "unknown"})
            parsed = {
                "overall_verdict": "unverifiable",
                "scores": {},
                "dimension_reviews": {},
                "summary": "LLM评审失败，已保留规则复盘和证据包。",
            }
            status = "failed"
            error = str(exc)

        evaluation = {
            "evaluation_id": evaluation_id,
            "review_id": review_id,
            "report_id": task.get("source_report_id"),
            "stock_symbol": task.get("stock_symbol"),
            "model_provider": model_info.get("provider"),
            "model_name": model_info.get("model"),
            "prompt_version": "review_judge_v1",
            "evidence_pack_hash": evidence_hash,
            "raw_response": response_text,
            "parsed_result": parsed,
            "status": status,
            "error": error,
            "created_at": created_at,
        }
        await self.db.analysis_review_evaluations.insert_one(evaluation)
        await self.db.analysis_review_tasks.update_one(
            {"review_id": review_id},
            {
                "$set": {
                    "latest_evaluation_id": evaluation_id,
                    "overall_review_result": parsed,
                    "updated_at": now_tz(),
                }
            },
        )
        return _jsonable(evaluation)

    async def update_manual_result(self, review_id: str, user: dict, notes: str, outcome: Optional[str] = None) -> Dict[str, Any]:
        await self._get_review_task_doc(review_id, user)
        update: Dict[str, Any] = {
            "manual_notes": notes,
            "needs_manual_review": False,
            "updated_at": now_tz(),
        }
        if outcome:
            update["manual_outcome"] = outcome
        await self.db.analysis_review_tasks.update_one({"review_id": review_id}, {"$set": update})
        return await self.get_review_task(review_id, user)

    async def get_evaluation(self, evaluation_id: str, user: dict) -> Dict[str, Any]:
        evaluation = await self.db.analysis_review_evaluations.find_one({"evaluation_id": evaluation_id})
        if not evaluation:
            raise HTTPException(status_code=404, detail="评审记录不存在")
        await self._get_review_task_doc(evaluation["review_id"], user)
        return _jsonable(evaluation)

    async def _assert_report_access(self, report: Dict[str, Any], user: dict) -> None:
        if user.get("is_admin"):
            return
        report_user_id = _first_non_empty(report.get("user_id"), report.get("owner_id"))
        if report_user_id and str(report_user_id) != str(user.get("id")):
            raise HTTPException(status_code=403, detail="无权访问该报告")
        if report_user_id:
            return
        task_id = report.get("task_id")
        if task_id:
            task = await self.db.analysis_tasks.find_one({"task_id": task_id}, {"user_id": 1})
            if task and task.get("user_id") and str(task.get("user_id")) != str(user.get("id")):
                raise HTTPException(status_code=403, detail="无权访问该报告")

    async def _assert_task_access(self, task: Dict[str, Any], user: dict) -> None:
        if user.get("is_admin"):
            return
        if task.get("user_id") and str(task.get("user_id")) != str(user.get("id")):
            raise HTTPException(status_code=403, detail="无权访问该报告")

    def _normalize_report_doc(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(doc)
        result["id"] = str(doc.get("_id"))
        result["reports"] = doc.get("reports") or {}
        return result

    def _normalize_task_result(self, task_doc: Dict[str, Any], report_id: str) -> Dict[str, Any]:
        result = dict(task_doc.get("result") or {})
        result["id"] = task_doc.get("task_id", report_id)
        result["task_id"] = task_doc.get("task_id", report_id)
        result["stock_symbol"] = result.get("stock_symbol") or result.get("stock_code") or task_doc.get("stock_code")
        result["created_at"] = task_doc.get("created_at")
        result["updated_at"] = task_doc.get("completed_at") or task_doc.get("created_at")
        result["reports"] = result.get("reports") or {}
        return result

    def _hash_report(self, report: Dict[str, Any]) -> str:
        payload = {
            "id": report.get("id"),
            "recommendation": report.get("recommendation"),
            "risk_level": report.get("risk_level"),
            "confidence_score": report.get("confidence_score"),
            "summary": report.get("summary"),
            "key_points": report.get("key_points"),
            "reports": {
                key: _text((report.get("reports") or {}).get(key))
                for key in CORE_REVIEW_MODULES
            },
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def _build_snapshot(self, report: Dict[str, Any], user: dict, report_hash: str) -> Dict[str, Any]:
        modules = report.get("reports") or {}
        core_text = self._build_core_report_text(report)
        assumptions = self._extract_assumptions(core_text, report.get("key_points") or [])
        technical_claims = self._extract_claims_by_keywords(
            _text(modules.get("market_report")),
            ("均线", "趋势", "MACD", "RSI", "支撑", "压力", "成交量", "突破", "回撤"),
            "technical",
        )
        fundamental_claims = self._extract_claims_by_keywords(
            _text(modules.get("fundamentals_report")),
            ("营收", "净利", "毛利", "ROE", "PE", "PB", "估值", "负债", "现金流", "成长"),
            "fundamental",
        )
        news_claims = self._extract_claims_by_keywords(
            _text(modules.get("news_report")),
            ("公告", "政策", "订单", "合作", "中标", "监管", "新闻", "利好", "利空"),
            "news",
        )
        now = now_tz()
        return {
            "snapshot_id": str(uuid.uuid4()),
            "report_id": report.get("id"),
            "analysis_id": report.get("analysis_id"),
            "task_id": report.get("task_id"),
            "user_id": str(_first_non_empty(report.get("user_id"), user.get("id"))),
            "stock_symbol": str(report.get("stock_symbol") or "").zfill(6),
            "stock_name": report.get("stock_name"),
            "market_type": report.get("market_type"),
            "analysis_date": report.get("analysis_date"),
            "created_at": _first_non_empty(report.get("created_at"), now),
            "updated_at": now,
            "model_info": report.get("model_info"),
            "research_depth": report.get("research_depth"),
            "viewpoint": {
                "action": report.get("recommendation") or self._infer_action(core_text),
                "confidence_score": report.get("confidence_score"),
                "risk_level": report.get("risk_level"),
                "summary": report.get("summary") or self._first_sentence(core_text),
            },
            "summary": report.get("summary") or self._first_sentence(core_text),
            "key_points": report.get("key_points") or [],
            "key_assumptions": assumptions,
            "claims": {
                "fundamental": fundamental_claims,
                "news": news_claims,
                "technical": technical_claims,
            },
            "tracking_indicators": self._extract_tracking_indicators(core_text),
            "risk_triggers": self._extract_risk_triggers(core_text),
            "source_report_modules": {
                key: bool(_text(modules.get(key)))
                for key in CORE_REVIEW_MODULES
            },
            "excluded_modules": list(EXCLUDED_REVIEW_MODULES),
            "estimated_core_tokens": _estimate_tokens_cn(core_text),
            "report_hash": report_hash,
        }

    def _build_comparison(self, base: Dict[str, Any], current: Dict[str, Any], user: dict) -> Dict[str, Any]:
        base_view = base.get("viewpoint") or {}
        current_view = current.get("viewpoint") or {}
        changed_assumptions = self._diff_text_items(
            [item.get("text", "") for item in base.get("key_assumptions", [])],
            [item.get("text", "") for item in current.get("key_assumptions", [])],
        )
        risk_changes = self._diff_text_items(
            [item.get("condition", item.get("name", "")) for item in base.get("risk_triggers", [])],
            [item.get("condition", item.get("name", "")) for item in current.get("risk_triggers", [])],
        )
        summary = self._comparison_summary(base_view, current_view, changed_assumptions, risk_changes)
        return {
            "comparison_id": str(uuid.uuid4()),
            "user_id": str(user.get("id")),
            "stock_symbol": current.get("stock_symbol"),
            "base_report_id": base.get("report_id"),
            "current_report_id": current.get("report_id"),
            "base_report_hash": base.get("report_hash"),
            "current_report_hash": current.get("report_hash"),
            "created_at": now_tz(),
            "viewpoint_change": {
                "from_action": base_view.get("action"),
                "to_action": current_view.get("action"),
                "confidence_delta": self._numeric_delta(base_view.get("confidence_score"), current_view.get("confidence_score")),
                "risk_level_change": f"{base_view.get('risk_level') or '-'} -> {current_view.get('risk_level') or '-'}",
            },
            "changed_assumptions": changed_assumptions,
            "risk_changes": risk_changes,
            "claim_changes": {
                dimension: self._diff_text_items(
                    [item.get("text", "") for item in (base.get("claims", {}).get(dimension) or [])],
                    [item.get("text", "") for item in (current.get("claims", {}).get(dimension) or [])],
                )
                for dimension in ("fundamental", "news", "technical")
            },
            "summary": summary,
        }

    async def _build_evidence_pack(self, task: Dict[str, Any], snapshot: Dict[str, Any], user: dict) -> Dict[str, Any]:
        report = await self.resolve_report(task["source_report_id"], user)
        stock_symbol = snapshot.get("stock_symbol")
        now = now_tz()
        quote = await self._get_quote_evidence(stock_symbol)
        fundamentals = await self._get_fundamental_evidence(stock_symbol)
        news = await self._get_news_evidence(stock_symbol, limit=30)
        technical = await self._get_technical_evidence(stock_symbol)
        core_text = self._build_core_report_text(report)
        return {
            "evidence_pack_id": str(uuid.uuid4()),
            "review_id": task.get("review_id"),
            "report_id": task.get("source_report_id"),
            "stock_symbol": stock_symbol,
            "created_at": now,
            "report_context": {
                "analysis_date": snapshot.get("analysis_date"),
                "created_at": snapshot.get("created_at"),
                "viewpoint": snapshot.get("viewpoint"),
                "key_assumptions": snapshot.get("key_assumptions", []),
                "claims": snapshot.get("claims", {}),
                "risk_triggers": snapshot.get("risk_triggers", []),
                "core_modules_used": list(CORE_REVIEW_MODULES),
                "modules_excluded": list(EXCLUDED_REVIEW_MODULES),
                "core_report_text": core_text[:50000],
                "estimated_core_tokens": _estimate_tokens_cn(core_text),
            },
            "quote_evidence": quote,
            "fundamental_evidence": fundamentals,
            "news_evidence": news,
            "technical_evidence": technical,
            "data_quality": self._data_quality(quote, fundamentals, news, technical),
        }

    def _build_core_report_text(self, report: Dict[str, Any]) -> str:
        reports = report.get("reports") or {}
        parts = []
        if report.get("summary"):
            parts.append(f"# summary\n{_text(report.get('summary'))}")
        if report.get("recommendation"):
            parts.append(f"# recommendation\n{_text(report.get('recommendation'))}")
        for key in CORE_REVIEW_MODULES:
            content = _text(reports.get(key))
            if content:
                parts.append(f"# {key}\n{content}")
        return "\n\n".join(parts)

    async def _get_quote_evidence(self, stock_symbol: str) -> Dict[str, Any]:
        quote = await self.db.market_quotes.find_one({"code": stock_symbol}, {"_id": 0})
        if not quote:
            return {"status": "data_missing", "message": "未找到最新行情"}
        return {"status": "ok", "data": _jsonable(quote)}

    async def _get_fundamental_evidence(self, stock_symbol: str) -> Dict[str, Any]:
        basic = await self.db.stock_basic_info.find_one({"code": stock_symbol}, {"_id": 0}, sort=[("updated_at", -1)])
        financial = await self.db.stock_financial_data.find_one(
            {"$or": [{"code": stock_symbol}, {"symbol": stock_symbol}]},
            {"_id": 0},
            sort=[("report_period", -1)],
        )
        if not basic and not financial:
            return {"status": "data_missing", "message": "未找到基本面/财务数据"}
        return {"status": "ok", "basic": _jsonable(basic or {}), "financial": _jsonable(financial or {})}

    async def _get_news_evidence(self, stock_symbol: str, limit: int = 30) -> Dict[str, Any]:
        cursor = self.db.stock_news.find(
            {"$or": [{"symbol": stock_symbol}, {"symbols": stock_symbol}]},
            {"_id": 0, "title": 1, "summary": 1, "content": 1, "source": 1, "url": 1, "publish_time": 1, "sentiment": 1, "importance": 1},
        ).sort("publish_time", -1).limit(limit)
        items = []
        idx = 1
        async for item in cursor:
            item = _jsonable(item)
            item["evidence_id"] = f"news_{idx}"
            idx += 1
            items.append(item)
        return {"status": "ok" if items else "data_missing", "items": items}

    async def _get_technical_evidence(self, stock_symbol: str) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        try:
            from tradingagents.dataflows.cache.mongodb_cache_adapter import get_mongodb_cache_adapter

            adapter = get_mongodb_cache_adapter()
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=240)).strftime("%Y-%m-%d")
            df = await asyncio.to_thread(adapter.get_historical_data, stock_symbol, start_date, end_date, "daily")
            if df is not None and not df.empty:
                for _, row in df.tail(120).iterrows():
                    items.append(
                        {
                            "time": str(row.get("trade_date", row.get("date", ""))),
                            "close": self._to_float(row.get("close")),
                            "volume": self._to_float(row.get("volume", row.get("vol"))),
                        }
                    )
        except Exception:
            items = []

        if not items:
            quote = await self.db.market_quotes.find_one({"code": stock_symbol}, {"_id": 0})
            if quote:
                return {
                    "status": "partial",
                    "message": "未找到连续K线，仅使用最新行情",
                    "latest_quote": _jsonable(quote),
                }
            return {"status": "data_missing", "message": "未找到K线或行情数据"}

        closes = [item["close"] for item in items if item.get("close") is not None]
        summary = {
            "latest_close": closes[-1] if closes else None,
            "return_20d_pct": self._return_pct(closes[-21], closes[-1]) if len(closes) >= 21 else None,
            "return_60d_pct": self._return_pct(closes[-61], closes[-1]) if len(closes) >= 61 else None,
            "ma20": self._mean(closes[-20:]) if len(closes) >= 20 else None,
            "ma60": self._mean(closes[-60:]) if len(closes) >= 60 else None,
            "max_drawdown_pct": self._max_drawdown(closes),
        }
        return {"status": "ok", "summary": summary, "recent_bars": items[-30:]}

    def _data_quality(self, *sections: Dict[str, Any]) -> Dict[str, Any]:
        missing = [section.get("message", "数据缺失") for section in sections if section.get("status") == "data_missing"]
        return {"missing_count": len(missing), "missing_notes": missing}

    def _build_llm_review_prompt(self, evidence_pack: Dict[str, Any]) -> str:
        compact_pack = dict(evidence_pack)
        return f"""你是股票研究复盘审稿人，不是荐股助手。

任务：
1. 对比原报告判断和当前证据，评估原分析是否合理。
2. 分别评价基本面、新闻面、技术面、风险意识和最终建议。
3. 必须区分“过程合理但结果不好”和“依据不足导致判断错误”。
4. 只能基于证据包判断；数据缺失时输出 unverifiable，不能编造事实。
5. 结论不是投资建议，只是研究质量复盘。

输出严格 JSON，不要 Markdown。JSON 结构：
{{
  "overall_verdict": "correct|partially_correct|incorrect|unverifiable|too_early",
  "scores": {{
    "overall_score": 0,
    "evidence_grounding_score": 0,
    "logic_quality_score": 0,
    "fundamental_correctness_score": 0,
    "news_correctness_score": 0,
    "technical_correctness_score": 0,
    "risk_awareness_score": 0
  }},
  "dimension_reviews": {{
    "fundamental": {{"verdict": "", "score": 0, "what_was_claimed": "", "what_happened": "", "supporting_evidence_ids": [], "contradicting_evidence_ids": [], "reasoning": "", "missed_signals": [], "improvement_suggestions": []}},
    "news": {{"verdict": "", "score": 0, "what_was_claimed": "", "what_happened": "", "supporting_evidence_ids": [], "contradicting_evidence_ids": [], "reasoning": "", "missed_signals": [], "improvement_suggestions": []}},
    "technical": {{"verdict": "", "score": 0, "what_was_claimed": "", "what_happened": "", "supporting_evidence_ids": [], "contradicting_evidence_ids": [], "reasoning": "", "missed_signals": [], "improvement_suggestions": []}},
    "risk": {{"verdict": "", "score": 0, "reasoning": "", "improvement_suggestions": []}},
    "final_recommendation": {{"verdict": "", "score": 0, "reasoning": "", "improvement_suggestions": []}}
  }},
  "summary": "",
  "lessons": []
}}

证据包：
{json.dumps(_jsonable(compact_pack), ensure_ascii=False)}
"""

    def _create_review_llm(self) -> Tuple[Any, Dict[str, str]]:
        from app.services.llm_config_service import build_llm_provider_config, validate_llm_provider_config
        from tradingagents.graph.trading_graph import create_llm_by_provider

        config = build_llm_provider_config(research_depth="深度")
        validate_llm_provider_config(config)
        provider = config.get("deep_provider") or config.get("llm_provider")
        model = config.get("deep_think_llm")
        llm = create_llm_by_provider(
            provider=provider,
            model=model,
            backend_url=config.get("deep_backend_url") or config.get("backend_url") or "",
            temperature=0.2,
            max_tokens=4096,
            timeout=180,
            api_key=config.get("deep_api_key") or config.get("api_key"),
        )
        return llm, {"provider": provider, "model": model}

    async def _invoke_llm(self, llm: Any, prompt: str) -> str:
        if hasattr(llm, "ainvoke"):
            response = await llm.ainvoke(prompt)
        else:
            response = await asyncio.to_thread(llm.invoke, prompt)
        content = getattr(response, "content", response)
        if isinstance(content, list):
            return "\n".join(str(item.get("text", item)) if isinstance(item, dict) else str(item) for item in content)
        return str(content)

    async def _get_review_task_doc(self, review_id: str, user: dict) -> Dict[str, Any]:
        task = await self.db.analysis_review_tasks.find_one({"review_id": review_id})
        if not task:
            raise HTTPException(status_code=404, detail="复盘任务不存在")
        if not user.get("is_admin") and str(task.get("user_id")) != str(user.get("id")):
            raise HTTPException(status_code=403, detail="无权访问该复盘任务")
        return task

    def _extract_assumptions(self, text: str, key_points: Iterable[Any]) -> List[Dict[str, Any]]:
        items: List[str] = [str(item).strip() for item in key_points if str(item).strip()]
        lines = [line.strip(" -#*>\t") for line in text.splitlines()]
        keywords = ("假设", "前提", "预期", "如果", "若", "关注", "跟踪", "验证", "兑现", "改善", "修复")
        for line in lines:
            if 12 <= len(line) <= 180 and any(word in line for word in keywords):
                items.append(line)
        return [
            {"id": f"a{i+1}", "text": value, "category": self._classify_claim(value), "status": "pending"}
            for i, value in enumerate(self._dedupe(items)[:16])
        ]

    def _extract_claims_by_keywords(self, text: str, keywords: Tuple[str, ...], category: str) -> List[Dict[str, Any]]:
        claims = []
        for line in text.splitlines():
            line = line.strip(" -#*>\t")
            if 12 <= len(line) <= 220 and any(word.lower() in line.lower() for word in keywords):
                claims.append(line)
        return [
            {"id": f"{category}_{i+1}", "text": value, "category": category}
            for i, value in enumerate(self._dedupe(claims)[:12])
        ]

    def _extract_tracking_indicators(self, text: str) -> List[Dict[str, Any]]:
        indicators: List[Dict[str, Any]] = []
        for label in ("目标价", "支撑位", "压力位", "止损", "止盈"):
            match = re.search(rf"{label}[格位]?[：:\s]*([0-9]+(?:\.[0-9]+)?)", text)
            if match:
                indicators.append(
                    {
                        "name": label,
                        "type": "price",
                        "threshold": float(match.group(1)),
                        "unit": "CNY",
                        "direction": "above" if label in {"目标价", "压力位", "止盈"} else "below",
                    }
                )
        return indicators

    def _extract_risk_triggers(self, text: str) -> List[Dict[str, Any]]:
        lines = []
        for line in text.splitlines():
            cleaned = line.strip(" -#*>\t")
            if 12 <= len(cleaned) <= 180 and any(word in cleaned for word in ("风险", "跌破", "不及预期", "恶化", "失效", "止损")):
                lines.append(cleaned)
        return [
            {"id": f"r{i+1}", "name": "风险触发", "type": "manual", "condition": value, "severity": "medium"}
            for i, value in enumerate(self._dedupe(lines)[:12])
        ]

    def _build_review_items(self, snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for indicator in snapshot.get("tracking_indicators", []):
            items.append(
                {
                    "item_id": str(uuid.uuid4()),
                    "type": indicator.get("type", "manual"),
                    "description": f"检查{indicator.get('name')}是否满足 {indicator.get('direction')} {indicator.get('threshold')}",
                    "condition": indicator,
                    "baseline": indicator.get("baseline"),
                    "result": "pending",
                    "evidence": [],
                }
            )
        for assumption in snapshot.get("key_assumptions", [])[:8]:
            items.append(
                {
                    "item_id": str(uuid.uuid4()),
                    "type": assumption.get("category", "manual"),
                    "description": assumption.get("text"),
                    "condition": None,
                    "baseline": None,
                    "result": "pending_manual",
                    "evidence": [],
                }
            )
        return items

    def _evaluate_rule_items(self, items: List[Dict[str, Any]], evidence_pack: Dict[str, Any]) -> List[Dict[str, Any]]:
        quote = evidence_pack.get("quote_evidence", {}).get("data", {})
        price = self._to_float(_first_non_empty(quote.get("close"), quote.get("price")))
        updated: List[Dict[str, Any]] = []
        for item in items:
            next_item = dict(item)
            condition = next_item.get("condition") or {}
            if next_item.get("type") == "price" and price is not None and condition.get("threshold") is not None:
                threshold = self._to_float(condition.get("threshold"))
                direction = condition.get("direction")
                hit = price >= threshold if direction == "above" else price <= threshold
                next_item.update(
                    {
                        "actual_value": price,
                        "result": "hit" if hit else "miss",
                        "evidence": [{"type": "quote", "value": price, "threshold": threshold}],
                    }
                )
            updated.append(next_item)
        return updated

    def _build_rule_overall(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        judged = [item for item in items if item.get("result") in {"hit", "miss"}]
        if not judged:
            return {"outcome": "inconclusive", "hit_rate": None, "summary": "暂无可自动判断的复盘项"}
        hit_count = sum(1 for item in judged if item.get("result") == "hit")
        hit_rate = round(hit_count / len(judged), 4)
        return {"outcome": "validated" if hit_rate >= 0.6 else "failed", "hit_rate": hit_rate, "summary": f"{hit_count}/{len(judged)} 个自动复盘项命中"}

    def _comparison_summary(
        self,
        base_view: Dict[str, Any],
        current_view: Dict[str, Any],
        assumptions: List[Dict[str, Any]],
        risks: List[Dict[str, Any]],
    ) -> str:
        parts = [
            f"观点从「{base_view.get('action') or '-'}」变为「{current_view.get('action') or '-'}」。",
            f"风险等级从「{base_view.get('risk_level') or '-'}」变为「{current_view.get('risk_level') or '-'}」。",
        ]
        if assumptions:
            parts.append(f"关键假设有 {len(assumptions)} 处变化。")
        if risks:
            parts.append(f"风险项有 {len(risks)} 处变化。")
        return "".join(parts)

    def _diff_text_items(self, previous: List[str], current: List[str]) -> List[Dict[str, Any]]:
        prev = set(self._dedupe(previous))
        curr = set(self._dedupe(current))
        changes = [{"change_type": "removed", "text": item} for item in sorted(prev - curr)]
        changes.extend({"change_type": "added", "text": item} for item in sorted(curr - prev))
        return changes[:20]

    def _classify_claim(self, text: str) -> str:
        if any(word in text for word in ("PE", "PB", "ROE", "营收", "净利", "毛利", "负债", "现金流", "估值")):
            return "fundamental"
        if any(word in text for word in ("新闻", "公告", "政策", "订单", "中标", "合作")):
            return "news"
        if any(word in text for word in ("均线", "MACD", "RSI", "支撑", "压力", "成交量", "趋势")):
            return "technical"
        if any(word in text for word in ("价格", "涨", "跌", "目标价", "止损")):
            return "price"
        return "manual"

    def _infer_action(self, text: str) -> str:
        for action in ("买入", "增持", "持有", "观望", "卖出", "减持"):
            if action in text:
                return action
        return "未提取"

    def _first_sentence(self, text: str) -> str:
        compact = re.sub(r"\s+", " ", text or "").strip()
        return compact[:240]

    def _dedupe(self, items: Iterable[str]) -> List[str]:
        result: List[str] = []
        seen = set()
        for item in items:
            value = re.sub(r"\s+", " ", str(item)).strip()
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _numeric_delta(self, base: Any, current: Any) -> Optional[float]:
        try:
            return round(float(current) - float(base), 4)
        except Exception:
            return None

    def _to_float(self, value: Any) -> Optional[float]:
        try:
            if value is None or (isinstance(value, float) and math.isnan(value)):
                return None
            return float(value)
        except Exception:
            return None

    def _mean(self, values: List[float]) -> Optional[float]:
        valid = [value for value in values if value is not None]
        return round(sum(valid) / len(valid), 4) if valid else None

    def _return_pct(self, start: float, end: float) -> Optional[float]:
        if start in (None, 0) or end is None:
            return None
        return round((end - start) / start * 100, 2)

    def _max_drawdown(self, closes: List[float]) -> Optional[float]:
        if not closes:
            return None
        peak = closes[0]
        max_dd = 0.0
        for close in closes:
            peak = max(peak, close)
            if peak:
                max_dd = min(max_dd, (close - peak) / peak)
        return round(max_dd * 100, 2)

