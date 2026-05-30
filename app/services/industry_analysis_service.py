"""Industry due diligence and A-share stock selection service."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.database import get_mongo_db
from app.models.analysis import AnalysisStatus
from app.models.industry_analysis import (
    IndustryAnalysisParameters,
    IndustryAnalysisRequest,
    IndustryAnalysisResult,
    IndustryStockPick,
)
from app.services.industry_web_research import (
    build_authority_queries,
    get_industry_web_research_provider,
)
from app.services.simple_analysis_service import get_provider_and_url_by_model_sync
from tradingagents.llm_clients import create_llm_client

logger = logging.getLogger(__name__)


class IndustryAnalysisService:
    def __init__(self) -> None:
        self._tasks: Dict[str, Dict[str, Any]] = {}

    async def create_task(self, user_id: str, request: IndustryAnalysisRequest) -> Dict[str, Any]:
        params = request.parameters or IndustryAnalysisParameters()
        task_id = f"industry_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()
        task_doc = {
            "task_id": task_id,
            "task_type": "industry_analysis",
            "user_id": user_id,
            "industry_query": request.industry_query.strip(),
            "symbol": "INDUSTRY",
            "stock_code": "INDUSTRY",
            "stock_symbol": "INDUSTRY",
            "stock_name": request.industry_query.strip(),
            "status": AnalysisStatus.PENDING.value,
            "progress": 0,
            "message": "任务已创建，等待执行",
            "current_step": "pending",
            "parameters": params.model_dump(),
            "created_at": now,
            "updated_at": now,
        }
        self._tasks[task_id] = dict(task_doc)

        try:
            db = get_mongo_db()
            await db.analysis_tasks.update_one(
                {"task_id": task_id},
                {"$setOnInsert": task_doc},
                upsert=True,
            )
        except Exception as exc:
            logger.warning("Failed to persist industry analysis task %s: %s", task_id, exc)

        return {
            "task_id": task_id,
            "status": AnalysisStatus.PENDING.value,
            "message": "行业分析任务已创建",
        }

    async def execute_background(
        self,
        task_id: str,
        user_id: str,
        request: IndustryAnalysisRequest,
    ) -> None:
        started = time.time()
        params = request.parameters or IndustryAnalysisParameters()
        try:
            await self._update_task(task_id, AnalysisStatus.PROCESSING, 8, "解析行业概念", "keyword_expansion")
            keywords = await self._expand_keywords(request.industry_query, params)

            await self._update_task(task_id, AnalysisStatus.PROCESSING, 22, "检索权威资料", "web_research")
            sources, web_status = await self._collect_sources(keywords, params)

            await self._update_task(task_id, AnalysisStatus.PROCESSING, 42, "生成行业尽调", "due_diligence")
            due_diligence_report = await self._generate_due_diligence_report(
                request.industry_query, keywords, sources, params, web_status
            )

            await self._update_task(task_id, AnalysisStatus.PROCESSING, 62, "召回A股候选池", "candidate_pool")
            candidates = await self._load_candidate_pool(request.industry_query, keywords)

            await self._update_task(task_id, AnalysisStatus.PROCESSING, 78, "多维度评分选股", "stock_scoring")
            picks = self._score_candidates(candidates, request.industry_query, keywords, params.top_n)

            await self._update_task(task_id, AnalysisStatus.PROCESSING, 90, "生成选股报告", "stock_selection_report")
            stock_selection_report = await self._generate_stock_selection_report(
                request.industry_query, due_diligence_report, picks, params
            )

            summary = self._build_summary(request.industry_query, picks, web_status)
            result = IndustryAnalysisResult(
                analysis_id=str(uuid.uuid4()),
                industry_query=request.industry_query.strip(),
                market=params.market,
                top_n=params.top_n,
                summary=summary,
                due_diligence_report=due_diligence_report,
                stock_selection_report=stock_selection_report,
                picks=picks,
                candidates_count=len(candidates),
                keywords=keywords,
                sources=[s.to_dict() for s in sources],
                web_search_enabled=bool(sources),
                web_search_status=web_status,
                execution_time=round(time.time() - started, 2),
                model_info=params.deep_analysis_model or params.quick_analysis_model,
            )
            await self._save_result(task_id, user_id, result)
            await self._update_task(
                task_id,
                AnalysisStatus.COMPLETED,
                100,
                "行业分析完成",
                "completed",
                result=result.model_dump(mode="json"),
            )
        except Exception as exc:
            logger.error("Industry analysis failed: %s", exc, exc_info=True)
            await self._update_task(
                task_id,
                AnalysisStatus.FAILED,
                0,
                f"行业分析失败: {exc}",
                "failed",
                error_message=str(exc),
            )

    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self._tasks.get(task_id)
        if task:
            return dict(task)

        try:
            db = get_mongo_db()
            doc = await db.analysis_tasks.find_one({"task_id": task_id, "task_type": "industry_analysis"})
            if doc:
                doc["_id"] = str(doc.get("_id"))
                return doc
        except Exception as exc:
            logger.warning("Failed to load industry task status %s: %s", task_id, exc)
        return None

    async def get_task_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self._tasks.get(task_id)
        if task and task.get("result"):
            return task["result"]

        try:
            db = get_mongo_db()
            report = await db.industry_analysis_reports.find_one({"task_id": task_id})
            if report:
                report["_id"] = str(report.get("_id"))
                return report.get("result") or report
            task_doc = await db.analysis_tasks.find_one({"task_id": task_id, "task_type": "industry_analysis"})
            if task_doc and task_doc.get("result"):
                return task_doc["result"]
        except Exception as exc:
            logger.warning("Failed to load industry result %s: %s", task_id, exc)
        return None

    async def _update_task(
        self,
        task_id: str,
        status: AnalysisStatus,
        progress: int,
        message: str,
        current_step: str,
        result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> None:
        now = datetime.utcnow()
        update = {
            "status": status.value,
            "progress": progress,
            "message": message,
            "current_step": current_step,
            "updated_at": now,
        }
        if status == AnalysisStatus.PROCESSING and current_step == "keyword_expansion":
            update["started_at"] = now
        if status in (AnalysisStatus.COMPLETED, AnalysisStatus.FAILED):
            update["completed_at"] = now
        if result is not None:
            update["result"] = result
        if error_message:
            update["last_error"] = error_message

        cached = self._tasks.setdefault(task_id, {"task_id": task_id})
        cached.update(update)

        try:
            db = get_mongo_db()
            await db.analysis_tasks.update_one({"task_id": task_id}, {"$set": update})
        except Exception as exc:
            logger.warning("Failed to update industry task %s: %s", task_id, exc)

    async def _expand_keywords(self, industry_query: str, params: IndustryAnalysisParameters) -> List[str]:
        fallback = self._fallback_keywords(industry_query)
        prompt = (
            "请把用户输入的行业或投资概念扩展为适合检索政策、行业报告和A股公司的中文关键词。"
            "只返回JSON数组，不要解释。"
            f"\n用户输入: {industry_query}\n示例输出: [\"算力\", \"AI服务器\", \"光模块\"]"
        )
        content = await self._invoke_llm(prompt, params.quick_analysis_model, max_tokens=400)
        parsed = self._parse_json_array(content)
        keywords = [str(item).strip() for item in parsed if str(item).strip()] if parsed else []
        keywords = [industry_query.strip(), *keywords, *fallback]
        return self._unique(keywords)[:8]

    async def _collect_sources(
        self,
        keywords: List[str],
        params: IndustryAnalysisParameters,
    ):
        if not params.enable_web_search:
            return [], "联网检索已关闭"

        try:
            provider = get_industry_web_research_provider()
            queries = build_authority_queries(keywords[:4])
            sources = await provider.search(queries, max_results=settings.INDUSTRY_WEB_SEARCH_MAX_RESULTS)
            if not sources:
                return [], "未获取到可用权威来源，已降级为本地数据分析"
            return sources, f"已获取{len(sources)}条权威来源"
        except Exception as exc:
            logger.warning("Industry web research failed: %s", exc)
            return [], f"联网检索失败，已降级: {exc}"

    async def _generate_due_diligence_report(
        self,
        industry_query: str,
        keywords: List[str],
        sources: List[Any],
        params: IndustryAnalysisParameters,
        web_status: str,
    ) -> str:
        source_lines = "\n".join(
            f"- [{idx + 1}] {s.title} | {s.source or s.domain} | {s.published_at or '日期未知'} | {s.url}\n  摘要: {s.snippet[:240]}"
            for idx, s in enumerate(sources[:12])
        )
        if not source_lines:
            source_lines = f"- {web_status}"

        prompt = f"""
