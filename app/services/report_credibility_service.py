from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

CORE_MODULE_LABELS = {
    "market_report": "市场技术分析缺失",
    "fundamentals_report": "基本面分析缺失",
    "news_report": "新闻分析缺失",
    "sentiment_report": "情绪分析缺失",
    "final_trade_decision": "最终交易决策缺失",
}

ANALYST_MODULES = {
    "market": "market_report",
    "fundamentals": "fundamentals_report",
    "news": "news_report",
    "social": "sentiment_report",
    "sentiment": "sentiment_report",
}

COUNTER_EVIDENCE_MODULES = (
    "bear_researcher",
    "safe_analyst",
    "neutral_analyst",
    "risk_management_decision",
    "final_trade_decision",
)

COUNTER_EVIDENCE_KEYWORDS = (
    "风险",
    "反对",
    "谨慎",
    "下行",
    "不确定",
    "压力",
    "负面",
    "卖出",
    "回避",
    "警惕",
    "高估",
    "下跌",
    "流动性",
    "替代",
    "竞争",
    "亏损",
    "止损",
)


class ReportCredibilityService:
    """Builds a deterministic credibility summary for report display/export."""

    def __init__(self, db: Any = None) -> None:
        if db is None:
            from app.core.database import get_mongo_db

            db = get_mongo_db()
        self.db = db

    async def build(self, report: Dict[str, Any]) -> Dict[str, Any]:
        stock_symbol = str(report.get("stock_symbol") or report.get("stock_code") or "").strip()
        reports = report.get("reports") or {}

        quote_doc = await self._find_stock_doc("market_quotes", stock_symbol)
        basic_doc = await self._find_stock_doc("stock_basic_info", stock_symbol)
        financial_doc = await self._find_stock_doc("stock_financial_data", stock_symbol)
        usage_records = await self._find_usage_records(report)
        enabled_sources = await self._get_enabled_sources()

        data_freshness = self._build_data_freshness(report, quote_doc, basic_doc, financial_doc)
        data_sources = self._build_data_sources(report, enabled_sources, quote_doc, basic_doc, financial_doc)
        missing_items = self._build_missing_items(report, reports)
        model_usage = self._build_model_usage(report, usage_records)
        confidence_basis = self._build_confidence_basis(report, data_freshness, data_sources, missing_items)
        counter_evidence = self._extract_counter_evidence(reports)

        return {
            "data_freshness": data_freshness,
            "data_sources": data_sources,
            "missing_items": missing_items,
            "model_usage": model_usage,
            "confidence_basis": confidence_basis,
            "counter_evidence": counter_evidence,
        }

    def format_markdown(self, credibility: Optional[Dict[str, Any]]) -> str:
        if not credibility:
            return ""

        freshness = credibility.get("data_freshness") or {}
        sources = credibility.get("data_sources") or {}
        usage = credibility.get("model_usage") or {}
        confidence = credibility.get("confidence_basis") or {}
        missing_items = credibility.get("missing_items") or []
        counter_evidence = credibility.get("counter_evidence") or []

        parts = [
            "## 可信度说明",
            "",
            f"- 数据新鲜度: {self._freshness_label(freshness.get('freshness_level'))}",
            f"- 分析日期: {freshness.get('analysis_date') or '未知'}",
            f"- 生成时间: {freshness.get('generated_at') or '未知'}",
            f"- 行情更新时间: {freshness.get('market_quote_updated_at') or '未知'}",
            f"- 基础信息更新时间: {freshness.get('stock_basic_updated_at') or '未知'}",
            f"- 财务数据更新时间: {freshness.get('financial_updated_at') or '未知'}",
            f"- 报告来源: {sources.get('report_source') or '未知'}",
            f"- 已启用数据源: {self._join_or_unknown(sources.get('enabled_sources'))}",
            f"- 可追踪数据源: {self._join_or_unknown(sources.get('observed_sources'))}",
            f"- 实际来源记录: {'是' if sources.get('actual_source_recorded') else '否'}",
            f"- 模型: {usage.get('model_info') or '未知'}",
            f"- Token: {usage.get('tokens_used') if usage.get('tokens_used') not in (None, '') else '未知'}",
            f"- 成本: {self._format_cost(usage)}",
            f"- 置信度: {confidence.get('label') or '未知'} ({self._format_confidence(confidence.get('confidence_score'))})",
            "",
        ]

        notes = freshness.get("notes") or []
        if notes:
            parts.extend(["### 新鲜度备注", ""])
            parts.extend(f"- {note}" for note in notes)
            parts.append("")

        parts.extend(["### 缺失项", ""])
        if missing_items:
            parts.extend(f"- [{item.get('severity', 'medium')}] {item.get('label')}: {item.get('reason')}" for item in missing_items)
        else:
            parts.append("- 未发现核心报告模块缺失。")
        parts.append("")

        parts.extend(["### 置信度依据", ""])
        positive = confidence.get("positive_factors") or []
        limiting = confidence.get("limiting_factors") or []
        parts.append("正向因素:")
        parts.extend(f"- {item}" for item in (positive or ["未记录明确正向依据。"]))
        parts.append("")
        parts.append("限制因素:")
        parts.extend(f"- {item}" for item in (limiting or ["未记录明确限制因素。"]))
        parts.append("")

        parts.extend(["### 关键反证", ""])
        if counter_evidence:
            parts.extend(
                f"- [{item.get('source_module')}] {item.get('text')}"
                for item in counter_evidence
            )
        else:
            parts.append("- 未提取到明确反证。")
        parts.append("")
        parts.append("---")
        parts.append("")

        return "\n".join(parts)

    async def _find_stock_doc(self, collection_name: str, stock_symbol: str) -> Optional[Dict[str, Any]]:
        if not stock_symbol:
            return None

        variants = self._symbol_variants(stock_symbol)
        query = {
            "$or": [
                {"code": {"$in": variants}},
                {"symbol": {"$in": variants}},
                {"stock_code": {"$in": variants}},
                {"stock_symbol": {"$in": variants}},
                {"full_symbol": {"$in": variants}},
                {"ts_code": {"$in": variants}},
            ]
        }
        sort = [
            ("updated_at", -1),
            ("timestamp", -1),
            ("trade_date", -1),
            ("report_date", -1),
            ("created_at", -1),
        ]
        try:
            return await self.db[collection_name].find_one(query, sort=sort)
        except Exception:
            return None

    async def _find_usage_records(self, report: Dict[str, Any]) -> List[Dict[str, Any]]:
        candidates = [
            report.get("task_id"),
            report.get("analysis_id"),
            report.get("id"),
        ]
        session_ids = [str(item) for item in candidates if item]
        if not session_ids:
            return []

        try:
            cursor = self.db["token_usage"].find({"session_id": {"$in": session_ids}})
            records = []
            async for doc in cursor:
                records.append(doc)
            return records
        except Exception:
            return []

    async def _get_enabled_sources(self) -> List[str]:
        try:
            doc = await self.db.system_configs.find_one({"is_active": True}, sort=[("version", -1)])
        except Exception:
            doc = None

        sources = []
        for item in (doc or {}).get("data_source_configs", []) or []:
            enabled = item.get("enabled", True) if isinstance(item, dict) else getattr(item, "enabled", True)
            if not enabled:
                continue
            source_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
            name = item.get("name") if isinstance(item, dict) else getattr(item, "name", None)
            if hasattr(source_type, "value"):
                source_type = source_type.value
            source = str(source_type or name or "").strip()
            if source and source not in sources:
                sources.append(source)
        return sources

    def _build_data_freshness(
        self,
        report: Dict[str, Any],
        quote_doc: Optional[Dict[str, Any]],
        basic_doc: Optional[Dict[str, Any]],
        financial_doc: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        quote_time = self._doc_time(quote_doc)
        basic_time = self._doc_time(basic_doc)
        financial_time = self._doc_time(financial_doc)
        generated_time = self._first_time(report.get("updated_at"), report.get("created_at"), report.get("timestamp"))
        analysis_date = report.get("analysis_date")
        reference_time = self._first_time(analysis_date, generated_time)

        notes: List[str] = []
        freshness_level = "unknown"
        if quote_time and reference_time:
            if abs(reference_time - quote_time) <= timedelta(days=3):
                freshness_level = "fresh"
                notes.append("行情数据与分析日期相距不超过3天。")
            else:
                freshness_level = "stale"
                notes.append("行情数据与分析日期相距超过3天，请谨慎解读价格相关结论。")
        else:
            notes.append("未记录可用于判断行情新鲜度的时间。")

        if not financial_time:
            notes.append("未找到财务数据更新时间，基本面结论可能依赖报告原文中的历史信息。")

        return {
            "analysis_date": str(analysis_date or ""),
            "generated_at": self._iso_or_none(generated_time),
            "market_quote_updated_at": self._iso_or_none(quote_time),
            "stock_basic_updated_at": self._iso_or_none(basic_time),
            "financial_updated_at": self._iso_or_none(financial_time),
            "freshness_level": freshness_level,
            "notes": notes,
        }

    def _build_data_sources(
        self,
        report: Dict[str, Any],
        enabled_sources: List[str],
        *docs: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        observed = []
        for value in report.get("data_sources") or []:
            self._add_unique_source(observed, value)
        for doc in docs:
            if not doc:
                continue
            for key in ("source", "data_source", "quote_source", "provider"):
                self._add_unique_source(observed, doc.get(key))

        actual_source_recorded = any(source not in {"unknown", "api", "analysis_tasks"} for source in observed)
        return {
            "report_source": report.get("source") or "unknown",
            "enabled_sources": enabled_sources,
            "observed_sources": observed,
            "actual_source_recorded": actual_source_recorded,
        }

    def _build_missing_items(self, report: Dict[str, Any], reports: Dict[str, Any]) -> List[Dict[str, Any]]:
        required = {"final_trade_decision"}
        analysts = report.get("analysts") or []
        for analyst in analysts:
            module = ANALYST_MODULES.get(str(analyst))
            if module:
                required.add(module)
        if not analysts:
            required.update(("market_report", "fundamentals_report", "news_report"))

        missing = []
        for key in sorted(required):
            value = reports.get(key)
            if isinstance(value, str):
                present = bool(value.strip())
            else:
                present = value not in (None, {}, [])
            if present:
                continue
            missing.append(
                {
                    "key": key,
                    "label": CORE_MODULE_LABELS.get(key, f"{key} 缺失"),
                    "severity": "medium" if key != "final_trade_decision" else "high",
                    "reason": "报告中未找到对应模块",
                }
            )
        return missing

    def _build_model_usage(self, report: Dict[str, Any], records: List[Dict[str, Any]]) -> Dict[str, Any]:
        tokens_used = self._number_or_none(report.get("tokens_used"))
        model_info = report.get("model_info") or "Unknown"
        if records:
            input_tokens = sum(int(item.get("input_tokens") or 0) for item in records)
            output_tokens = sum(int(item.get("output_tokens") or 0) for item in records)
            cost = sum(float(item.get("cost") or 0.0) for item in records)
            currency = records[0].get("currency") or "CNY"
            return {
                "model_info": model_info,
                "tokens_used": tokens_used if tokens_used is not None else input_tokens + output_tokens,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": round(cost, 6),
                "currency": currency,
                "cost_source": "token_usage",
            }

        token_usage = report.get("token_usage") if isinstance(report.get("token_usage"), dict) else {}
        if token_usage:
            return {
                "model_info": model_info,
                "tokens_used": tokens_used or token_usage.get("total_tokens"),
                "input_tokens": token_usage.get("prompt_tokens") or token_usage.get("input_tokens"),
                "output_tokens": token_usage.get("completion_tokens") or token_usage.get("output_tokens"),
                "cost": token_usage.get("cost"),
                "currency": token_usage.get("currency") or "CNY",
                "cost_source": "report",
            }

        return {
            "model_info": model_info,
            "tokens_used": tokens_used,
            "input_tokens": None,
            "output_tokens": None,
            "cost": None,
            "currency": "CNY",
            "cost_source": "unavailable",
        }

    def _build_confidence_basis(
        self,
        report: Dict[str, Any],
        data_freshness: Dict[str, Any],
        data_sources: Dict[str, Any],
        missing_items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        score = self._confidence_score(report.get("confidence_score"))
        normalized = self._normalize_score(score)
        label = self._confidence_label(normalized)

        positive: List[str] = []
        limiting: List[str] = []

        if normalized is not None and normalized >= 60:
            positive.append("模型给出中等及以上置信度。")
        if report.get("reports", {}).get("final_trade_decision"):
            positive.append("报告包含最终交易决策模块。")
        if len(report.get("reports", {}) or {}) >= 3:
            positive.append("报告包含多个分析模块。")
        if data_freshness.get("freshness_level") == "fresh":
            positive.append("行情数据与分析日期较接近。")
        if data_sources.get("actual_source_recorded"):
            positive.append("数据库中记录到可追踪的数据来源。")

        if normalized is None:
            limiting.append("报告未记录模型置信度。")
        elif normalized < 40:
            limiting.append("模型置信度偏低。")
        if missing_items:
            limiting.append(f"存在 {len(missing_items)} 个核心缺失项。")
        if data_freshness.get("freshness_level") in {"stale", "unknown"}:
            limiting.append("数据新鲜度不足或无法判断。")
        if not data_sources.get("actual_source_recorded"):
            limiting.append("实际使用的数据源未完整记录。")
        if not report.get("model_info") or report.get("model_info") == "Unknown":
            limiting.append("模型信息未记录。")

        return {
            "confidence_score": score,
            "label": label,
            "positive_factors": positive[:5],
            "limiting_factors": limiting[:5],
        }

    def _extract_counter_evidence(self, reports: Dict[str, Any]) -> List[Dict[str, Any]]:
        evidence = []
        for module in COUNTER_EVIDENCE_MODULES:
            content = reports.get(module)
            if not isinstance(content, str) or not content.strip():
                continue
            for sentence in self._split_sentences(content):
                if not any(keyword in sentence for keyword in COUNTER_EVIDENCE_KEYWORDS):
                    continue
                evidence.append(
                    {
                        "source_module": module,
                        "text": sentence[:180],
                        "severity": self._counter_evidence_severity(sentence),
                    }
                )
                if len(evidence) >= 5:
                    return evidence
        return evidence

    def _split_sentences(self, text: str) -> List[str]:
        cleaned = re.sub(r"[#>*`\-]+", "", text)
        raw_parts = re.split(r"[。！？!?；;\n]", cleaned)
        return [part.strip() for part in raw_parts if len(part.strip()) >= 12]

    def _counter_evidence_severity(self, text: str) -> str:
        if any(keyword in text for keyword in ("高风险", "严重", "卖出", "止损", "大幅", "显著", "亏损")):
            return "high"
        return "medium"

    def _symbol_variants(self, symbol: str) -> List[str]:
        raw = str(symbol).strip()
        variants = {raw, raw.upper(), raw.lower()}
        if raw.isdigit():
            variants.add(raw.zfill(6))
        if "." in raw:
            variants.add(raw.split(".")[0])
        return [item for item in variants if item]

    def _doc_time(self, doc: Optional[Dict[str, Any]]) -> Optional[datetime]:
        if not doc:
            return None
        return self._first_time(
            doc.get("updated_at"),
            doc.get("timestamp"),
            doc.get("trade_time"),
            doc.get("trade_date"),
            doc.get("report_date"),
            doc.get("created_at"),
        )

    def _first_time(self, *values: Any) -> Optional[datetime]:
        for value in values:
            parsed = self._parse_time(value)
            if parsed:
                return parsed
        return None

    def _parse_time(self, value: Any) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value).replace(tzinfo=None)
            except Exception:
                return None
        text = str(value).strip()
        if not text:
            return None
        formats = (
            ("%Y%m%d", 8),
            ("%Y-%m-%d", 10),
            ("%Y/%m/%d", 10),
            ("%Y-%m-%d %H:%M:%S", 19),
            ("%Y/%m/%d %H:%M:%S", 19),
        )
        for fmt, size in formats:
            try:
                return datetime.strptime(text[:size], fmt)
            except Exception:
                pass
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None

    def _iso_or_none(self, value: Optional[datetime]) -> Optional[str]:
        return value.isoformat() if value else None

    def _add_unique_source(self, sources: List[str], value: Any) -> None:
        if not value:
            return
        source = str(value).strip()
        if source and source not in sources:
            sources.append(source)

    def _confidence_score(self, value: Any) -> Optional[float]:
        number = self._number_or_none(value)
        if number is None:
            return None
        return number

    def _normalize_score(self, value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        return value if value > 1 else value * 100

    def _confidence_label(self, normalized: Optional[float]) -> str:
        if normalized is None:
            return "未知"
        if normalized >= 80:
            return "较高"
        if normalized >= 60:
            return "中上"
        if normalized >= 40:
            return "中等"
        return "较低"

    def _number_or_none(self, value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except Exception:
            return None

    def _freshness_label(self, value: Optional[str]) -> str:
        return {"fresh": "较新", "stale": "可能过期", "unknown": "未知"}.get(value or "", "未知")

    def _join_or_unknown(self, values: Any) -> str:
        if not values:
            return "未知"
        return "、".join(str(item) for item in values)

    def _format_cost(self, usage: Dict[str, Any]) -> str:
        cost = usage.get("cost")
        if cost in (None, ""):
            return "未知"
        return f"{usage.get('currency') or 'CNY'} {float(cost):.6f}"

    def _format_confidence(self, score: Any) -> str:
        if score in (None, ""):
            return "未知"
        normalized = self._normalize_score(float(score))
        return f"{normalized:.1f}%" if normalized is not None else "未知"
