import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from starlette.responses import StreamingResponse

from app.models.industry_analysis import IndustryAnalysisRequest
from app.routers.auth_db import get_current_user
from app.services.industry_analysis_service import get_industry_analysis_service

router = APIRouter(tags=["industry-analysis"])
logger = logging.getLogger("webapi")


def _ensure_task_access(task: Optional[dict], user_id: str) -> dict:
    if not task or task.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


def _stringify_report_section(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _build_recommendations_markdown(recommendations: Any) -> str:
    if not isinstance(recommendations, list):
        return ""

    lines = []
    for item in recommendations:
        if not isinstance(item, dict):
            continue

        rank = item.get("rank")
        name = item.get("name") or item.get("code") or "未知标的"
        code = item.get("code") or ""
        score = item.get("score")
        summary = item.get("summary") or ""

        title = f"{rank}. {name}" if rank is not None else name
        if code:
            title = f"{title} ({code})"
        if score is not None:
            title = f"{title} - 评分: {score}"

        lines.append(f"- {title}")
        if summary:
            lines.append(f"  - 推荐理由: {summary}")

    return "\n".join(lines)


def _build_markdown_report(task: dict) -> str:
    result = task.get("result")
    if not isinstance(result, dict):
        raise HTTPException(status_code=400, detail="任务结果尚未生成")

    due_diligence_report = _stringify_report_section(result.get("due_diligence_report"))
    if not due_diligence_report:
        due_diligence_report = _stringify_report_section(result.get("market_overview"))

    stock_selection_report = _stringify_report_section(result.get("stock_selection_report"))
    if not stock_selection_report:
        stock_selection_parts = []
        selection_reasoning = _stringify_report_section(result.get("selection_reasoning"))
        if selection_reasoning:
            stock_selection_parts.append(selection_reasoning)

        recommendations_markdown = _build_recommendations_markdown(result.get("recommendations"))
        if recommendations_markdown:
            stock_selection_parts.extend(["### 推荐标的", "", recommendations_markdown])

        risk_warning = _stringify_report_section(result.get("risk_warning"))
        if risk_warning:
            stock_selection_parts.extend(["", "### 风险提示", "", risk_warning])

        stock_selection_report = "\n".join(part for part in stock_selection_parts if part is not None).strip()

    if not due_diligence_report and not stock_selection_report:
        raise HTTPException(status_code=400, detail="任务结果中没有可下载的报告内容")

    content_parts = [
        f"# 行业分析报告：{task.get('concept') or task.get('task_id')}",
        "",
        f"- 任务ID: {task.get('task_id', '')}",
        f"- 分析主题: {task.get('concept', '')}",
        f"- 任务状态: {task.get('status', '')}",
        f"- 分析粒度: {task.get('detail_level', '')}",
    ]

    if task.get("completed_at"):
        content_parts.append(f"- 完成时间: {task['completed_at']}")

    content_parts.extend(["", "---", ""])

    if due_diligence_report:
        content_parts.extend(["## 尽职调查报告", "", due_diligence_report, ""])

    if stock_selection_report:
        content_parts.extend(["## 选股报告", "", stock_selection_report, ""])

    return "\n".join(content_parts).strip() + "\n"


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

        markdown_content = _build_markdown_report(task)

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