你是一名A股行业研究员。请基于权威来源和常识完成行业尽调，结论先行，避免虚构来源。

用户概念: {industry_query}
扩展关键词: {", ".join(keywords)}
联网资料:
{source_lines}

请输出中文Markdown，包含:
1. 核心结论
2. 概念边界与产业链
3. 政策、周期和需求验证
4. 行业竞争格局与发展前景
5. 关键风险矩阵
6. 资料依据与AI推断分开说明
7. 免责声明: 仅供研究参考，不构成投资建议
"""
        content = await self._invoke_llm(prompt, params.deep_analysis_model, max_tokens=2500)
        if content:
            return content
        return self._fallback_due_diligence(industry_query, keywords, sources, web_status)

    async def _load_candidate_pool(self, industry_query: str, keywords: List[str]) -> List[Dict[str, Any]]:
        fields = {
            "_id": 0,
            "code": 1,
            "name": 1,
            "industry": 1,
            "area": 1,
            "market": 1,
            "total_mv": 1,
            "circ_mv": 1,
            "pe": 1,
            "pb": 1,
            "pe_ttm": 1,
            "pb_mrq": 1,
            "roe": 1,
            "roa": 1,
            "netprofit_margin": 1,
            "gross_margin": 1,
            "turnover_rate": 1,
            "volume_ratio": 1,
            "pct_chg": 1,
            "amount": 1,
            "close": 1,
            "source": 1,
        }
        db = get_mongo_db()
        collection = db["stock_screening_view"]

        regex_terms = [re.escape(k) for k in keywords if k and len(k) <= 30]
        or_conditions = []
        for term in regex_terms:
            or_conditions.extend(
                [
                    {"name": {"$regex": term, "$options": "i"}},
                    {"industry": {"$regex": term, "$options": "i"}},
                ]
            )
        base_query: Dict[str, Any] = {"code": {"$regex": r"^\d{6}$"}}
        query = dict(base_query)
        if or_conditions:
            query["$or"] = or_conditions

        try:
            docs = await self._find_candidates(collection, query, fields)
            if not docs and industry_query:
                query = dict(base_query)
                query["$or"] = [
                    {"name": {"$regex": re.escape(industry_query), "$options": "i"}},
                    {"industry": {"$regex": re.escape(industry_query), "$options": "i"}},
                ]
                docs = await self._find_candidates(collection, query, fields)
            if not docs:
                docs = await self._find_candidates(collection, base_query, fields)
        except Exception as exc:
            logger.warning("stock_screening_view unavailable, fallback to stock_basic_info: %s", exc)
            basic_collection = db["stock_basic_info"]
            docs = await self._find_candidates(basic_collection, query, fields)
            if not docs:
                docs = await self._find_candidates(basic_collection, base_query, fields)
        return docs

    async def _find_candidates(self, collection, query: Dict[str, Any], fields: Dict[str, int]) -> List[Dict[str, Any]]:
        cursor = collection.find(query, fields).sort([("total_mv", -1), ("amount", -1)]).limit(300)
        seen = set()
        results: List[Dict[str, Any]] = []
        async for doc in cursor:
            code = str(doc.get("code") or "").zfill(6)
            if not code or code in seen:
                continue
            seen.add(code)
            doc["code"] = code
            results.append(doc)
            if len(results) >= 80:
                break
        return results

    def _score_candidates(
        self,
        candidates: List[Dict[str, Any]],
        industry_query: str,
        keywords: List[str],
        top_n: int,
    ) -> List[IndustryStockPick]:
        if not candidates:
            return []

        max_mv = max([self._num(c.get("total_mv")) for c in candidates] or [1]) or 1
        max_amount = max([self._num(c.get("amount")) for c in candidates] or [1]) or 1
        picks: List[IndustryStockPick] = []
        for c in candidates:
            name = str(c.get("name") or "")
            industry = str(c.get("industry") or "")
            text = f"{name} {industry}"
            match_count = sum(1 for kw in keywords if kw and kw in text)
            direct_match = industry_query in text
            relevance = min(15.0, (8 if direct_match else 4) + match_count * 2.2)

            mv = self._num(c.get("total_mv"))
            amount = self._num(c.get("amount"))
            roe = self._num(c.get("roe"))
            pe = self._num(c.get("pe_ttm") or c.get("pe"))
            pb = self._num(c.get("pb_mrq") or c.get("pb"))
            pct_chg = self._num(c.get("pct_chg"))
            turnover = self._num(c.get("turnover_rate"))
            gross_margin = self._num(c.get("gross_margin"))
            net_margin = self._num(c.get("netprofit_margin"))

            industry_position = min(15.0, 6 + 9 * math.sqrt(max(mv, 0) / max_mv))
            prospects = min(18.0, 6 + relevance * 0.55 + min(4, amount / max_amount * 4))
            fundamentals = min(18.0, 6 + max(0, min(roe, 25)) * 0.28 + max(0, min(gross_margin, 60)) * 0.06)
            technical = min(14.0, 5 + self._technical_bonus(pct_chg, turnover) + min(3, amount / max_amount * 3))
            financial = min(12.0, 4 + max(0, min(roe, 25)) * 0.22 + max(0, min(net_margin, 30)) * 0.08)
            valuation = self._valuation_score(pe, pb)
            risk_deduction = self._risk_deduction(name, roe, pe, pb, pct_chg)

            scores = {
                "概念相关性": round(relevance, 2),
                "行业地位": round(industry_position, 2),
                "发展前景": round(prospects, 2),
                "基本面": round(fundamentals, 2),
                "技术面": round(technical, 2),
                "财务状况": round(financial, 2),
                "估值": round(valuation, 2),
            }
            total = max(0.0, sum(scores.values()) - risk_deduction)
            picks.append(
                IndustryStockPick(
                    code=str(c.get("code")),
                    name=name,
                    industry=industry or None,
                    total_score=round(total, 2),
                    scores=scores,
                    risk_deduction=round(risk_deduction, 2),
                    reason=self._build_pick_reason(name, industry, scores),
                    risk=self._build_pick_risk(name, risk_deduction, pe, pb),
                    metrics={
                        "close": c.get("close"),
                        "pct_chg": c.get("pct_chg"),
                        "total_mv": c.get("total_mv"),
                        "pe": pe or None,
                        "pb": pb or None,
                        "roe": roe or None,
                        "amount": c.get("amount"),
                    },
                )
            )

        picks.sort(key=lambda item: item.total_score, reverse=True)
        return picks[:top_n]

    async def _generate_stock_selection_report(
        self,
        industry_query: str,
        due_diligence_report: str,
        picks: List[IndustryStockPick],
        params: IndustryAnalysisParameters,
    ) -> str:
        picks_json = json.dumps([p.model_dump() for p in picks], ensure_ascii=False, indent=2)
        prompt = f"""
