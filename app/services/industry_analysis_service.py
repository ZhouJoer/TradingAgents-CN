from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.database import get_mongo_db
from app.models.industry_analysis import (
    IndustryAnalysisRequest,
    IndustryAnalysisResult,
    IndustryAnalysisStatus,
    IndustryAnalysisTask,
)
from app.utils.timezone import now_tz

logger = logging.getLogger("app.services.industry_analysis_service")

STALE_TASK_MINUTES = 45
STALE_TASK_ERROR = "任务超时或服务器已重启，请重新提交分析。"


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
            created_at=now_tz(),
            updated_at=now_tz(),
        )

        task_doc = task.model_dump()
        task_doc["market"] = request.market

        db = get_mongo_db()
        await db[self.COLLECTION].insert_one(task_doc)
        return await self._serialize_task(task_doc)

    async def get_task(self, task_id: str) -> Optional[dict]:
        db = get_mongo_db()
        task = await db[self.COLLECTION].find_one({"task_id": task_id})
        return await self._serialize_task(task)

    async def list_tasks(self, user_id: str, limit: int = 20) -> List[dict]:
        db = get_mongo_db()
        cursor = (
            db[self.COLLECTION]
            .find({"user_id": user_id})
            .sort("created_at", -1)
            .limit(limit)
        )
        tasks = await cursor.to_list(length=limit)
        serialized = []
        for task in tasks:
            serialized.append(await self._serialize_task(task))
        return serialized

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

            config = self._build_pipeline_config(
                quick_model=request.quick_analysis_model,
                deep_model=request.deep_analysis_model,
            )
            config.update(
                {
                    "market": request.market,
                    "detail_level": request.detail_level.value,
                    "top_n": request.top_n,
                }
            )

            pipeline = IndustryAnalysisPipeline(config=config)

            async def progress_callback(*args, **kwargs):
                updates = self._parse_progress_update(args, kwargs)
                if updates:
                    await self._update_task(task_id, updates)

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
                    "completed_at": now_tz(),
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
                    "completed_at": now_tz(),
                },
            )

    async def _update_task(self, task_id: str, updates: dict):
        if not updates:
            return

        payload = dict(updates)
        payload["updated_at"] = now_tz()

        db = get_mongo_db()
        await db[self.COLLECTION].update_one(
            {"task_id": task_id},
            {"$set": payload},
        )

    def _build_pipeline_config(
        self,
        quick_model: Optional[str] = None,
        deep_model: Optional[str] = None,
    ) -> dict:
        """构建 pipeline 配置，复用单股/批量分析共用的 LLM 选择逻辑。"""
        from app.services.llm_config_service import build_llm_provider_config, validate_llm_provider_config

        config = build_llm_provider_config(
            quick_model=quick_model,
            deep_model=deep_model,
            research_depth="标准",
        )
        validate_llm_provider_config(config)
        return config

    def _serialize_result(self, result: Any) -> Dict[str, Any]:
        if isinstance(result, IndustryAnalysisResult):
            return result.model_dump(mode="json")
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        if isinstance(result, dict):
            return result
        raise TypeError("Industry analysis result is not serializable")

    async def _serialize_task(self, task: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not task:
            return None

        data = dict(task)
        data.pop("_id", None)
        return await self._maybe_mark_stale_task(data)

    def _task_updated_at_utc(self, updated_at: Any) -> Optional[datetime]:
        if not isinstance(updated_at, datetime):
            return None
        if updated_at.tzinfo is None:
            return updated_at.replace(tzinfo=timezone.utc)
        return updated_at.astimezone(timezone.utc)

    async def _maybe_mark_stale_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        status = task.get("status")
        if status not in (
            IndustryAnalysisStatus.PENDING.value,
            IndustryAnalysisStatus.RUNNING.value,
        ):
            return task

        updated_at = self._task_updated_at_utc(task.get("updated_at"))
        if updated_at is None:
            return task

        age_seconds = (datetime.now(timezone.utc) - updated_at).total_seconds()
        if age_seconds <= STALE_TASK_MINUTES * 60:
            return task

        task_id = task.get("task_id")
        if task_id:
            await self._update_task(
                task_id,
                {
                    "status": IndustryAnalysisStatus.FAILED.value,
                    "error": STALE_TASK_ERROR,
                    "progress_message": STALE_TASK_ERROR,
                    "completed_at": now_tz(),
                },
            )

        task["status"] = IndustryAnalysisStatus.FAILED.value
        task["error"] = STALE_TASK_ERROR
        task["progress_message"] = STALE_TASK_ERROR
        return task

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
