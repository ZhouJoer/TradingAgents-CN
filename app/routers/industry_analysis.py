"""Industry analysis API routes."""

import logging
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.models.industry_analysis import IndustryAnalysisRequest
from app.routers.auth_db import get_current_user
from app.services.industry_analysis_service import get_industry_analysis_service

router = APIRouter()
logger = logging.getLogger("webapi")


@router.post("", response_model=Dict[str, Any])
async def submit_industry_analysis(
    request: IndustryAnalysisRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    try:
        service = get_industry_analysis_service()
        result = await service.create_task(user["id"], request)
        task_id = result["task_id"]
        user_id = user["id"]

        async def run_task():
            try:
                await get_industry_analysis_service().execute_background(task_id, user_id, request)
            except Exception as exc:
                logger.error("Industry analysis background task failed: %s", exc, exc_info=True)

        background_tasks.add_task(run_task)
        return {
            "success": True,
            "data": result,
            "message": "行业分析任务已在后台启动",
        }
    except Exception as exc:
        logger.error("Submit industry analysis failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/tasks/{task_id}/status", response_model=Dict[str, Any])
async def get_industry_task_status(
    task_id: str,
    user: dict = Depends(get_current_user),
):
    service = get_industry_analysis_service()
    result = await service.get_task_status(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="行业分析任务不存在")
    return {
        "success": True,
        "data": result,
        "message": "任务状态获取成功",
    }


@router.get("/tasks/{task_id}/result", response_model=Dict[str, Any])
async def get_industry_task_result(
    task_id: str,
    user: dict = Depends(get_current_user),
):
    service = get_industry_analysis_service()
    result = await service.get_task_result(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="行业分析结果不存在或尚未完成")
    return {
        "success": True,
        "data": result,
        "message": "行业分析结果获取成功",
    }