你是一名A股策略分析师。请基于行业尽调摘要和候选股票评分，生成Top {params.top_n}选股报告。

行业/概念: {industry_query}
行业尽调摘要:
{due_diligence_report[:3000]}

候选评分:
{picks_json}

请输出中文Markdown，包含Top股票表格、推荐理由、主要风险、组合建议，并声明仅供研究参考，不构成投资建议。
不要新增候选池之外的股票代码。
"""
        content = await self._invoke_llm(prompt, params.deep_analysis_model, max_tokens=2200)
        if content:
            return content
        return self._fallback_selection_report(industry_query, picks)

    async def _invoke_llm(self, prompt: str, model_name: Optional[str], max_tokens: int = 1500) -> str:
        if not model_name:
            return ""

        def call() -> str:
            provider_info = get_provider_and_url_by_model_sync(model_name)
            client = create_llm_client(
                provider_info.get("provider"),
                model_name,
                provider_info.get("backend_url"),
                api_key=provider_info.get("api_key"),
                temperature=0.2,
                max_tokens=max_tokens,
                timeout=120,
            )
            response = client.get_llm().invoke(prompt)
            return str(getattr(response, "content", response) or "").strip()

        try:
            return await asyncio.to_thread(call)
        except Exception as exc:
            logger.warning("Industry LLM call failed, using fallback: %s", exc)
            return ""

    async def _save_result(self, task_id: str, user_id: str, result: IndustryAnalysisResult) -> None:
        document = {
            "task_id": task_id,
            "analysis_id": result.analysis_id,
            "user_id": user_id,
            "industry_query": result.industry_query,
            "result": result.model_dump(mode="json"),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        try:
            db = get_mongo_db()
            await db.industry_analysis_reports.insert_one(document)
            await db.analysis_tasks.update_one(
                {"task_id": task_id},
                {"$set": {"result": result.model_dump(mode="json")}},
            )
        except Exception as exc:
            logger.warning("Failed to save industry analysis result %s: %s", task_id, exc)

    def _fallback_keywords(self, industry_query: str) -> List[str]:
        query = industry_query.strip()
        if any(k in query for k in ("AI", "人工智能", "大模型")):
            return ["人工智能", "算力", "AI服务器", "光模块", "半导体", "数据中心"]
        if any(k in query for k in ("高股息", "红利", "分红")):
            return ["高股息", "现金分红", "央企", "银行", "公用事业", "煤炭"]
        if any(k in query for k in ("传统", "周期")):
            return ["传统行业", "周期", "煤炭", "钢铁", "建筑材料", "公用事业"]
        return [query, f"{query}行业", f"{query}概念", f"{query}产业链"]

    def _fallback_due_diligence(self, industry_query: str, keywords: List[str], sources: List[Any], web_status: str) -> str:
        source_text = "\n".join(f"- {s.title} ({s.domain}) {s.url}" for s in sources[:8]) or f"- {web_status}"
        return f"""# {industry_query}行业尽调

