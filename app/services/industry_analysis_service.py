from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.database import get_mongo_db
from app.models.industry_analysis import (
    IndustryAnalysisRequest,
    IndustryAnalysisResult,
    IndustryAnalysisStatus,
    IndustryAnalysisTask,
)

logger = logging.getLogger("app.services.industry_analysis_service")


class IndustryAnalysisService:
    COLLECTION = "industry_analysis_tasks"

    def __init__(self):
        pass

    async def create_task(self, user_id: str, request: IndustryAnalysisRequest) -> dict:
        task = IndustryAnalysisTask(
            task_id=str(uuid.uuid4()),
            user_id=user_id,
            concept=request.concept,
            detail_level=request.detail_level,
            top_n=request.top_n,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        task_doc = task.model_dump()
        task_doc["market"] = request.market

        db = get_mongo_db()
        await db[self.COLLECTION].insert_one(task_doc)
        return self._serialize_task(task_doc)

    async def get_task(self, task_id: str) -> Optional[dict]:
        db = get_mongo_db()
        task = await db[self.COLLECTION].find_one({"task_id": task_id})
        return self._serialize_task(task)

    async def list_tasks(self, user_id: str, limit: int = 20) -> List[dict]:
        db = get_mongo_db()
        cursor = (
            db[self.COLLECTION]
            .find({"user_id": user_id})
            .sort("created_at", -1)
            .limit(limit)
        )
        tasks = await cursor.to_list(length=limit)
        return [self._serialize_task(task) for task in tasks]

    async def delete_task(self, task_id: str, user_id: str) -> bool:
        """Delete a task. Returns True if deleted, False if not found."""
        db = get_mongo_db()
        result = await db[self.COLLECTION].delete_one({"task_id": task_id, "user_id": user_id})
        return result.deleted_count > 0

    async def execute_task(self, task_id: str, user_id: str, request: IndustryAnalysisRequest):
        await self._update_task(
            task_id,
            {
                "status": IndustryAnalysisStatus.RUNNING.value,
                "progress": 5,
                "progress_message": "正在初始化行业分析任务...",
                "error": None,
            },
        )

        try:
            from tradingagents.industry_analysis.pipeline import IndustryAnalysisPipeline

            config = await self._build_pipeline_config()
            config.update(
                {
                    "market": request.market,
                    "detail_level": request.detail_level.value,
                    "top_n": request.top_n,
                }
            )

            pipeline = IndustryAnalysisPipeline(config=config)

            def progress_callback(*args, **kwargs):
                updates = self._parse_progress_update(args, kwargs)
                if updates:
                    asyncio.create_task(self._update_task(task_id, updates))

            result = await pipeline.run(request=request, progress_callback=progress_callback)
            result_payload = self._serialize_result(result)

            await self._update_task(
                task_id,
                {
                    "user_id": user_id,
                    "status": IndustryAnalysisStatus.COMPLETED.value,
                    "progress": 100,
                    "progress_message": "行业分析已完成",
                    "result": result_payload,
                    "error": None,
                    "completed_at": datetime.utcnow(),
                },
            )
        except Exception as exc:
            logger.exception("行业分析任务执行失败: %s", task_id)
            await self._update_task(
                task_id,
                {
                    "status": IndustryAnalysisStatus.FAILED.value,
                    "progress_message": "行业分析执行失败",
                    "error": str(exc),
                    "completed_at": datetime.utcnow(),
                },
            )

    async def _update_task(self, task_id: str, updates: dict):
        if not updates:
            return

        payload = dict(updates)
        payload["updated_at"] = datetime.utcnow()

        db = get_mongo_db()
        await db[self.COLLECTION].update_one(
            {"task_id": task_id},
            {"$set": payload},
        )

    async def _build_pipeline_config(self) -> dict:
        """
        构建pipeline配置，使用与现有分析服务相同的模型选择逻辑：
        1. 通过 model_capability_service 自动推荐已启用的模型
        2. 通过 get_provider_and_url_by_model_sync 从数据库查找 provider/url/key
        """
        from app.services.model_capability_service import get_model_capability_service
        from app.services.simple_analysis_service import get_provider_and_url_by_model_sync

        # 使用 model_capability_service 选择已启用的模型（与现有分析一致）
        capability_service = get_model_capability_service()
        quick_model, deep_model = capability_service.recommend_models_for_depth("标准")
        logger.info(f"🤖 行业分析模型选择: quick={quick_model}, deep={deep_model}")

        # 从数据库查找供应商、URL、API Key（与现有分析一致）
        quick_provider_info = get_provider_and_url_by_model_sync(quick_model)
        deep_provider_info = get_provider_and_url_by_model_sync(deep_model)

        logger.info(f"🔍 快速模型: {quick_model} -> provider={quick_provider_info['provider']}, url={quick_provider_info['backend_url']}")
        logger.info(f"🔍 深度模型: {deep_model} -> provider={deep_provider_info['provider']}, url={deep_provider_info['backend_url']}")

        return {
            "llm_provider": quick_provider_info["provider"],
            "quick_think_llm": quick_model,
            "deep_think_llm": deep_model,
            "backend_url": quick_provider_info["backend_url"],
            "api_key": quick_provider_info["api_key"],
            "quick_provider": quick_provider_info["provider"],
            "deep_provider": deep_provider_info["provider"],
            "quick_backend_url": quick_provider_info["backend_url"],
            "deep_backend_url": deep_provider_info["backend_url"],
            "quick_api_key": quick_provider_info["api_key"],
            "deep_api_key": deep_provider_info["api_key"],
            "quick_model_config": {},
            "deep_model_config": {},
            "debug": False,
        }

    def _serialize_result(self, result: Any) -> Dict[str, Any]:
        if isinstance(result, IndustryAnalysisResult):
            return result.model_dump(mode="json")
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        if isinstance(result, dict):
            return result
        raise TypeError("Industry analysis result is not serializable")

    def _serialize_task(self, task: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not task:
            return None

        data = dict(task)
        data.pop("_id", None)
        return data

    def _parse_progress_update(self, args: tuple, kwargs: dict) -> Dict[str, Any]:
        progress = kwargs["progress"] if "progress" in kwargs else kwargs.get("percent")
        message = (
            kwargs["message"]
            if "message" in kwargs
            else kwargs.get("progress_message") or kwargs.get("status")
        )

        if len(args) == 1:
            payload = args[0]
            if isinstance(payload, dict):
                progress = payload.get("progress", progress)
                message = payload.get("message") or payload.get("progress_message") or message
            elif isinstance(payload, str):
                message = payload
            elif isinstance(payload, (int, float)):
                progress = payload
        elif len(args) >= 2:
            first, second = args[0], args[1]
            if isinstance(first, (int, float)):
                progress = first
                message = str(second)
            elif isinstance(second, (int, float)):
                message = str(first)
                progress = second
            else:
                message = str(first)

        step = kwargs.get("step")
        total_steps = kwargs.get("total_steps")
        if progress is None and isinstance(step, (int, float)) and isinstance(total_steps, (int, float)) and total_steps:
            progress = int(step / total_steps * 100)

        updates: Dict[str, Any] = {}
        if progress is not None:
            updates["progress"] = max(0, min(int(progress), 99))
        if message:
            updates["progress_message"] = str(message)
        return updates


_industry_analysis_service: Optional[IndustryAnalysisService] = None


def get_industry_analysis_service() -> IndustryAnalysisService:
    global _industry_analysis_service
    if _industry_analysis_service is None:
        _industry_analysis_service = IndustryAnalysisService()
    return _industry_analysis_service
