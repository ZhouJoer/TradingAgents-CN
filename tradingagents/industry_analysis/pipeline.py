"""行业分析全流程编排：两阶段（尽调 + 选股）并行优化。"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from app.models.industry_analysis import (
        ConceptMappingResult,
        IndustryAnalysisRequest,
        IndustryAnalysisResult,
        StockCandidate,
    )
except Exception:
    model_path = Path(__file__).resolve().parents[2] / "app" / "models" / "industry_analysis.py"
    spec = importlib.util.spec_from_file_location("industry_analysis_model_fallback", model_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load industry analysis models from {model_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ConceptMappingResult = module.ConceptMappingResult
    IndustryAnalysisRequest = module.IndustryAnalysisRequest
    IndustryAnalysisResult = module.IndustryAnalysisResult
    StockCandidate = module.StockCandidate

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import create_llm_by_provider
from tradingagents.utils.logging_manager import get_logger

from .candidate_fetcher import CandidateFetcher
from .candidate_filter import CandidateFilter
from .concept_mapper import ConceptMapper
from .stock_comparator import StockComparator

logger = get_logger("industry_analysis")
ProgressCallback = Callable[[int, str], Any]


class IndustryAnalysisPipeline:
    """两阶段行业分析流水线：

    并行路径:
      A) LLM深度尽调报告（不依赖数据）
      B) 概念映射 → 候选抓取 → 规则过滤

    串行阶段:
      Stage 2: 基于尽调报告 + 候选数据 → 选股推荐
    """

    def __init__(self, config: Optional[dict[str, Any]] = None):
        self.config = dict(DEFAULT_CONFIG)
        if config:
            self.config.update(config)

    async def run(
        self,
        request: IndustryAnalysisRequest,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> IndustryAnalysisResult:
        start_time = time.perf_counter()
        concept = (request.concept or "").strip()
        if not concept:
            raise ValueError("行业分析概念不能为空")

        logger.info(
            "开始执行行业分析流水线(两阶段): concept=%s, top_n=%s",
            concept,
            request.top_n,
        )

        try:
            await self._report_progress(progress_callback, 0, "开始初始化行业分析模型")
            quick_llm = self._create_llm(role="quick")
            deep_llm = self._create_llm(role="deep")

            concept_mapper = ConceptMapper(quick_llm)
            candidate_fetcher = CandidateFetcher()
            candidate_filter = CandidateFilter()
            stock_comparator = StockComparator(deep_llm)

            # ============================================================
            # 并行执行: A) 行业尽调 + B) 数据获取
            # ============================================================
            await self._report_progress(progress_callback, 5, "阶段1：行业尽调与数据获取并行进行")

            async def _run_due_diligence():
                """Path A: Generate industry due diligence report."""
                await self._report_progress(progress_callback, 10, "正在生成行业尽调报告（深度研究）")
                dd_report = await stock_comparator.generate_due_diligence(concept)
                await self._report_progress(progress_callback, 40, "行业尽调报告已完成")
                return dd_report

            async def _run_data_pipeline():
                """Path B: Concept mapping → fetch → filter."""
                await self._report_progress(progress_callback, 15, "正在进行概念映射")
                mapping = await self._map_concept(concept_mapper, concept)
                mapped_boards = self._collect_mapped_boards(mapping)

                candidates: list[StockCandidate] = []

                if mapped_boards:
                    await self._report_progress(progress_callback, 25, "正在抓取候选股票数据")
                    candidates = await self._fetch_candidates(candidate_fetcher, mapping, concept, mapped_boards)
                else:
                    logger.warning("概念映射未返回有效板块: concept=%s, 将直接使用LLM推荐候选股", concept)

                # LLM fallback when data sources unavailable or mapping returned empty
                if not candidates:
                    await self._report_progress(progress_callback, 30, "使用LLM智能推荐候选股")
                    # Use mapped_boards if available; otherwise derive from concept keywords
                    fallback_boards = mapped_boards or (mapping.keywords if mapping else [concept])
                    candidates = await self._llm_suggest_candidates(quick_llm, concept, fallback_boards)

                if not candidates:
                    raise ValueError(
                        f'概念"{concept}"未能获取到候选股票。请检查网络连接或稍后重试。'
                    )

                await self._report_progress(progress_callback, 35, "正在过滤候选股票")
                filtered = self._filter_candidates(candidate_filter, candidates, request.top_n)

                if not filtered:
                    # If filter removes all, use unfiltered candidates
                    logger.warning("规则过滤后无候选股，使用原始候选列表")
                    filtered = candidates[:max(request.top_n * 3, 15)]

                # Use mapped_boards for display; if empty, use concept as label
                display_boards = mapped_boards or [concept]
                return display_boards, len(candidates), filtered

            # Run both paths in parallel
            dd_report, data_result = await asyncio.gather(
                _run_due_diligence(),
                _run_data_pipeline(),
            )

            mapped_boards, candidate_count, filtered_candidates = data_result
            filtered_count = len(filtered_candidates)

            # ============================================================
            # Stage 2: 基于尽调结果 + 候选数据进行选股
            # ============================================================
            await self._report_progress(progress_callback, 50, "阶段2：基于尽调结果进行选股分析")

            two_stage_result = await stock_comparator.select_stocks(
                concept=concept,
                due_diligence_report=dd_report,
                candidates=filtered_candidates,
                top_n=request.top_n,
            )

            await self._report_progress(progress_callback, 90, "正在整理分析结果")

            # Build final result
            result = IndustryAnalysisResult(
                concept=concept,
                detail_level=request.detail_level,
                mapped_boards=mapped_boards,
                candidate_count=candidate_count,
                filtered_count=filtered_count,
                recommendations=two_stage_result.recommendations,
                market_overview=two_stage_result.market_overview,
                selection_reasoning=two_stage_result.selection_reasoning,
                risk_warning=two_stage_result.risk_warning,
                due_diligence_report=two_stage_result.due_diligence_report,
                stock_selection_report=two_stage_result.stock_selection_report,
                exclusion_reasons=two_stage_result.exclusion_reasons,
                portfolio_advice=two_stage_result.portfolio_advice,
                tracking_indicators=two_stage_result.tracking_indicators,
                conclusion=two_stage_result.conclusion,
                analysis_time=round(time.perf_counter() - start_time, 4),
                llm_calls=3,  # 1 concept mapping + 1 DD + 1 stock selection
                data_date=date.today().isoformat(),
            )

            await self._report_progress(progress_callback, 100, "行业分析完成")
            logger.info(
                "行业分析流水线执行完成: concept=%s, candidate_count=%s, filtered_count=%s, "
                "recommendations=%s, dd_report_len=%s, selection_report_len=%s",
                concept,
                candidate_count,
                filtered_count,
                len(result.recommendations),
                len(result.due_diligence_report),
                len(result.stock_selection_report),
            )
            return result
        except Exception:
            logger.exception("行业分析流水线执行失败: concept=%s", concept)
            raise

    def _create_llm(self, role: str) -> Any:
        provider_key = f"{role}_provider"
        backend_url_key = f"{role}_backend_url"
        model_key = "quick_think_llm" if role == "quick" else "deep_think_llm"
        model_config_key = "quick_model_config" if role == "quick" else "deep_model_config"
        provider = self.config.get(provider_key) or self.config.get("llm_provider")
        model = self.config.get(model_key)
        backend_url = self.config.get(backend_url_key) or self.config.get("backend_url", "")
        api_key = self.config.get(f"{role}_api_key")
        if not api_key:
            api_key = self.config.get("quick_api_key") or self.config.get("deep_api_key")

        if not provider:
            raise ValueError("缺少 llm_provider 配置，无法创建行业分析所需的 LLM 实例")
        if not model:
            raise ValueError(f"缺少 {model_key} 配置，无法创建行业分析所需的 LLM 实例")

        model_config = self.config.get(model_config_key, {})
        temperature = model_config.get("temperature", 0.7)
        max_tokens = model_config.get("max_tokens", 8000)
        timeout = model_config.get("timeout", 300)

        logger.info(
            "创建行业分析LLM: role=%s, provider=%s, model=%s",
            role,
            provider,
            model,
        )
        try:
            return create_llm_by_provider(
                provider=provider,
                model=model,
                backend_url=backend_url,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                api_key=api_key,
            )
        except Exception as exc:
            raise RuntimeError(f"创建{role}阶段LLM实例失败: {exc}") from exc

    async def _map_concept(self, concept_mapper: ConceptMapper, concept: str) -> ConceptMappingResult:
        try:
            return await concept_mapper.map_concept(concept)
        except Exception as exc:
            raise RuntimeError(f"概念映射失败: {exc}") from exc

    async def _fetch_candidates(
        self,
        candidate_fetcher: CandidateFetcher,
        mapping: ConceptMappingResult,
        concept: str,
        mapped_boards: list[str],
    ) -> list[StockCandidate]:
        try:
            candidates = await candidate_fetcher.fetch_candidates(mapping)
        except Exception as exc:
            raise RuntimeError(f"候选股票抓取失败: {exc}") from exc

        if not candidates:
            logger.warning("候选股票抓取结果为空: concept=%s, boards=%s", concept, mapped_boards)
        return candidates

    def _filter_candidates(
        self,
        candidate_filter: CandidateFilter,
        candidates: list[StockCandidate],
        top_n: int,
    ) -> list[StockCandidate]:
        try:
            return candidate_filter.filter(
                candidates,
                max_output=max(top_n, getattr(candidate_filter, "max_candidates", 30)),
            )
        except Exception as exc:
            raise RuntimeError(f"候选股票过滤失败: {exc}") from exc

    async def _report_progress(
        self,
        progress_callback: Optional[ProgressCallback],
        percent: int,
        message: str,
    ) -> None:
        if progress_callback is None:
            return

        try:
            callback_result = progress_callback(percent, message)
            if inspect.isawaitable(callback_result):
                await callback_result
        except Exception as exc:
            logger.warning("行业分析进度回调执行失败: percent=%s, message=%s, error=%s", percent, message, exc)

    def _collect_mapped_boards(self, mapping: ConceptMappingResult) -> list[str]:
        boards = [*(mapping.board_concepts or []), *(mapping.board_industries or [])]
        deduped: list[str] = []
        seen: set[str] = set()
        for board in boards:
            normalized = str(board).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    async def _llm_suggest_candidates(self, llm: Any, concept: str, mapped_boards: list[str]) -> list[StockCandidate]:
        """当数据源无法获取候选股时，让LLM直接推荐股票代码，再从MongoDB验证"""
        prompt = f"""你是A股投资研究助手。当前需要从"{concept}"相关领域中推荐优质候选股票。
