from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services.report_review_service import ReportReviewService


router = APIRouter(prefix="/api/reviews", tags=["reviews"])


class ManualReviewResultRequest(BaseModel):
    notes: str = Field(..., min_length=1)
    outcome: Optional[str] = None


@router.get("/tasks")
async def list_review_tasks(
    stock_symbol: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
):
    service = ReportReviewService()
    data = await service.list_review_tasks(
        user=user,
        stock_symbol=stock_symbol,
        status=status,
        limit=limit,
        offset=offset,
    )
    return ok(data=data, message="复盘任务列表获取成功")


@router.get("/tasks/{review_id}")
async def get_review_task(review_id: str, user: dict = Depends(get_current_user)):
    service = ReportReviewService()
    data = await service.get_review_task(review_id, user)
    return ok(data=data, message="复盘任务详情获取成功")


@router.post("/tasks/{review_id}/run")
async def run_review_task(review_id: str, user: dict = Depends(get_current_user)):
    service = ReportReviewService()
    data = await service.run_review_task(review_id, user)
    return ok(data=data, message="复盘检查完成")


@router.post("/tasks/{review_id}/llm-evaluate")
async def llm_evaluate_review_task(review_id: str, user: dict = Depends(get_current_user)):
    service = ReportReviewService()
    data = await service.llm_evaluate_review_task(review_id, user)
    return ok(data=data, message="LLM复盘评审完成")


@router.post("/tasks/{review_id}/manual-result")
async def update_manual_review_result(
    review_id: str,
    request: ManualReviewResultRequest,
    user: dict = Depends(get_current_user),
):
    service = ReportReviewService()
    data = await service.update_manual_result(
        review_id=review_id,
        user=user,
        notes=request.notes,
        outcome=request.outcome,
    )
    return ok(data=data, message="人工复盘结论已保存")


@router.get("/evaluations/{evaluation_id}")
async def get_review_evaluation(evaluation_id: str, user: dict = Depends(get_current_user)):
    service = ReportReviewService()
    data = await service.get_evaluation(evaluation_id, user)
    return ok(data=data, message="LLM复盘评审详情获取成功")

