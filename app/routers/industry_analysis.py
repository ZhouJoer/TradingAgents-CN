import json
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from starlette.responses import StreamingResponse

from app.models.industry_analysis import IndustryAnalysisRequest
from app.routers.auth_db import get_current_user
from app.services.industry_analysis_service import get_industry_analysis_service
from app.utils.industry_analysis_report import build_industry_markdown_report

router = APIRouter(tags=["industry-analysis"])
logger = logging.getLogger("webapi")


def _ensure_task_access(task: Optional[dict], user_id: str) -> dict:
    if not task or task.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


def _stream_bytes(content: bytes):
    yield content


@router.post("/submit")
async def submit_industry_analysis(
    request: IndustryAnalysisRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """Submit an industry analysis task"""
    try:
        service = get_industry_analysis_service()
        task = await service.create_task(user["id"], request)

        background_tasks.add_task(
            service.execute_task,
            task["task_id"],
            user["id"],
            request,
        )

        return {
            "success": True,
            "data": task,
            "message": "行业分析任务已提交",
        }
    except Exception as exc:
        logger.error("提交行业分析任务失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/result/{task_id}")
async def get_industry_analysis_result(
    task_id: str,
    user: dict = Depends(get_current_user),
):
    """Get task status and result"""
    try:
        service = get_industry_analysis_service()
        task = _ensure_task_access(await service.get_task(task_id), user["id"])

        return {
            "success": True,
            "data": task,
            "message": "行业分析任务获取成功",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("获取行业分析结果失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/history")
async def get_industry_analysis_history(
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """List user's analysis history"""
    try:
        service = get_industry_analysis_service()
        tasks = await service.list_tasks(user["id"], limit=limit)
        return {
            "success": True,
            "data": tasks,
            "message": "行业分析历史获取成功",
        }
    except Exception as exc:
        logger.error("获取行业分析历史失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{task_id}")
async def delete_industry_analysis_task(
    task_id: str,
    user: dict = Depends(get_current_user),
):
    """Delete an industry analysis task"""
    try:
        service = get_industry_analysis_service()
        deleted = await service.delete_task(task_id, user["id"])
        if not deleted:
            raise HTTPException(status_code=404, detail="任务不存在")

        return {
            "success": True,
            "data": {"task_id": task_id},
            "message": "行业分析任务删除成功",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("删除行业分析任务失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{task_id}/download")
async def download_industry_analysis_report(
    task_id: str,
    format: str = Query("markdown"),
    user: dict = Depends(get_current_user),
):
    """Download industry analysis report"""
    try:
        service = get_industry_analysis_service()
        task = _ensure_task_access(await service.get_task(task_id), user["id"])
        download_format = format.lower()
        filename_base = f"industry-analysis-{task_id}"

        if download_format == "json":
            payload = json.dumps(task, ensure_ascii=False, indent=2, default=str).encode("utf-8")
            return StreamingResponse(
                _stream_bytes(payload),
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="{filename_base}.json"'},
            )

        try:
            markdown_content = build_industry_markdown_report(task)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if download_format == "markdown":
            return StreamingResponse(
                _stream_bytes(markdown_content.encode("utf-8")),
                media_type="text/markdown",
                headers={"Content-Disposition": f'attachment; filename="{filename_base}.md"'},
            )

        if download_format == "pdf":
            from app.utils.report_exporter import report_exporter

            if not report_exporter.pandoc_available:
                raise HTTPException(status_code=400, detail="PDF 导出功能不可用，请先安装 pandoc")

            try:
                html_content = report_exporter._markdown_to_html(markdown_content)
                pdf_content = report_exporter._generate_pdf_with_pdfkit(html_content)
            except Exception as exc:
                logger.error("生成行业分析 PDF 失败: %s", exc, exc_info=True)
                raise HTTPException(status_code=500, detail=f"PDF 文档生成失败: {str(exc)}")

            return StreamingResponse(
                _stream_bytes(pdf_content),
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{filename_base}.pdf"'},
            )

        raise HTTPException(status_code=400, detail=f"不支持的下载格式: {format}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("下载行业分析报告失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/run")
async def run_industry_analysis_sync(
    request: IndustryAnalysisRequest,
    user: dict = Depends(get_current_user),
):
    """Submit and wait for industry analysis result (synchronous/blocking).

    This endpoint is designed for bot/service integrations (e.g., Feishu)
    that prefer a single request-response cycle.
    Timeout is ~6 minutes (typical analysis takes 2-4 minutes).
    """
    import asyncio

    try:
        service = get_industry_analysis_service()
        task = await service.create_task(user["id"], request)
        task_id = task["task_id"]

        # Execute the analysis directly (not in background)
        await service.execute_task(task_id, user["id"], request)

        # Fetch final result
        final_task = await service.get_task(task_id)
        if not final_task:
            raise HTTPException(status_code=500, detail="任务执行后未找到结果")

        return {
            "success": final_task.get("status") == "completed",
            "data": final_task,
            "message": "行业分析完成" if final_task.get("status") == "completed" else final_task.get("error", "分析失败"),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("同步行业分析执行失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
