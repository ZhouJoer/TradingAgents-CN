"""Markdown export helpers for industry-analysis results."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _load_strip_structured_payload_blocks():
    module_path = Path(__file__).resolve().parents[2] / "tradingagents" / "utils" / "structured_output.py"
    spec = importlib.util.spec_from_file_location("tradingagents_structured_output_for_report", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load structured output helpers from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.strip_structured_payload_blocks


strip_structured_payload_blocks = _load_strip_structured_payload_blocks()


def stringify_report_section(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _table_cell(value: Any) -> str:
    return stringify_report_section(value).replace("|", "\\|").replace("\n", "<br>")


def _join_items(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    return "、".join(stringify_report_section(item) for item in values if stringify_report_section(item))


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


def _build_candidate_trace_markdown(trace: Any) -> str:
    if not isinstance(trace, dict):
        return "该历史报告未记录过程明细。"

    lines = ["### 概念映射"]
    mapping = trace.get("mapping") if isinstance(trace.get("mapping"), dict) else {}
    lines.extend([
        f"- 用户输入: {mapping.get('user_concept', '')}",
        f"- 概念板块: {_join_items(mapping.get('board_concepts')) or '无'}",
        f"- 行业板块: {_join_items(mapping.get('board_industries')) or '无'}",
        f"- 关键词: {_join_items(mapping.get('keywords')) or '无'}",
    ])
    if mapping.get("reasoning"):
        lines.append(f"- 映射理由: {mapping['reasoning']}")

    lines.extend(["", "### 候选抓取", "", "|板块|类型|抓取数|有效数|状态|说明|", "|---|---|---:|---:|---|---|"])
    for item in trace.get("board_fetches") or []:
        if not isinstance(item, dict):
            continue
        status = "失败" if item.get("failed") else "成功"
        lines.append(
            f"|{_table_cell(item.get('board_name'))}|{_table_cell(item.get('board_type'))}|"
            f"{item.get('fetched_count', 0)}|{item.get('valid_count', 0)}|"
            f"{status}|{_table_cell(item.get('reason'))}|"
        )

    lines.extend(["", "### 数据补全", "", "|数据源|尝试数|命中数|字段|说明|", "|---|---:|---:|---|---|"])
    for item in trace.get("enrichment") or []:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"|{_table_cell(item.get('source'))}|{item.get('attempted_count', 0)}|{item.get('hit_count', 0)}|"
            f"{_table_cell(_join_items(item.get('fields')))}|{_table_cell(item.get('note'))}|"
        )

    lines.extend(["", "### 过滤结果", "", f"- 初始候选: {trace.get('original_count', 0)}"])
    lines.append(f"- 进入选股: {trace.get('filtered_count', 0)}")
    lines.append(f"- 剔除数量: {trace.get('excluded_count', 0)}")
    lines.extend(["", "|代码|名称|行业|是否入围|原因|规则评分|来源板块|", "|---|---|---|---|---|---:|---|"])
    for item in trace.get("filter_details") or []:
        if not isinstance(item, dict):
            continue
        included = "是" if item.get("included") else "否"
        lines.append(
            f"|{_table_cell(item.get('code'))}|{_table_cell(item.get('name'))}|{_table_cell(item.get('industry'))}|"
            f"{included}|{_table_cell(item.get('reason_detail') or item.get('reason'))}|"
            f"{item.get('rule_score', 0)}|{_table_cell(_join_items(item.get('source_boards')))}|"
        )
    return "\n".join(lines)


def _build_sections_markdown(title: str, sections: Any, labels: dict[str, str]) -> str:
    if not isinstance(sections, dict):
        return ""
    lines = [f"## {title}"]
    for key, label in labels.items():
        value = stringify_report_section(sections.get(key))
        if value:
            lines.extend(["", f"### {label}", "", value])
    return "\n".join(lines).strip()


def _build_supply_chain_markdown(segments: Any) -> str:
    if not isinstance(segments, list) or not segments:
        return ""
    lines = ["## 产业链视角", "", "|环节|主要业务|受益逻辑|关键指标|风险|相关股票|", "|---|---|---|---|---|---|"]
    for item in segments:
        if not isinstance(item, dict):
            continue
        stocks = []
        for stock in item.get("related_stocks") or []:
            if isinstance(stock, dict):
                stocks.append(f"{stock.get('name') or stock.get('code')}({stock.get('code', '')})")
        lines.append(
            f"|{_table_cell(item.get('segment_name') or item.get('segment_key'))}|{_table_cell(item.get('business'))}|"
            f"{_table_cell(item.get('benefit_logic'))}|{_table_cell(item.get('key_indicators'))}|"
            f"{_table_cell(item.get('risks'))}|{_table_cell('、'.join(stocks))}|"
        )
    return "\n".join(lines)


def _build_recommendation_groups_markdown(groups: Any) -> str:
    if not isinstance(groups, list) or not groups:
        return ""
    lines = ["## 分组推荐"]
    for group in groups:
        if not isinstance(group, dict):
            continue
        lines.extend([
            "",
            f"### {group.get('group_name') or group.get('group_key')}",
            "",
            f"- 分组说明: {group.get('description', '')}",
            f"- 适合风格: {group.get('suitable_style', '')}",
            f"- 主要风险: {group.get('main_risks', '')}",
            "",
            "|代码|名称|评分|推荐逻辑|主要风险|",
            "|---|---|---:|---|---|",
        ])
        for stock in group.get("stocks") or []:
            if not isinstance(stock, dict):
                continue
            lines.append(
                f"|{_table_cell(stock.get('code'))}|{_table_cell(stock.get('name'))}|{stock.get('score', 0)}|"
                f"{_table_cell(stock.get('recommendation_logic') or stock.get('summary'))}|"
                f"{_table_cell(stock.get('main_risks'))}|"
            )
    return "\n".join(lines)


def build_industry_markdown_report(task: dict) -> str:
    result = task.get("result")
    if not isinstance(result, dict):
        raise ValueError("任务结果尚未生成")

    due_diligence_report = strip_structured_payload_blocks(
        stringify_report_section(result.get("due_diligence_report"))
    )
    if not due_diligence_report:
        due_diligence_report = stringify_report_section(result.get("market_overview"))

    stock_selection_report = strip_structured_payload_blocks(
        stringify_report_section(result.get("stock_selection_report"))
    )
    if not stock_selection_report:
        stock_selection_parts = []
        selection_reasoning = stringify_report_section(result.get("selection_reasoning"))
        if selection_reasoning:
            stock_selection_parts.append(selection_reasoning)

        recommendations_markdown = _build_recommendations_markdown(result.get("recommendations"))
        if recommendations_markdown:
            stock_selection_parts.extend(["### 推荐标的", "", recommendations_markdown])

        risk_warning = stringify_report_section(result.get("risk_warning"))
        if risk_warning:
            stock_selection_parts.extend(["", "### 风险提示", "", risk_warning])

        stock_selection_report = "\n".join(part for part in stock_selection_parts if part is not None).strip()

    if not due_diligence_report and not stock_selection_report:
        raise ValueError("任务结果中没有可下载的报告内容")

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
    content_parts.extend(["## 分析过程", "", _build_candidate_trace_markdown(result.get("candidate_trace")), ""])

    industry_logic = _build_sections_markdown(
        "行业逻辑",
        result.get("industry_logic_sections"),
        {
            "supply_chain": "产业链",
            "policy": "政策",
            "cycle": "景气度",
            "demand": "需求驱动",
            "competition": "竞争格局",
            "risks": "风险",
        },
    )
    if industry_logic:
        content_parts.extend([industry_logic, ""])

    supply_chain = _build_supply_chain_markdown(result.get("supply_chain_analysis"))
    if supply_chain:
        content_parts.extend([supply_chain, ""])

    if due_diligence_report:
        content_parts.extend(["## 尽职调查报告", "", due_diligence_report, ""])

    stock_selection_logic = _build_sections_markdown(
        "选股逻辑",
        result.get("stock_selection_sections"),
        {
            "leaders": "龙头",
            "growth_beta": "成长弹性",
            "valuation_repair": "低估修复",
            "high_risk": "高风险高波动",
            "watchlist": "观察名单",
        },
    )
    if stock_selection_logic:
        content_parts.extend([stock_selection_logic, ""])

    recommendation_groups = _build_recommendation_groups_markdown(result.get("recommendation_groups"))
    if recommendation_groups:
        content_parts.extend([recommendation_groups, ""])

    if stock_selection_report:
        content_parts.extend(["## 选股报告", "", stock_selection_report, ""])

    return "\n".join(content_parts).strip() + "\n"
