"""两阶段行业分析引擎：行业尽调 + 基于尽调结果的选股。"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
else:
    BaseChatModel = Any

try:
    from app.models.industry_analysis import (
        DetailLevel,
        DISCOVERY_INSIGHT_CATEGORIES,
        DiscoveryInsightItem,
        IndustryDiscoveryInsights,
        IndustryLogicSections,
        IndustryAnalysisResult,
        RecommendationGroup,
        StockCandidate,
        StockRecommendation,
        StockSelectionSections,
        SupplyChainSegment,
    )
except Exception:
    industry_analysis_model_path = Path(__file__).resolve().parents[2] / "app" / "models" / "industry_analysis.py"
    spec = importlib.util.spec_from_file_location("industry_analysis_model_fallback", industry_analysis_model_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load industry analysis models from {industry_analysis_model_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    DetailLevel = module.DetailLevel
    DISCOVERY_INSIGHT_CATEGORIES = module.DISCOVERY_INSIGHT_CATEGORIES
    DiscoveryInsightItem = module.DiscoveryInsightItem
    IndustryDiscoveryInsights = module.IndustryDiscoveryInsights
    IndustryLogicSections = module.IndustryLogicSections
    IndustryAnalysisResult = module.IndustryAnalysisResult
    RecommendationGroup = module.RecommendationGroup
    StockCandidate = module.StockCandidate
    StockRecommendation = module.StockRecommendation
    StockSelectionSections = module.StockSelectionSections
    SupplyChainSegment = module.SupplyChainSegment

from tradingagents.llm_clients.base_client import normalize_content
from tradingagents.utils.logging_manager import get_logger

from .prompts import build_due_diligence_prompt, build_stock_selection_prompt
from tradingagents.utils.structured_output import extract_structured_payload, strip_structured_payload_blocks

logger = get_logger("industry_analysis")

_REFERENCE_DISCLAIMER = "AI分析仅供参考，不构成投资建议，请结合基本面、公告与市场风险独立判断。"


@dataclass
class TwoStageResult:
    """Internal result container for the two-stage analysis."""
    due_diligence_report: str = ""
    stock_selection_report: str = ""
    recommendations: List[StockRecommendation] = field(default_factory=list)
    market_overview: str = ""
    selection_reasoning: str = ""
    risk_warning: str = ""
    exclusion_reasons: str = ""
    portfolio_advice: str = ""
    tracking_indicators: str = ""
    conclusion: str = ""
    industry_logic_sections: Optional[IndustryLogicSections] = None
    stock_selection_sections: Optional[StockSelectionSections] = None
    supply_chain_analysis: List[SupplyChainSegment] = field(default_factory=list)
    recommendation_groups: List[RecommendationGroup] = field(default_factory=list)
    discovery_insights: IndustryDiscoveryInsights = field(default_factory=IndustryDiscoveryInsights)
    llm_calls: int = 0


class StockComparator:
    """Two-stage industry analysis engine: due diligence -> stock selection."""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_due_diligence(self, concept: str) -> str:
        """Stage 1: Generate a comprehensive industry due diligence report (Markdown)."""
        prompt = build_due_diligence_prompt(concept)
        logger.info("Stage 1 开始: 生成行业尽调报告 concept=%s", concept)
        report = await self._invoke_llm(prompt)
        logger.info("Stage 1 完成: 尽调报告长度=%d chars", len(report))
        return report

    async def select_stocks(
        self,
        concept: str,
        due_diligence_report: str,
        candidates: List[StockCandidate],
        top_n: int = 5,
    ) -> TwoStageResult:
        """Stage 2: Select top stocks based on due diligence + candidate data."""
        candidate_data = self._build_candidate_data_json(candidates)
        prompt = build_stock_selection_prompt(
            industry_query=concept,
            due_diligence_report=due_diligence_report,
            candidate_data=candidate_data,
        )

        logger.info("Stage 2 开始: 基于尽调结果选股 concept=%s, candidates=%d", concept, len(candidates))
        response_text = await self._invoke_llm(prompt)
        logger.info("Stage 2 完成: 选股报告长度=%d chars", len(response_text))

        # Parse structured data from the Markdown response
        result = self._parse_stock_selection(response_text, candidates, top_n)
        clean_response_text = strip_structured_payload_blocks(response_text)
        self._supplement_two_layer_sections(result, due_diligence_report, clean_response_text)
        result.stock_selection_report = clean_response_text
        result.due_diligence_report = due_diligence_report
        return result

    async def compare_and_select(
        self,
        candidates: List[StockCandidate],
        user_concept: str,
        top_n: int = 5,
        detail_level: DetailLevel = DetailLevel.BRIEF,
    ) -> IndustryAnalysisResult:
        """Legacy API: runs full two-stage analysis. Kept for backward compatibility."""
        start_time = time.perf_counter()
        mapped_boards = self._collect_mapped_boards(candidates)
        data_date = date.today().isoformat()

        if not candidates:
            return IndustryAnalysisResult(
                concept=user_concept,
                detail_level=detail_level,
                mapped_boards=mapped_boards,
                candidate_count=0,
                filtered_count=0,
                recommendations=[],
                market_overview="暂无候选股票，无法进行概念对比分析。",
                selection_reasoning="候选池为空，建议先扩大概念映射范围或补充筛选数据。",
                risk_warning=_REFERENCE_DISCLAIMER,
                analysis_time=round(time.perf_counter() - start_time, 4),
                llm_calls=0,
                data_date=data_date,
                industry_logic_sections=self._build_industry_logic_sections(""),
                stock_selection_sections=self._build_stock_selection_sections(""),
                discovery_insights=IndustryDiscoveryInsights(),
            )

        # Two-stage approach
        dd_report = await self.generate_due_diligence(user_concept)
        two_stage = await self.select_stocks(user_concept, dd_report, candidates, top_n)

        return IndustryAnalysisResult(
            concept=user_concept,
            detail_level=detail_level,
            mapped_boards=mapped_boards,
            candidate_count=len(candidates),
            filtered_count=len(candidates),
            recommendations=two_stage.recommendations,
            market_overview=two_stage.market_overview,
            selection_reasoning=two_stage.selection_reasoning,
            risk_warning=self._ensure_disclaimer(two_stage.risk_warning),
            due_diligence_report=two_stage.due_diligence_report,
            stock_selection_report=two_stage.stock_selection_report,
            exclusion_reasons=two_stage.exclusion_reasons,
            portfolio_advice=two_stage.portfolio_advice,
            tracking_indicators=two_stage.tracking_indicators,
            conclusion=two_stage.conclusion,
            industry_logic_sections=two_stage.industry_logic_sections,
            stock_selection_sections=two_stage.stock_selection_sections,
            supply_chain_analysis=two_stage.supply_chain_analysis,
            recommendation_groups=two_stage.recommendation_groups,
            discovery_insights=two_stage.discovery_insights,
            analysis_time=round(time.perf_counter() - start_time, 4),
            llm_calls=2,
            data_date=data_date,
        )

    # ------------------------------------------------------------------
    # LLM invocation
    # ------------------------------------------------------------------

    async def _invoke_llm(self, prompt: str) -> str:
        if hasattr(self.llm, "ainvoke") and callable(getattr(self.llm, "ainvoke")):
            response = await self.llm.ainvoke(prompt)
        else:
            response = await asyncio.to_thread(self.llm.invoke, prompt)
        return self._response_to_text(response)

    def _response_to_text(self, response: Any) -> str:
        if isinstance(response, str):
            return response.strip()

        normalized = normalize_content(response)
        content = getattr(normalized, "content", normalized)

        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(str(item.get("text", "")))
            return "\n".join(part for part in parts if part).strip()
        return str(content).strip()

    # ------------------------------------------------------------------
    # Build candidate data for Stage 2
    # ------------------------------------------------------------------

    def _build_candidate_data_json(self, candidates: List[StockCandidate]) -> str:
        """Build a structured JSON string of candidate data for the stock selection prompt."""
        if not candidates:
            return "[]"

        data = []
        for c in candidates:
            entry: Dict[str, Any] = {
                "代码": c.code,
                "名称": c.name or "-",
                "行业": c.industry or "-",
            }
            if c.pe is not None:
                entry["PE"] = round(c.pe, 2)
            if c.pb is not None:
                entry["PB"] = round(c.pb, 2)
            if c.roe is not None:
                entry["ROE%"] = round(c.roe, 2)
            if c.total_mv is not None:
                entry["总市值(亿)"] = round(c.total_mv, 2)
            if c.revenue_growth is not None:
                entry["营收增速%"] = round(c.revenue_growth, 2)
            if c.net_profit_growth is not None:
                entry["净利增速%"] = round(c.net_profit_growth, 2)
            if c.debt_ratio is not None:
                entry["负债率%"] = round(c.debt_ratio, 2)
            if c.price is not None:
                entry["价格"] = round(c.price, 2)
            if c.pct_chg is not None:
                entry["当日涨跌%"] = round(c.pct_chg, 2)
            if c.pct_chg_20d is not None:
                entry["20日涨跌%"] = round(c.pct_chg_20d, 2)
            if c.turnover_rate is not None:
                entry["换手率%"] = round(c.turnover_rate, 2)
            if c.source_boards:
                entry["来源板块"] = "、".join(c.source_boards[:3])
            data.append(entry)

        return json.dumps(data, ensure_ascii=False, indent=1)

    # ------------------------------------------------------------------
    # Parse Stage 2 response
    # ------------------------------------------------------------------

    def _parse_stock_selection(
        self, response_text: str, candidates: List[StockCandidate], top_n: int
    ) -> TwoStageResult:
        """Extract structured fields from the Stage 2 Markdown response."""
        result = TwoStageResult()
        structured_payload = extract_structured_payload(response_text)
        clean_response_text = strip_structured_payload_blocks(response_text)

        # Extract section contents from Markdown
        sections = self._extract_markdown_sections(clean_response_text)

        # Map sections to result fields (fuzzy match section names)
        result.market_overview = self._find_section(sections, ["概念解析", "行业结论", "结论摘要", "Top 5结论摘要"])
        result.selection_reasoning = self._find_section(sections, ["提取选股关键变量", "构建A股候选池", "选股关键变量"])
        result.exclusion_reasons = self._find_section(sections, ["未入选/剔除原因", "未入选", "剔除原因"])
        result.portfolio_advice = self._find_section(sections, ["组合建议"])
        result.tracking_indicators = self._find_section(sections, ["跟踪指标"])
        result.conclusion = self._find_section(sections, ["最终结论", "结论"])
        result.risk_warning = _REFERENCE_DISCLAIMER

        if structured_payload:
            self._apply_structured_payload(result, structured_payload, candidates, top_n)

        # Try to extract recommendations from the Top 5 table
        top5_section = self._find_section(sections, [
            "推荐A股Top 5", "推荐A股Top5", "推荐A股 Top 5", "推荐A股 Top5",
            "推荐A股", "Top 5", "Top5",
        ])
        if not top5_section:
            # Fallback: search entire response for a table with ranking/codes
            top5_section = clean_response_text

        if not result.recommendations:
            result.recommendations = self._extract_recommendations_from_markdown(
                top5_section, candidates, top_n
            )

        # If recommendations have missing scores/details, try to supplement from the scoring table (Section 4)
        if result.recommendations:
            scoring_section = self._find_section(sections, ["股票多维评分", "多维评分", "候选股评分"])
            if scoring_section:
                self._supplement_from_scoring_table(result.recommendations, scoring_section)

        return result

    def _supplement_two_layer_sections(
        self,
        result: TwoStageResult,
        due_diligence_report: str,
        stock_selection_report: str,
    ) -> None:
        if result.industry_logic_sections is None:
            result.industry_logic_sections = self._build_industry_logic_sections(due_diligence_report)
        if result.stock_selection_sections is None:
            result.stock_selection_sections = self._build_stock_selection_sections(stock_selection_report)
        if not self._has_discovery_insights(result.discovery_insights):
            result.discovery_insights = self._build_discovery_insights(
                due_diligence_report=due_diligence_report,
                stock_selection_report=stock_selection_report,
                recommendations=result.recommendations,
            )

    def _apply_structured_payload(
        self,
        result: TwoStageResult,
        payload: Dict[str, Any],
        candidates: List[StockCandidate],
        top_n: int,
    ) -> None:
        result.industry_logic_sections = self._parse_industry_logic_sections(
            payload.get("industry_logic_sections")
        )
        result.stock_selection_sections = self._parse_stock_selection_sections(
            payload.get("stock_selection_sections")
        )
        result.supply_chain_analysis = self._parse_supply_chain_analysis(
            payload.get("supply_chain_analysis"), candidates
        )
        result.recommendation_groups = self._parse_recommendation_groups(
            payload.get("recommendation_groups"), candidates
        )
        result.discovery_insights = self._parse_discovery_insights(
            payload.get("discovery_insights"), candidates
        )

        structured_recommendations = self._parse_recommendation_list(
            payload.get("recommendations"), candidates, top_n
        )
        if structured_recommendations:
            result.recommendations = structured_recommendations

    def _parse_industry_logic_sections(self, value: Any) -> Optional[IndustryLogicSections]:
        if not isinstance(value, dict):
            return None
        return IndustryLogicSections(
            supply_chain=self._clean_text(value.get("supply_chain")),
            policy=self._clean_text(value.get("policy")),
            cycle=self._clean_text(value.get("cycle")),
            demand=self._clean_text(value.get("demand")),
            competition=self._clean_text(value.get("competition")),
            risks=self._clean_text(value.get("risks")),
        )

    def _parse_stock_selection_sections(self, value: Any) -> Optional[StockSelectionSections]:
        if not isinstance(value, dict):
            return None
        return StockSelectionSections(
            leaders=self._clean_text(value.get("leaders")),
            growth_beta=self._clean_text(value.get("growth_beta")),
            valuation_repair=self._clean_text(value.get("valuation_repair")),
            high_risk=self._clean_text(value.get("high_risk")),
            watchlist=self._clean_text(value.get("watchlist")),
        )

    def _parse_supply_chain_analysis(
        self,
        value: Any,
        candidates: List[StockCandidate],
    ) -> List[SupplyChainSegment]:
        if not isinstance(value, list):
            return []

        segments: List[SupplyChainSegment] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            segments.append(SupplyChainSegment(
                segment_key=self._clean_text(item.get("segment_key")),
                segment_name=self._clean_text(item.get("segment_name")),
                business=self._clean_text(item.get("business")),
                benefit_logic=self._clean_text(item.get("benefit_logic")),
                key_indicators=self._clean_text(item.get("key_indicators")),
                risks=self._clean_text(item.get("risks")),
                related_stocks=self._parse_recommendation_list(item.get("related_stocks"), candidates, 20),
            ))
        return segments

    def _parse_recommendation_groups(
        self,
        value: Any,
        candidates: List[StockCandidate],
    ) -> List[RecommendationGroup]:
        if not isinstance(value, list):
            return []

        groups: List[RecommendationGroup] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            groups.append(RecommendationGroup(
                group_key=self._clean_text(item.get("group_key")),
                group_name=self._clean_text(item.get("group_name")),
                description=self._clean_text(item.get("description")),
                suitable_style=self._clean_text(item.get("suitable_style")),
                main_risks=self._clean_text(item.get("main_risks")),
                stocks=self._parse_recommendation_list(item.get("stocks"), candidates, 20),
            ))
        return groups

    def _parse_discovery_insights(
        self,
        value: Any,
        candidates: List[StockCandidate],
    ) -> IndustryDiscoveryInsights:
        if not isinstance(value, dict):
            return IndustryDiscoveryInsights()

        return IndustryDiscoveryInsights(**{
            key: self._parse_discovery_items(value.get(key), candidates)
            for key, _label in DISCOVERY_INSIGHT_CATEGORIES
        })

    def _parse_discovery_items(
        self,
        value: Any,
        candidates: List[StockCandidate],
    ) -> List[DiscoveryInsightItem]:
        if not isinstance(value, list):
            return []

        items: List[DiscoveryInsightItem] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            related_stocks = self._parse_recommendation_list(
                item.get("related_stocks") or item.get("stocks"),
                candidates,
                10,
            )
            items.append(DiscoveryInsightItem(
                title=self._clean_text(item.get("title")),
                summary=self._clean_text(item.get("summary") or item.get("description")),
                evidence=self._clean_text(item.get("evidence") or item.get("basis")),
                tracking_signal=self._clean_text(item.get("tracking_signal") or item.get("tracking")),
                expected_timing=self._clean_text(item.get("expected_timing") or item.get("timing")),
                severity=self._normalize_severity(item.get("severity")),
                related_stocks=related_stocks,
            ))
        return items

    def _parse_recommendation_list(
        self,
        value: Any,
        candidates: List[StockCandidate],
        limit: int,
    ) -> List[StockRecommendation]:
        if not isinstance(value, list):
            return []

        recommendations: List[StockRecommendation] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            code = self._clean_text(item.get("code") or item.get("股票代码"))
            code_match = re.search(r"(\d{6})", code)
            if not code_match:
                continue
            code = code_match.group(1)
            candidate = self._find_candidate_by_code(code, candidates)
            rec = StockRecommendation(
                rank=int(item.get("rank") or len(recommendations) + 1),
                code=code,
                name=self._clean_text(item.get("name")) or (candidate.name if candidate else ""),
                industry=self._clean_text(item.get("industry")) or (candidate.industry if candidate else ""),
                summary=self._clean_text(item.get("summary") or item.get("recommendation_logic")),
                score=self._parse_score(str(item.get("score") or "")),
                recommendation_logic=self._clean_text(item.get("recommendation_logic")),
                main_advantages=self._clean_text(item.get("main_advantages")),
                main_risks=self._clean_text(item.get("main_risks")),
                suitable_style=self._clean_text(item.get("suitable_style")),
                supply_chain_position=self._clean_text(item.get("supply_chain_position")),
                score_breakdown=self._parse_score_breakdown(item.get("score_breakdown")),
                key_metrics=self._build_key_metrics(candidate),
            )
            if isinstance(item.get("key_metrics"), dict):
                rec.key_metrics.update(item["key_metrics"])
            recommendations.append(rec)
            if len(recommendations) >= limit:
                break

        return recommendations

    def _parse_score_breakdown(self, value: Any) -> Dict[str, float]:
        if not isinstance(value, dict):
            return {}
        parsed: Dict[str, float] = {}
        for key, raw in value.items():
            score = self._parse_score(str(raw))
            if score > 0:
                parsed[str(key)] = score
        return parsed

    def _build_industry_logic_sections(self, report: str) -> IndustryLogicSections:
        sections = self._extract_markdown_sections(report or "")
        return IndustryLogicSections(
            supply_chain=self._find_section(sections, ["产业链拆解", "产业链"]),
            policy=self._find_section(sections, ["政策与周期判断", "政策", "周期判断"]),
            cycle=self._find_section(sections, ["政策与周期判断", "行业结论"]),
            demand=self._find_section(sections, ["需求端验证", "需求"]),
            competition=self._find_section(sections, ["竞争格局"]),
            risks=self._find_section(sections, ["风险矩阵", "风险"]),
        )

    def _build_stock_selection_sections(self, report: str) -> StockSelectionSections:
        sections = self._extract_markdown_sections(report or "")
        return StockSelectionSections(
            leaders=self._find_section(sections, ["推荐A股 Top 5", "推荐A股Top 5", "Top 5结论摘要"]),
            growth_beta=self._find_section(sections, ["组合建议"]),
            valuation_repair=self._find_section(sections, ["股票多维评分", "估值合理性"]),
            high_risk=self._find_section(sections, ["未入选/剔除原因", "风险"]),
            watchlist=self._find_section(sections, ["最终结论", "跟踪指标"]),
        )

    def _build_discovery_insights(
        self,
        due_diligence_report: str,
        stock_selection_report: str,
        recommendations: List[StockRecommendation],
    ) -> IndustryDiscoveryInsights:
        dd_sections = self._extract_markdown_sections(due_diligence_report or "")
        selection_sections = self._extract_markdown_sections(stock_selection_report or "")

        return IndustryDiscoveryInsights(
            industry_bottlenecks=self._build_discovery_category(
                title="产业瓶颈",
                sections=dd_sections,
                section_names=["产业链拆解", "经济性公式", "风险矩阵"],
                tracking_hint="跟踪产能、关键成本、订单兑现和价格竞争变化。",
            ),
            non_consensus_targets=self._build_discovery_category(
                title="非共识标的",
                sections=selection_sections,
                section_names=["未入选/剔除原因", "观察名单", "组合建议"],
                tracking_hint="跟踪是否出现业绩、订单或估值修复信号。",
                related_stocks=recommendations,
            ),
            financial_inflections=self._build_discovery_category(
                title="财务拐点",
                sections=selection_sections,
                section_names=["股票多维评分", "最终结论", "跟踪指标"],
                tracking_hint="跟踪营收增速、利润率、现金流和负债率的边际变化。",
            ),
            red_team_counterpoints=self._build_discovery_category(
                title="红队反证",
                sections={**dd_sections, **selection_sections},
                section_names=["风险矩阵", "风险", "主要风险", "未入选/剔除原因"],
                tracking_hint="跟踪能推翻核心逻辑的政策、需求、价格和财务证据。",
                severity="high",
            ),
            future_catalysts=self._build_discovery_category(
                title="未来催化事件",
                sections=dd_sections,
                section_names=["政策与周期判断", "真实项目/订单验证", "需求端验证"],
                tracking_hint="跟踪政策落地、订单招标、中标公告、产能投放和客户导入。",
            ),
        )

    def _build_discovery_category(
        self,
        title: str,
        sections: Dict[str, str],
        section_names: List[str],
        tracking_hint: str,
        related_stocks: Optional[List[StockRecommendation]] = None,
        severity: str = "medium",
    ) -> List[DiscoveryInsightItem]:
        content = self._find_section(sections, section_names)
        if not content:
            return []
        return [DiscoveryInsightItem(
            title=f"从报告提取：{title}",
            summary=self._compact_text(content, 220),
            evidence=f"来源章节：{section_names[0]}",
            tracking_signal=tracking_hint,
            severity=severity,
            related_stocks=(related_stocks or [])[:5],
        )]

    def _has_discovery_insights(self, value: IndustryDiscoveryInsights) -> bool:
        return any(getattr(value, key) for key, _label in DISCOVERY_INSIGHT_CATEGORIES)

    def _extract_markdown_sections(self, text: str) -> Dict[str, str]:
        """Split Markdown text into sections by headers."""
        sections: Dict[str, str] = {}
        current_title = ""
        current_lines: List[str] = []

        for line in text.split("\n"):
            header_match = re.match(
                r"^#{1,4}\s*(?:[一二三四五六七八九十]+[、.]?\s*)?(.+)$", line.strip()
            )
            if header_match:
                if current_title:
                    sections[current_title] = "\n".join(current_lines).strip()
                current_title = header_match.group(1).strip()
                current_lines = []
            else:
                current_lines.append(line)

        if current_title:
            sections[current_title] = "\n".join(current_lines).strip()

        return sections

    def _find_section(self, sections: Dict[str, str], candidates: List[str]) -> str:
        """Find a section by trying exact match first, then fuzzy substring match."""
        # Exact match
        for key in candidates:
            if key in sections and sections[key].strip():
                return sections[key]

        # Fuzzy: check if any candidate is contained in a section title
        for section_title, content in sections.items():
            if not content.strip():
                continue
            normalized_title = re.sub(r"\s+", "", section_title)
            for key in candidates:
                normalized_key = re.sub(r"\s+", "", key)
                if normalized_key in normalized_title or normalized_title in normalized_key:
                    return content

        return ""

    def _extract_recommendations_from_markdown(
        self, text: str, candidates: List[StockCandidate], top_n: int
    ) -> List[StockRecommendation]:
        """Extract stock recommendations from Markdown tables in the response."""
        recommendations: List[StockRecommendation] = []

        # Find Markdown table rows (support both ASCII | and fullwidth ｜)
        normalized_text = text.replace("｜", "|")
        table_rows = re.findall(r"^\|(.+)\|$", normalized_text, re.MULTILINE)
        if not table_rows:
            return recommendations

        # Find the Top 5 table header (must contain "排名" to distinguish from scoring table)
        header_idx = -1
        headers: List[str] = []
        # First pass: look for header with "排名" (the Top 5 table)
        for i, row in enumerate(table_rows):
            cells = [c.strip() for c in row.split("|")]
            cells = [c for c in cells if c]
            joined = "".join(cells)
            if "排名" in joined and ("代码" in joined or "名称" in joined):
                header_idx = i
                headers = cells
                break

        # Fallback: any table with both "代码" and "名称"
        if header_idx < 0:
            for i, row in enumerate(table_rows):
                cells = [c.strip() for c in row.split("|")]
                cells = [c for c in cells if c]
                joined = "".join(cells)
                if "代码" in joined and "名称" in joined:
                    header_idx = i
                    headers = cells
                    break

        if header_idx < 0 or not headers:
            return recommendations

        # Map header names to column indices (broader matching)
        col_map: Dict[str, int] = {}
        for idx, h in enumerate(headers):
            h_clean = h.strip()
            if "排名" in h_clean or h_clean in ("序号", "#"):
                col_map["rank"] = idx
            elif "代码" in h_clean or h_clean in ("代码", "股票代码", "证券代码"):
                col_map["code"] = idx
            elif "名称" in h_clean or h_clean in ("名称", "股票名称", "公司", "简称"):
                col_map["name"] = idx
            elif "行业" in h_clean or "所属" in h_clean or h_clean in ("分类",):
                col_map["industry"] = idx
            elif "总分" in h_clean or "评分" in h_clean or "得分" in h_clean or h_clean in ("分数", "总评"):
                col_map["score"] = idx
            elif "推荐逻辑" in h_clean or ("逻辑" in h_clean and "推荐" in h_clean):
                col_map["logic"] = idx
            elif "优势" in h_clean or "亮点" in h_clean:
                col_map["advantages"] = idx
            elif "风险" in h_clean and "扣" not in h_clean:
                col_map["risks"] = idx
            elif "风格" in h_clean or "适合" in h_clean or "类型" in h_clean:
                col_map["style"] = idx
            elif "理由" in h_clean or "原因" in h_clean or "说明" in h_clean:
                # Catch-all for recommendation reason columns
                if "logic" not in col_map:
                    col_map["logic"] = idx

        logger.debug("Top5表格列映射: headers=%s, col_map=%s", headers, col_map)

        # Parse data rows
        seen_codes: set = set()
        for row in table_rows[header_idx + 1:]:
            if re.match(r"^[\s\-:|]+$", row):
                continue

            cells = [c.strip() for c in row.split("|")]
            cells = [c for c in cells if c != ""]

            if len(cells) < 3:
                continue

            code = self._extract_cell(cells, col_map.get("code", 1))
            code_match = re.search(r"(\d{6})", code)
            if not code_match:
                continue
            code = code_match.group(1)

            if code in seen_codes:
                continue
            seen_codes.add(code)

            name = self._extract_cell(cells, col_map.get("name", 2))
            score_str = self._extract_cell(cells, col_map.get("score", -1))
            logic = self._extract_cell(cells, col_map.get("logic", -1))
            advantages = self._extract_cell(cells, col_map.get("advantages", -1))
            risks = self._extract_cell(cells, col_map.get("risks", -1))
            style = self._extract_cell(cells, col_map.get("style", -1))
            industry = self._extract_cell(cells, col_map.get("industry", -1))

            candidate = self._find_candidate_by_code(code, candidates)
            score = self._parse_score(score_str)

            summary = logic or ""
            if not summary and advantages:
                summary = f"{name}: {advantages}"

            rec = StockRecommendation(
                rank=len(recommendations) + 1,
                code=code,
                name=name or (candidate.name if candidate else ""),
                summary=summary,
                score=score,
                industry=industry or (candidate.industry if candidate else ""),
                recommendation_logic=logic,
                main_advantages=advantages,
                main_risks=risks,
                suitable_style=style,
                key_metrics=self._build_key_metrics(candidate),
            )
            recommendations.append(rec)

            if len(recommendations) >= top_n:
                break

        return recommendations

    def _extract_cell(self, cells: List[str], idx: int) -> str:
        """Safely extract a cell value from a parsed row."""
        if idx < 0 or idx >= len(cells):
            return ""
        return cells[idx].strip()

    def _parse_score(self, score_str: str) -> float:
        """Parse a numeric score from text."""
        if not score_str:
            return 0.0
        match = re.search(r"(\d+(?:\.\d+)?)", score_str)
        if match:
            return min(100.0, max(0.0, float(match.group(1))))
        return 0.0

    def _supplement_from_scoring_table(
        self, recommendations: List[StockRecommendation], scoring_text: str
    ) -> None:
        """Supplement recommendation scores and score_breakdown from the scoring table (Section 4)."""
        normalized = scoring_text.replace("｜", "|")
        table_rows = re.findall(r"^\|(.+)\|$", normalized, re.MULTILINE)
        if not table_rows:
            return

        # Find scoring header (should have "代码" and "总分")
        header_idx = -1
        headers: List[str] = []
        for i, row in enumerate(table_rows):
            cells = [c.strip() for c in row.split("|")]
            cells = [c for c in cells if c]
            joined = "".join(cells)
            if ("代码" in joined or "名称" in joined) and ("总分" in joined or "评分" in joined):
                header_idx = i
                headers = cells
                break

        if header_idx < 0:
            return

        # Map scoring table columns
        score_col_map: Dict[str, int] = {}
        scoring_dimension_cols: Dict[str, int] = {}
        for idx, h in enumerate(headers):
            h_clean = h.strip()
            if "代码" in h_clean:
                score_col_map["code"] = idx
            elif "总分" in h_clean or "评分" in h_clean:
                score_col_map["score"] = idx
            elif "说明" in h_clean:
                score_col_map["note"] = idx
            # Scoring dimensions for score_breakdown
            elif "概念" in h_clean and "相关" in h_clean:
                scoring_dimension_cols["概念相关性"] = idx
            elif "行业地位" in h_clean:
                scoring_dimension_cols["行业地位"] = idx
            elif "发展前景" in h_clean:
                scoring_dimension_cols["发展前景"] = idx
            elif "基本面" in h_clean:
                scoring_dimension_cols["基本面"] = idx
            elif "技术面" in h_clean:
                scoring_dimension_cols["技术面"] = idx
            elif "财务" in h_clean:
                scoring_dimension_cols["财务健康"] = idx
            elif "估值" in h_clean:
                scoring_dimension_cols["估值合理性"] = idx
            elif "扣分" in h_clean:
                scoring_dimension_cols["风险扣分"] = idx

        if "code" not in score_col_map:
            return

        # Parse scoring data
        score_lookup: Dict[str, Dict] = {}
        for row in table_rows[header_idx + 1:]:
            if re.match(r"^[\s\-:|]+$", row):
                continue
            cells = [c.strip() for c in row.split("|")]
            cells = [c for c in cells if c != ""]
            if len(cells) < 3:
                continue

            code_cell = self._extract_cell(cells, score_col_map.get("code", -1))
            code_match = re.search(r"(\d{6})", code_cell)
            if not code_match:
                continue

            code = code_match.group(1)
            score_str = self._extract_cell(cells, score_col_map.get("score", -1))
            note = self._extract_cell(cells, score_col_map.get("note", -1))

            breakdown = {}
            for dim_name, dim_idx in scoring_dimension_cols.items():
                val = self._parse_score(self._extract_cell(cells, dim_idx))
                if val > 0:
                    breakdown[dim_name] = val

            score_lookup[code] = {
                "score": self._parse_score(score_str),
                "note": note,
                "breakdown": breakdown,
            }

        # Merge into recommendations
        for rec in recommendations:
            data = score_lookup.get(rec.code)
            if not data:
                continue
            if rec.score == 0 and data["score"] > 0:
                rec.score = data["score"]
            if not rec.summary and data["note"]:
                rec.summary = data["note"]
            if data["breakdown"]:
                rec.score_breakdown = data["breakdown"]

    def _find_candidate_by_code(self, code: str, candidates: List[StockCandidate]) -> Optional[StockCandidate]:
        """Find a candidate by stock code."""
        normalized = re.sub(r"\D", "", code or "")
        for c in candidates:
            if c.code == code or re.sub(r"\D", "", c.code) == normalized:
                return c
        return None

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def _build_key_metrics(self, candidate: Optional[StockCandidate]) -> Dict[str, Any]:
        if candidate is None:
            return {}
        metric_names = [
            "industry", "pe", "pb", "roe", "total_mv", "circ_mv",
            "revenue_growth", "net_profit_growth", "debt_ratio",
            "price", "pct_chg", "pct_chg_5d", "pct_chg_20d",
            "turnover_rate", "volume_ratio", "source_boards", "match_score",
        ]
        metric_data = candidate.model_dump()
        return {key: metric_data.get(key) for key in metric_names if metric_data.get(key) not in (None, [], "")}

    def _collect_mapped_boards(self, candidates: List[StockCandidate]) -> List[str]:
        boards: List[str] = []
        for candidate in candidates:
            for board in candidate.source_boards:
                if board and board not in boards:
                    boards.append(board)
        return boards

    def _ensure_disclaimer(self, risk_warning: str) -> str:
        risk_warning = risk_warning or ""
        if _REFERENCE_DISCLAIMER in risk_warning:
            return risk_warning
        if not risk_warning:
            return _REFERENCE_DISCLAIMER
        return f"{risk_warning} {_REFERENCE_DISCLAIMER}"

    def _clean_text(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _compact_text(self, value: str, limit: int) -> str:
        text = re.sub(r"\s+", " ", value or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "..."

    def _normalize_severity(self, value: Any) -> str:
        normalized = str(value or "medium").strip().lower()
        if normalized in {"high", "medium", "low"}:
            return normalized
        return "medium"

    def _format_value(self, value: Any) -> str:
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)