## 核心结论
{industry_query}的分析已基于可用权威资料和本地A股数据完成。当前联网状态：{web_status}。

## 概念边界
相关关键词包括：{", ".join(keywords)}。

## 资料依据
{source_text}

## AI推断
后续选股更重视概念相关性、行业地位、盈利质量、估值约束和短期交易状态。

## 风险提示
需关注政策变化、需求验证不足、估值过高、业绩波动和交易拥挤。

仅供研究参考，不构成投资建议。
"""

    def _fallback_selection_report(self, industry_query: str, picks: List[IndustryStockPick]) -> str:
        rows = "\n".join(
            f"| {idx + 1} | {p.code} | {p.name} | {p.industry or '-'} | {p.total_score:.2f} | {p.reason} |"
            for idx, p in enumerate(picks)
        )
        return f"""# {industry_query} Top {len(picks)} A股选股结果

| 排名 | 代码 | 名称 | 行业 | 总分 | 推荐理由 |
|---|---|---|---|---:|---|
{rows}

## 组合建议
优先关注评分靠前且风险扣分较低的标的，避免单一主题过度集中。

## 免责声明
仅供研究参考，不构成投资建议。
"""

    def _build_summary(self, industry_query: str, picks: List[IndustryStockPick], web_status: str) -> str:
        if not picks:
            return f"{industry_query}分析完成，但本地A股候选池不足。{web_status}。"
        names = "、".join(f"{p.name}({p.code})" for p in picks[:3])
        return f"{industry_query}分析完成，Top候选包括{names}等。{web_status}。仅供研究参考，不构成投资建议。"

    def _parse_json_array(self, content: str) -> Optional[List[Any]]:
        if not content:
            return None
        try:
            return json.loads(content)
        except Exception:
            match = re.search(r"\[[\s\S]*\]", content)
            if not match:
                return None
            try:
                return json.loads(match.group(0))
            except Exception:
                return None

    def _unique(self, values: List[str]) -> List[str]:
        seen = set()
        result = []
        for value in values:
            clean = str(value).strip()
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result

    def _num(self, value: Any) -> float:
        try:
            if value is None or value == "":
                return 0.0
            return float(value)
        except Exception:
            return 0.0

    def _technical_bonus(self, pct_chg: float, turnover: float) -> float:
        trend = 3.0 if 0 <= pct_chg <= 6 else 1.5 if -3 <= pct_chg < 0 else 0.5
        liquidity = min(3.0, max(0.0, turnover) * 0.25)
        return trend + liquidity

    def _valuation_score(self, pe: float, pb: float) -> float:
        score = 4.0
        if 0 < pe <= 35:
            score += 2.5
        elif 35 < pe <= 60:
            score += 1.0
        if 0 < pb <= 4:
            score += 1.5
        elif 4 < pb <= 8:
            score += 0.5
        return min(8.0, score)

    def _risk_deduction(self, name: str, roe: float, pe: float, pb: float, pct_chg: float) -> float:
        risk = 0.0
        if "ST" in name.upper():
            risk += 10
        if roe < 0:
            risk += 5
        if pe > 80:
            risk += 4
        if pb > 10:
            risk += 3
        if pct_chg < -7:
            risk += 3
        return min(20.0, risk)

    def _build_pick_reason(self, name: str, industry: str, scores: Dict[str, float]) -> str:
        best = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:2]
        best_text = "、".join(k for k, _ in best)
        return f"{name}属于{industry or '相关'}方向，主要优势在{best_text}。"

    def _build_pick_risk(self, name: str, risk_deduction: float, pe: float, pb: float) -> str:
        risks = []
        if risk_deduction >= 8:
            risks.append("综合风险扣分较高")
        if pe > 60:
            risks.append("估值偏高")
        if pb > 8:
            risks.append("市净率偏高")
        return "；".join(risks) if risks else f"{name}仍需关注业绩兑现和市场波动。"


_industry_analysis_service: Optional[IndustryAnalysisService] = None


def get_industry_analysis_service() -> IndustryAnalysisService:
    global _industry_analysis_service
    if _industry_analysis_service is None:
        _industry_analysis_service = IndustryAnalysisService()
    return _industry_analysis_service
