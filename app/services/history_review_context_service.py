from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tradingagents.utils.report_guard import sanitize_report_modules

try:
    from tradingagents.utils.logging_init import get_logger

    logger = get_logger("default")
except Exception:
    logger = logging.getLogger(__name__)


CORE_HISTORY_MODULES = (
    "final_trade_decision",
    "trader_investment_plan",
    "market_report",
    "fundamentals_report",
    "news_report",
    "investment_plan",
    "review_context_report",
)


@dataclass
class HistoryReviewSource:
    analysis_id: str
    analysis_date: str
    source: str


@dataclass
class HistoryReviewBuildResult:
    prompt_context: str = ""
    display_report: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


class HistoryReviewPolicy:
    """Rules for selecting and sizing historical report review context."""

    DEPTH_RULES = {
        "快速": ("quick", 1),
        "基础": ("quick", 1),
        "标准": ("standard", 2),
        "深度": ("standard", 2),
        "全面": ("deep", 3),
    }

    EXPLICIT_RULES = {
        "quick": ("quick", 1),
        "standard": ("standard", 2),
        "deep": ("deep", 3),
    }

    CONTEXT_HINTS = (
        ("qwen-max-longcontext", 1_000_000),
        ("qwen-long", 1_000_000),
        ("qwen-turbo", 1_000_000),
        ("gemini", 1_000_000),
        ("claude-3", 200_000),
        ("gpt-4o", 128_000),
        ("gpt-4.1", 1_000_000),
        ("deepseek", 32_768),
        ("gpt-4", 8_192),
    )

    def resolve_depth(self, research_depth: str, requested_depth: str = "auto") -> Tuple[str, int]:
        if requested_depth and requested_depth != "auto":
            return self.EXPLICIT_RULES.get(requested_depth, ("standard", 2))
        return self.DEPTH_RULES.get(research_depth, ("standard", 2))

    def infer_context_length(self, model_name: str, model_config: Dict[str, Any]) -> Optional[int]:
        configured = model_config.get("context_length")
        if configured:
            try:
                return int(configured)
            except Exception:
                pass
        normalized = (model_name or "").lower()
        for keyword, length in self.CONTEXT_HINTS:
            if keyword in normalized:
                return length
        return None

    def token_budget(self, model_name: str, model_config: Dict[str, Any]) -> int:
        context_length = self.infer_context_length(model_name, model_config)
        output_tokens = int(model_config.get("max_tokens") or 4000)
        if not context_length:
            return 6000
        reserve = max(9000, output_tokens + 7000)
        available = max(1200, context_length - reserve)
        cap = 14_000 if context_length >= 128_000 else 10_000
        return max(1800, min(cap, int(available * 0.16)))