相关板块参考: {', '.join(mapped_boards[:5])}

请直接推荐15-25只与"{concept}"概念高度相关的A股股票。要求：
1. 必须是真实存在的A股上市公司
2. 优先选择行业龙头、市值较大、流动性好的标的
3. 涵盖该概念的不同细分方向
4. 只输出JSON，不要输出其他内容

返回JSON格式：
{{
  "stocks": [
    {{"code": "000001", "name": "平安银行", "reason": "金融科技龙头"}},
    ...
  ]
}}"""

        try:
            if hasattr(llm, "ainvoke"):
                try:
                    response = await llm.ainvoke(prompt)
                except Exception:
                    if not hasattr(llm, "invoke"):
                        raise
                    response = await asyncio.to_thread(llm.invoke, prompt)
            elif hasattr(llm, "invoke"):
                response = await asyncio.to_thread(llm.invoke, prompt)
            else:
                return []

            response_text = getattr(response, "content", str(response))
            if isinstance(response_text, list):
                response_text = "\n".join(str(item) for item in response_text)

            import json as json_mod
            import re as re_mod
            json_text = response_text.strip()
            fenced = re_mod.search(r"```(?:json)?\s*(\{.*\})\s*```", json_text, re_mod.DOTALL)
            if fenced:
                json_text = fenced.group(1)
            else:
                start = json_text.find("{")
                end = json_text.rfind("}")
                if start != -1 and end > start:
                    json_text = json_text[start:end + 1]

            payload = json_mod.loads(json_text)
            stocks_raw = payload.get("stocks", [])

            candidates: list[StockCandidate] = []
            for item in stocks_raw:
                code = str(item.get("code", "")).strip().zfill(6)
                if not code or len(code) != 6 or not code.isdigit():
                    continue
                name = str(item.get("name", "")).strip()
                candidates.append(StockCandidate(
                    code=code,
                    name=name,
                    source_boards=mapped_boards[:3],
                    match_score=1.0,
                ))

            if not candidates:
                logger.warning("LLM推荐候选股解析结果为空")
                return []

            # 从MongoDB补充行情数据
            fetcher = CandidateFetcher()
            await fetcher._enrich_from_mongodb(candidates)

            logger.info("LLM直接推荐候选股: concept=%s, count=%s", concept, len(candidates))
            return candidates

        except Exception as exc:
            logger.warning("LLM直接推荐候选股失败: %s", exc)
            return []
