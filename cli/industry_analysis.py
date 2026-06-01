"""行业/概念分析 CLI 命令。"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

import typer
from dotenv import load_dotenv
from rich.console import Console, Group
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

load_dotenv()

from app.models.industry_analysis import DetailLevel, IndustryAnalysisRequest, IndustryAnalysisResult, StockRecommendation
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.industry_analysis.pipeline import IndustryAnalysisPipeline
from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS
from tradingagents.llm_clients.provider_keys import default_backend_url, env_key_for_provider, normalize_provider_key

console = Console()
app = typer.Typer(help="行业/概念分析")


@app.command()
def analyze(
    concept: str = typer.Argument(..., help="行业或概念关键词，如'AI相关'、'高股息'"),
    detail: bool = typer.Option(False, "--detail", "-d", help="输出详细分析报告"),
    top: int = typer.Option(5, "--top", "-n", help="推荐股票数量"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="LLM供应商(覆盖默认配置)"),
):
    """分析指定行业/概念，挑选最优股票。"""
    if not 1 <= top <= 20:
        raise typer.BadParameter("推荐股票数量必须在 1-20 之间", param_hint="--top")

    try:
        config = _build_config(provider)
        _validate_provider_credentials(config["llm_provider"])
    except ValueError as exc:
        console.print(Panel(str(exc), title="配置错误", border_style="red"))
        raise typer.Exit(code=1)

    request = IndustryAnalysisRequest(
        concept=concept,
        detail_level=DetailLevel.DETAILED if detail else DetailLevel.BRIEF,
        top_n=top,
    )

    console.print(
        Panel.fit(
            f"[bold cyan]{concept}[/bold cyan]\n"
            f"模式: {'详细分析' if detail else '简版分析'}\n"
            f"Top N: {top} | Provider: {config['llm_provider']} | Model: {config['deep_think_llm']}",
            title="行业/概念分析",
            border_style="cyan",
        )
    )

    try:
        result = _run_pipeline(request, config)
    except KeyboardInterrupt:
        console.print(Panel("分析已取消", border_style="yellow"))
        raise typer.Exit(code=130)
    except Exception as exc:
        console.print(Panel(str(exc), title="分析失败", border_style="red"))
        raise typer.Exit(code=1)

    _render_summary(result, config)
    if detail:
        _render_detailed_recommendations(result.recommendations)
    _render_footer(result)


def _run_pipeline(request: IndustryAnalysisRequest, config: dict[str, Any]) -> IndustryAnalysisResult:
    pipeline = IndustryAnalysisPipeline(config=config)
    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task("正在初始化分析流程…", total=100)

        def on_progress(percent: int, message: str) -> None:
            progress.update(task_id, description=message, completed=percent)

        result = asyncio.run(pipeline.run(request, progress_callback=on_progress))
        progress.update(task_id, description="分析完成", completed=100)
        return result


def _build_config(provider_override: Optional[str]) -> dict[str, Any]:
    """
    构建 pipeline 配置。优先从数据库读取已启用的模型配置，
    回退到环境变量和 DEFAULT_CONFIG。
    """
    config = DEFAULT_CONFIG.copy()

    # 尝试从数据库读取模型配置（与后端 API 一致的逻辑）
    try:
        from app.services.model_capability_service import get_model_capability_service
        from app.services.simple_analysis_service import get_provider_and_url_by_model_sync

        capability_service = get_model_capability_service()
        quick_model, deep_model = capability_service.recommend_models_for_depth("标准")

        quick_info = get_provider_and_url_by_model_sync(quick_model)
        deep_info = get_provider_and_url_by_model_sync(deep_model)

        config["llm_provider"] = quick_info["provider"]
        config["quick_think_llm"] = quick_model
        config["deep_think_llm"] = deep_model
        config["backend_url"] = quick_info["backend_url"]
        config["quick_provider"] = quick_info["provider"]
        config["deep_provider"] = deep_info["provider"]
        config["quick_backend_url"] = quick_info["backend_url"]
        config["deep_backend_url"] = deep_info["backend_url"]
        config["quick_api_key"] = quick_info["api_key"]
        config["deep_api_key"] = deep_info["api_key"]

        # 如果用户指定了 provider override，覆盖
        if provider_override:
            selected_provider = normalize_provider_key(provider_override)
            if selected_provider and selected_provider not in MODEL_OPTIONS:
                supported = "、".join(sorted(MODEL_OPTIONS.keys()))
                raise ValueError(f"不支持的 LLM 供应商: {provider_override}。可选值: {supported}")
            if selected_provider:
                config["llm_provider"] = selected_provider
                config["quick_provider"] = selected_provider
                config["deep_provider"] = selected_provider
                config["quick_think_llm"] = _default_model_for_provider(selected_provider, mode="quick")
                config["deep_think_llm"] = _default_model_for_provider(selected_provider, mode="deep")
                backend_url = default_backend_url(selected_provider)
                config["backend_url"] = backend_url
                config["quick_backend_url"] = backend_url
                config["deep_backend_url"] = backend_url

        return config

    except Exception as e:
        # 数据库不可用时回退到环境变量 + DEFAULT_CONFIG
        console.print(f"[dim]⚠️ 无法从数据库读取模型配置，使用环境变量: {e}[/dim]")

    env_results_dir = os.getenv("TRADINGAGENTS_RESULTS_DIR")
    env_provider = os.getenv("TRADINGAGENTS_LLM_PROVIDER") or os.getenv("LLM_PROVIDER")
    env_backend_url = os.getenv("TRADINGAGENTS_BACKEND_URL") or os.getenv("BACKEND_URL")
    env_quick_model = os.getenv("TRADINGAGENTS_QUICK_MODEL") or os.getenv("SHALLOW_THINKING_MODEL")
    env_deep_model = os.getenv("TRADINGAGENTS_DEEP_MODEL") or os.getenv("DEEP_THINKING_MODEL")
    if env_results_dir:
        config["results_dir"] = env_results_dir
    if env_quick_model:
        config["quick_think_llm"] = env_quick_model
    if env_deep_model:
        config["deep_think_llm"] = env_deep_model

    selected_provider = normalize_provider_key(provider_override or env_provider or config.get("llm_provider", "openai")) or "openai"
    if selected_provider not in MODEL_OPTIONS:
        supported = "、".join(sorted(MODEL_OPTIONS.keys()))
        raise ValueError(f"不支持的 LLM 供应商: {provider_override}。可选值: {supported}")

    config["llm_provider"] = selected_provider
    config["quick_provider"] = selected_provider
    config["deep_provider"] = selected_provider
    if provider_override:
        if not env_quick_model:
            config["quick_think_llm"] = _default_model_for_provider(selected_provider, mode="quick")
        if not env_deep_model:
            config["deep_think_llm"] = _default_model_for_provider(selected_provider, mode="deep")

    if selected_provider == "custom_openai":
        backend_url = os.getenv("CUSTOM_OPENAI_BASE_URL", env_backend_url or config.get("backend_url") or "https://api.openai.com/v1")
    else:
        backend_url = env_backend_url or default_backend_url(selected_provider)

    config["backend_url"] = backend_url
    config["quick_backend_url"] = backend_url
    config["deep_backend_url"] = backend_url
    return config


def _default_model_for_provider(provider: str, mode: str) -> str:
    options = MODEL_OPTIONS.get(provider, {}).get(mode, [])
    for _, value in options:
        if value != "custom":
            return value
    raise ValueError(f"供应商 {provider} 缺少可用的 {mode} 模型配置")


def _validate_provider_credentials(provider: str) -> None:
    """验证凭证（如果 config 中已有 api_key 则跳过环境变量检查）"""
    if provider == "ollama":
        return
    # 如果是从数据库获取的配置，api_key 已经在 config 中，不需要检查环境变量
    # 这里只做最基本的检查
    if provider == "custom_openai":
        if os.getenv("CUSTOM_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY"):
            return
        # 不抛异常，因为 api_key 可能已通过数据库配置
        return

    # 不再强制检查环境变量，因为 API Key 可能来自数据库
    return


def _render_summary(result: IndustryAnalysisResult, config: dict[str, Any]) -> None:
    meta = Table.grid(expand=True)
    meta.add_column(style="cyan", justify="right", ratio=1)
    meta.add_column(style="white", ratio=3)
    meta.add_row("映射板块", "、".join(result.mapped_boards) if result.mapped_boards else "未命中明确板块")
    meta.add_row("候选数量", f"初筛 {result.candidate_count} 只 / 入围 {result.filtered_count} 只")
    meta.add_row("分析耗时", f"{result.analysis_time:.2f} 秒")
    meta.add_row("LLM 调用", str(result.llm_calls))
    meta.add_row("数据日期", result.data_date or "未知")
    meta.add_row("模型配置", f"{config['llm_provider']} / {config['deep_think_llm']}")
    console.print(Panel(meta, title="分析摘要", border_style="blue"))

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Rank", style="cyan", justify="right", width=6)
    table.add_column("Code", style="green", width=10)
    table.add_column("Name", style="white", width=14)
    table.add_column("Score", style="yellow", justify="right", width=8)
    table.add_column("Summary", style="white", overflow="fold")

    if result.recommendations:
        for stock in result.recommendations:
            table.add_row(
                str(stock.rank),
                stock.code,
                stock.name or "-",
                f"{stock.score:.1f}",
                stock.summary or "-",
            )
        console.print(table)
    else:
        console.print(Panel("未生成推荐股票，请尝试更换概念关键词或 LLM 供应商。", title="暂无结果", border_style="yellow"))


def _render_detailed_recommendations(recommendations: list[StockRecommendation]) -> None:
    for stock in recommendations:
        sections = Table.grid(expand=True)
        sections.add_column(style="cyan", width=12)
        sections.add_column(style="white")
        sections.add_row("推荐摘要", stock.summary or "-")
        sections.add_row("概念匹配", stock.concept_match or "-")
        sections.add_row("行业地位", stock.industry_position or "-")
        sections.add_row("成长前景", stock.growth_prospect or "-")
        sections.add_row("基本面", stock.fundamentals or "-")
        sections.add_row("技术面", stock.technicals or "-")
        sections.add_row("财务状况", stock.financials or "-")

        group_items: list[Any] = [sections]
        metrics_table = _build_metrics_table(stock.key_metrics)
        if metrics_table is not None:
            group_items.append(metrics_table)

        console.print(
            Panel(
                Group(*group_items),
                title=f"#{stock.rank} {stock.code} {stock.name} | 评分 {stock.score:.1f}",
                border_style="green",
            )
        )


def _build_metrics_table(metrics: dict[str, Any]) -> Optional[Table]:
    if not metrics:
        return None

    labels = {
        "industry": "所属行业",
        "pe": "PE",
        "pb": "PB",
        "roe": "ROE",
        "total_mv": "总市值",
        "circ_mv": "流通市值",
        "revenue_growth": "营收增速",
        "net_profit_growth": "净利增速",
        "debt_ratio": "负债率",
        "price": "最新价",
        "pct_chg": "当日涨跌",
        "pct_chg_5d": "5日涨跌",
        "pct_chg_20d": "20日涨跌",
        "turnover_rate": "换手率",
        "volume_ratio": "量比",
        "source_boards": "来源板块",
        "match_score": "预筛分数",
    }

    table = Table(show_header=True, header_style="bold blue")
    table.add_column("指标", style="cyan", width=12)
    table.add_column("数值", style="white")
    for key, value in metrics.items():
        label = labels.get(key, key)
        table.add_row(label, _format_metric_value(key, value))
    return table


def _format_metric_value(key: str, value: Any) -> str:
    if isinstance(value, list):
        return "、".join(str(item) for item in value)
    if isinstance(value, float):
        if key in {"roe", "revenue_growth", "net_profit_growth", "debt_ratio", "pct_chg", "pct_chg_5d", "pct_chg_20d", "turnover_rate"}:
            return f"{value:.2f}%"
        if key in {"total_mv", "circ_mv"}:
            return f"{value:.2f} 亿"
        return f"{value:.2f}"
    return str(value)


def _render_footer(result: IndustryAnalysisResult) -> None:
    if result.market_overview:
        console.print(Panel(result.market_overview, title="市场概览", border_style="cyan"))
    if result.selection_reasoning:
        console.print(Panel(result.selection_reasoning, title="选股逻辑", border_style="blue"))
    risk_text = Text(result.risk_warning or "AI分析仅供参考，不构成投资建议，请结合自身风险承受能力独立判断。")
    risk_text.stylize("bold yellow")
    console.print(Panel(risk_text, title="风险提示", border_style="yellow"))