class HistoryReviewContextService:
    """Builds compact historical report review context for stock analysis."""

    def __init__(self, policy: Optional[HistoryReviewPolicy] = None):
        self.policy = policy or HistoryReviewPolicy()

    def build(
        self,
        stock_code: str,
        user_id: str,
        research_depth: str,
        requested_depth: str,
        current_analysis_date: str,
        model_name: str,
        model_config: Dict[str, Any],
    ) -> HistoryReviewBuildResult:
        depth_label, limit = self.policy.resolve_depth(research_depth, requested_depth)
        budget = self.policy.token_budget(model_name, model_config)
        reports = self._load_reports(stock_code, user_id, current_analysis_date, limit)

        meta: Dict[str, Any] = {
            "enabled": bool(reports),
            "depth": depth_label,
            "requested_depth": requested_depth or "auto",
            "report_limit": limit,
            "reports_used": len(reports),
            "token_budget": budget,
            "estimated_tokens": 0,
            "original_estimated_tokens": 0,
            "truncated": False,
            "budget_limited": False,
            "current_analysis_date": current_analysis_date,
            "sources": [source.__dict__ for source, _ in reports],
            "model_name": model_name,
            "context_length": self.policy.infer_context_length(model_name, model_config),
        }
        if not reports:
            meta["reason"] = "no_history_reports"
            return HistoryReviewBuildResult(meta=meta)

        prompt_context, final_meta = self._compose_to_budget(reports, depth_label, budget)
        meta.update(final_meta)
        display_report = self._display_report(prompt_context, meta)
        return HistoryReviewBuildResult(
            prompt_context=prompt_context,
            display_report=display_report,
            meta=meta,
        )

    def _load_reports(
        self,
        stock_code: str,
        user_id: str,
        current_analysis_date: str,
        limit: int,
    ) -> List[Tuple[HistoryReviewSource, Dict[str, Any]]]:
        code6 = str(stock_code).zfill(6)
        reports: List[Tuple[HistoryReviewSource, Dict[str, Any]]] = []
        seen_dates = set()

        try:
            from app.core.database import get_mongo_db_sync

            db = get_mongo_db_sync()
            query: Dict[str, Any] = {"stock_symbol": code6}
            if user_id:
                query["$or"] = [
                    {"user_id": str(user_id)},
                    {"user": str(user_id)},
                    {"user_id": {"$exists": False}, "user": {"$exists": False}},
                ]
            cursor = db.analysis_reports.find(query).sort("created_at", -1).limit(limit + 10)
            for report in cursor:
                date = str(report.get("analysis_date") or report.get("created_at") or "")[:10]
                if not date or date == str(current_analysis_date)[:10] or date in seen_dates:
                    continue
                modules = self._extract_report_modules(report)
                if not modules:
                    continue
                reports.append((
                    HistoryReviewSource(
                        analysis_id=str(report.get("analysis_id") or report.get("_id") or ""),
                        analysis_date=date,
                        source=report.get("source") or "mongodb",
                    ),
                    self._normalize_report(report, modules),
                ))
                seen_dates.add(date)
                if len(reports) >= limit:
                    return reports
        except Exception as exc:
            logger.warning(f"⚠️ 读取 Mongo 历史报告失败: {exc}")

        reports.extend(
            self._load_local_reports(
                stock_code=code6,
                excluded_dates=seen_dates,
                current_analysis_date=current_analysis_date,
                limit=limit - len(reports),
            )
        )
        return reports[:limit]

    def _load_local_reports(
        self,
        stock_code: str,
        excluded_dates: set,
        current_analysis_date: str,
        limit: int,
    ) -> List[Tuple[HistoryReviewSource, Dict[str, Any]]]:
        if limit <= 0:
            return []
        base_dir = Path("data") / "analysis_results" / str(stock_code).zfill(6)
        if not base_dir.exists():
            return []
        results: List[Tuple[HistoryReviewSource, Dict[str, Any]]] = []
        for date_dir in sorted((p for p in base_dir.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
            if date_dir.name == str(current_analysis_date)[:10] or date_dir.name in excluded_dates:
                continue
            reports_dir = date_dir / "reports"
            if not reports_dir.exists():
                continue
            modules = {}
            for module in CORE_HISTORY_MODULES:
                module_path = reports_dir / f"{module}.md"
                if module_path.exists():
                    try:
                        text = module_path.read_text(encoding="utf-8", errors="ignore").strip()
                    except Exception as exc:
                        logger.warning(f"⚠️ 读取本地历史报告失败: {module_path} - {exc}")
                        continue
                    if text:
                        modules[module] = text
            if not modules:
                continue
            results.append((
                HistoryReviewSource(
                    analysis_id=f"local:{stock_code}:{date_dir.name}",
                    analysis_date=date_dir.name,
                    source="local_files",
                ),
                self._normalize_report({"analysis_date": date_dir.name, "source": "local_files"}, modules),
            ))
            if len(results) >= limit:
                break
        return results

    def _normalize_report(self, report: Dict[str, Any], modules: Dict[str, Any]) -> Dict[str, Any]:
        final_decision = self._module_text(modules, "final_trade_decision")
        trader_plan = self._module_text(modules, "trader_investment_plan")
        market_report = self._module_text(modules, "market_report")
        fundamentals_report = self._module_text(modules, "fundamentals_report")
        news_report = self._module_text(modules, "news_report")
        decision_fields = self._extract_decision_fields(final_decision)

        return {
            "analysis_date": str(report.get("analysis_date") or report.get("created_at") or "")[:10],
            "recommendation": self._compact(report.get("recommendation") or decision_fields.get("action"), 80),
            "risk_level": self._compact(report.get("risk_level") or decision_fields.get("risk_score"), 60),
            "confidence_score": report.get("confidence_score") or decision_fields.get("confidence"),
            "summary": self._compact(report.get("summary"), 260),
            "decision": decision_fields,
            "decision_reasoning": self._extract_decision_reasoning(final_decision),
            "trader_plan": self._extract_trader_plan(trader_plan),
            "market_evidence": self._extract_dimension_evidence(market_report, "market"),
            "fundamentals_evidence": self._extract_dimension_evidence(fundamentals_report, "fundamentals"),
            "news_evidence": self._extract_dimension_evidence(news_report, "news"),
            "review_context_report": self._extract_recent_review_note(self._module_text(modules, "review_context_report")),
        }

    def _compose_to_budget(
        self,
        reports: List[Tuple[HistoryReviewSource, Dict[str, Any]]],
        depth_label: str,
        budget: int,
    ) -> Tuple[str, Dict[str, Any]]:
        variants = (
            {"include_trader": True, "include_dimensions": True},
            {"include_trader": False, "include_dimensions": True},
            {"include_trader": False, "include_dimensions": False},
        )
        for variant_index, variant in enumerate(variants):
            text = self._compose(reports, depth_label, **variant)
            estimated = self._estimate_tokens(text)
            if estimated <= budget:
                return text, {
                    "estimated_tokens": estimated,
                    "original_estimated_tokens": self._estimate_tokens(self._compose(reports, depth_label, True, True)),
                    "truncated": False,
                    "budget_limited": variant_index > 0,
                    "compression_variant": variant_index,
                }

        reduced_reports = reports[: max(1, len(reports) - 1)]
        text = self._compose(reduced_reports, depth_label, include_trader=False, include_dimensions=False)
        estimated = self._estimate_tokens(text)
        if estimated <= budget:
            return text, {
                "estimated_tokens": estimated,
                "original_estimated_tokens": self._estimate_tokens(self._compose(reports, depth_label, True, True)),
                "truncated": False,
                "budget_limited": True,
                "compression_variant": "drop_oldest",
                "reports_used": len(reduced_reports),
                "sources": [source.__dict__ for source, _ in reduced_reports],
            }

        hard = text[: max(800, int(len(text) * budget / max(estimated, 1) * 0.9))].rstrip()
        return hard + "\n\n[历史报告复盘已按预算硬截断]", {
            "estimated_tokens": self._estimate_tokens(hard),
            "original_estimated_tokens": self._estimate_tokens(self._compose(reports, depth_label, True, True)),
            "truncated": True,
            "budget_limited": True,
            "compression_variant": "hard_trim",
            "reports_used": len(reduced_reports),
            "sources": [source.__dict__ for source, _ in reduced_reports],
        }

    def _compose(
        self,
        reports: List[Tuple[HistoryReviewSource, Dict[str, Any]]],
        depth_label: str,
        include_trader: bool,
        include_dimensions: bool,
    ) -> str:
        lines = [
            "## 历史报告复盘",
            f"- 复盘深度: {depth_label}",
            f"- 使用最近 {len(reports)} 份历史报告；默认不引用 research_team_decision 和 risk_management_decision。",
            "- 用法: 仅作为历史判断校验和观点变化参考，不直接替代本次投资建议。",
            "",
            "### 历史结论序列",
        ]
        for source, report in reports:
            decision = report.get("decision") or {}
            conclusion = decision.get("action") or report.get("recommendation") or "未记录"
            target = decision.get("target_price") or "未记录"
            confidence = report.get("confidence_score") or "未记录"
            risk = report.get("risk_level") or "未记录"
            lines.append(
                f"- {source.analysis_date}: 动作={conclusion}；目标价={target}；置信度={confidence}；风险={risk}"
            )

        lines.extend([
            "",
            "### 历史报告结构化输入包",
        ])
        for index, (source, report) in enumerate(reports, start=1):
            decision = report.get("decision") or {}
            lines.extend([
                f"#### 历史报告 {index}: {source.analysis_date}",
                "- 历史结论: "
                f"动作={decision.get('action') or report.get('recommendation') or '未记录'}；"
                f"目标价={decision.get('target_price') or '未记录'}；"
                f"置信度={report.get('confidence_score') if report.get('confidence_score') is not None else '未记录'}；"
                f"风险评分/等级={report.get('risk_level') or '未记录'}",
            ])
            if report.get("summary"):
                lines.append(f"- 报告摘要: {report['summary']}")
            if report.get("decision_reasoning"):
                lines.append(f"- 历史核心理由: {report['decision_reasoning']}")
            if include_trader and report.get("trader_plan"):
                lines.append(f"- 历史交易计划: {report['trader_plan']}")
            if include_dimensions:
                lines.extend(self._format_evidence_block("技术面证据", report.get("market_evidence")))
                lines.extend(self._format_evidence_block("基本面证据", report.get("fundamentals_evidence")))
                lines.extend(self._format_evidence_block("新闻面证据", report.get("news_evidence")))
                lines.extend(self._format_review_questions(report))
            if depth_label == "deep" and index == 1 and report.get("review_context_report"):
                lines.append(f"- 最近复盘结论: {report['review_context_report']}")
            lines.append("")

        lines.extend([
            "### 本次分析必须回答",
            "1. 历史报告中的核心判断，哪些被当前信息支持、削弱或推翻？",
            "2. 技术面、基本面、新闻面是否相较历史出现关键变化？",
            "3. 当前最终建议若延续历史逻辑，证据是什么；若推翻历史逻辑，新增证据是什么？",
            "4. 若历史报告提供了“复盘索引”或“可验证假设”，必须逐项检查其验证信号或失效信号。",
        ])
        return "\n".join(lines)

    def _display_report(self, prompt_context: str, meta: Dict[str, Any]) -> str:
        sources = meta.get("sources") or []
        source_block = "\n".join(
            f"- {item.get('analysis_date') or '未知日期'} ({item.get('source') or 'history'})"
            for item in sources
        ) or "- 未记录"
        return (
            "# 历史报告复盘\n\n"
            "## 本次注入状态\n\n"
            f"- 使用历史报告数: {meta.get('reports_used', 0)}\n"
            f"- 估算注入 tokens: {meta.get('estimated_tokens', 0)}\n"
            f"- 预算 tokens: {meta.get('token_budget') or '未配置'}\n"
            f"- 是否截断: {'是' if meta.get('truncated') else '否'}\n"
            f"- 是否预算压缩: {'是' if meta.get('budget_limited') else '否'}\n\n"
            "## 历史报告来源\n\n"
            f"{source_block}\n\n"
            "## 注入内容\n\n"
            f"{prompt_context}"
        )

    def _extract_report_modules(self, report: Dict[str, Any]) -> Dict[str, Any]:
        candidates = [
            report.get("reports"),
            report.get("result", {}).get("reports") if isinstance(report.get("result"), dict) else None,
            report.get("full_result", {}).get("reports") if isinstance(report.get("full_result"), dict) else None,
            report.get("detailed_analysis", {}).get("reports") if isinstance(report.get("detailed_analysis"), dict) else None,
        ]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate:
                return sanitize_report_modules(candidate)
        return {}

    def _extract_decision_fields(self, text: str) -> Dict[str, str]:
        compact = self._clean_text(text)
        patterns = {
            "action": r"\*{0,2}(?:行动|最终建议|最终交易建议|投资建议)\*{0,2}\s*[:：]?\s*\*{0,2}(买入|持有|卖出)\*{0,2}",
            "confidence": r"\*{0,2}(?:置信度)\*{0,2}\s*[:：]?\s*\*{0,2}([0-9]+(?:\.[0-9]+)?%?|0?\.[0-9]+)\*{0,2}",
            "risk_score": r"\*{0,2}(?:综合风险评分|风险评分|风险等级)\*{0,2}\s*[:：]?\s*\*{0,2}([0-9]+(?:\.[0-9]+)?%?|低|中等|高|较高|较低)\*{0,2}",
            "target_price": r"\*{0,2}(?:目标价区间|目标价位|目标价格|目标价|基准目标)\*{0,2}\s*[:：]?\s*\*{0,2}(¥?\s*[0-9]+(?:\.[0-9]+)?(?:\s*[-~至]\s*¥?\s*[0-9]+(?:\.[0-9]+)?)?)",
        }
        result: Dict[str, str] = {}
        for key, pattern in patterns.items():
            match = re.search(pattern, compact, flags=re.IGNORECASE)
            if match:
                result[key] = self._compact(match.group(1), 80)
        return result

    def _extract_decision_reasoning(self, text: str) -> str:
        sections = self._sections_by_headings(
            text,
            ("决策快照", "判断依据表", "证据裁决", "可验证假设", "复盘索引", "分析推理", "详细推理", "理由", "总结"),
        )
        source = "\n".join(sections) if sections else text
        return self._compact(self._select_informative_text(source, max_items=8), 780)

    def _extract_trader_plan(self, text: str) -> str:
        if not text:
            return ""
        plan_sections = self._sections_by_headings(
            text,
            ("交易计划", "价格与仓位", "执行方案", "目标价位", "止损", "投资建议"),
        )
        source = "\n".join(plan_sections) if plan_sections else text
        return self._compact(self._select_informative_text(source, max_items=8), 760)

    def _extract_dimension_evidence(self, text: str, dimension: str) -> Dict[str, str]:
        if not text:
            return {}
        if dimension == "market":
            return {
                "state": self._extract_key_lines(text, ("当前价格", "涨跌幅", "历史价格分位", "收盘价", "趋势"), 4, 420),
                "signals": self._extract_key_lines(text, ("MA", "均线", "MACD", "RSI", "BOLL", "布林", "金叉", "死叉"), 8, 760),
                "levels": self._extract_key_lines(text, ("支撑", "阻力", "压力", "止损", "突破", "回落"), 6, 620),
                "conclusion": self._extract_named_sections(text, ("综合技术", "技术结论", "价格趋势", "交易建议"), 700),
            }
        if dimension == "fundamentals":
            return {
                "valuation": self._extract_key_lines(text, ("PE", "PB", "PS", "PEG", "估值", "历史分位", "中位数", "低点"), 10, 900),
                "quality": self._extract_key_lines(text, ("ROE", "毛利率", "净利率", "营收", "净利润", "现金流", "负债", "盈利"), 8, 800),
                "peers": self._extract_named_sections(text, ("同业对比", "同行", "可比", "估值锚"), 650),
                "conclusion": self._extract_named_sections(text, ("核心结论", "投资建议", "风险", "结论"), 760),
            }
        if dimension == "news":
            return {
                "events": self._extract_named_sections(text, ("核心事件", "时间线", "关键日期", "关键发现"), 850),
                "impact": self._extract_named_sections(text, ("新闻影响", "市场情绪", "短期影响", "中长期影响"), 850),
                "risks": self._extract_named_sections(text, ("风险提示", "利空", "压力因素", "追高风险"), 650),
                "conclusion": self._extract_named_sections(text, ("投资建议", "核心策略", "关键发现总结"), 700),
            }
        return {}

    def _extract_recent_review_note(self, text: str) -> str:
        if not text:
            return ""
        sections = self._sections_by_headings(text, ("历史报告复盘", "本次分析必须回答", "注入内容"))
        source = "\n".join(sections[-2:]) if sections else text
        return self._compact(self._select_informative_text(source, max_items=5), 520)

    def _format_evidence_block(self, title: str, evidence: Optional[Dict[str, str]]) -> List[str]:
        if not evidence:
            return [f"- {title}: 未记录或报告为空"]
        labels = {
            "state": "状态",
            "signals": "关键指标/信号",
            "levels": "关键价位",
            "valuation": "估值",
            "quality": "经营质量",
            "peers": "同业/可比",
            "events": "核心事件",
            "impact": "影响判断",
            "risks": "风险",
            "conclusion": "历史结论",
        }
        lines = [f"- {title}:"]
        has_content = False
        for key, value in evidence.items():
            if value:
                has_content = True
                lines.append(f"  - {labels.get(key, key)}: {value}")
        if not has_content:
            return [f"- {title}: 未提取到关键证据"]
        return lines

    def _format_review_questions(self, report: Dict[str, Any]) -> List[str]:
        questions = []
        market = report.get("market_evidence") or {}
        fundamentals = report.get("fundamentals_evidence") or {}
        news = report.get("news_evidence") or {}
        if market:
            questions.append("技术面: 历史支撑/阻力、均线、MACD/RSI 信号是否在当前行情中兑现或失效？")
        if fundamentals:
            questions.append("基本面: 历史估值低位、盈利改善、同业不可比等判断是否仍成立？")
        if news:
            questions.append("新闻面: 历史事件催化、资金情绪、政策/消费预期是否继续发酵或已被消化？")
        if not questions:
            return []
        return ["- 待复盘假设: " + " ".join(questions)]

    def _extract_named_sections(self, text: str, headings: Tuple[str, ...], max_chars: int) -> str:
        sections = self._sections_by_headings(text, headings)
        if not sections:
            return self._extract_key_lines(text, headings, 5, max_chars)
        return self._compact(self._select_informative_text("\n".join(sections), max_items=8), max_chars)

    def _section_after_heading(self, text: str, headings: Tuple[str, ...]) -> str:
        sections = self._sections_by_headings(text, headings)
        return sections[0] if sections else ""

    def _sections_by_headings(self, text: str, headings: Tuple[str, ...]) -> List[str]:
        lines = (text or "").splitlines()
        sections: List[str] = []
        capture: List[str] = []
        active = False
        for line in lines:
            stripped = line.strip()
            is_heading = stripped.startswith("#") or re.match(r"^(?:[一二三四五六七八九十]+、|\d+(?:\.\d+)*[\.、])", stripped)
            if is_heading:
                if active and capture:
                    sections.append("\n".join(capture).strip())
                    capture = []
                active = any(keyword.lower() in stripped.lower() for keyword in headings)
            if active:
                capture.append(stripped)
        if active and capture:
            sections.append("\n".join(capture).strip())
        return [section for section in sections if section]

    def _extract_key_lines(
        self,
        text: str,
        keywords: Tuple[str, ...],
        max_lines: int,
        max_chars: int,
    ) -> str:
        selected = []
        for raw_line in (text or "").splitlines():
            line = raw_line.strip()
            if not line or set(line) <= {"-", "|", " "}:
                continue
            if any(keyword.lower() in line.lower() for keyword in keywords):
                selected.append(line)
            if len(selected) >= max_lines:
                break
        return self._compact("；".join(selected), max_chars)

    def _select_informative_text(self, text: str, max_items: int) -> str:
        items = []
        for raw_line in (text or "").splitlines():
            line = raw_line.strip()
            if not line or line in {"---"}:
                continue
            line = re.sub(r"^#+\s*", "", line)
            if len(line) < 8 and not re.search(r"\d", line):
                continue
            items.append(line)
            if len(items) >= max_items:
                break
        if items:
            return "；".join(items)
        return self._clean_text(text)

    def _clean_text(self, value: Any) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            try:
                value = json.dumps(value, ensure_ascii=False, default=str)
            except Exception:
                value = str(value)
        return " ".join(value.split())

    def _module_text(self, modules: Dict[str, Any], module: str) -> str:
        value = modules.get(module)
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("content", "text", "markdown", "report", "summary"):
                nested = value.get(key)
                if isinstance(nested, str) and nested.strip():
                    return nested
        return self._compact(value, 400)

    def _compact(self, value: Any, max_chars: int) -> str:
        value = self._clean_text(value)
        if len(value) <= max_chars:
            return value
        return value[:max_chars].rstrip() + "..."

    def _estimate_tokens(self, text: str) -> int:
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        ascii_chars = sum(1 for ch in text if ord(ch) < 128 and not ch.isspace())
        other = max(0, len(text) - cjk - ascii_chars)
        return int(cjk + ascii_chars / 4 + other * 0.6)
