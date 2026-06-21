"""Guards for model output that is not a user-facing report."""

from typing import Any


INVALID_REPORT_PLACEHOLDER = (
    "该报告模块保存的是模型工具调用协议片段，而不是有效的分析报告。"
    "请重新运行本次分析；系统已拦截此类协议片段，避免后续报告继续保存原始工具调用文本。"
)


def is_tool_call_artifact(content: Any) -> bool:
    """Return True when model text looks like a serialized tool-call block."""
    if not isinstance(content, str):
        return False

    text = content.strip()
    if not text:
        return False

    lower = text.lower()

    if "dsml" in lower and ("tool_calls" in lower or "invoke name=" in lower):
        return True

    if "tool_calls" in lower and (
        "invoke name=" in lower
        or "parameter name=" in lower
        or "<tool_call" in lower
        or "</tool_call" in lower
    ):
        return True

    marker_hits = sum(
        marker in lower
        for marker in (
            "<|dsml|",
            "invoke name=",
            "parameter name=",
            "<tool_call",
            "</tool_call",
            '"tool_calls"',
            "'tool_calls'",
        )
    )
    return marker_hits >= 2


def is_valid_report_text(content: Any, min_length: int = 100) -> bool:
    """A lightweight validity check for completed report text."""
    if not isinstance(content, str):
        return False
    text = content.strip()
    return len(text) > min_length and not is_tool_call_artifact(text)


def sanitize_report_content(content: Any) -> Any:
    """Replace raw tool-call artifacts with a user-facing placeholder."""
    if is_tool_call_artifact(content):
        return INVALID_REPORT_PLACEHOLDER
    return content


def sanitize_report_modules(reports: Any) -> Any:
    """Sanitize a report modules dict while preserving non-string values."""
    if not isinstance(reports, dict):
        return reports

    return {
        module_name: sanitize_report_content(module_content)
        for module_name, module_content in reports.items()
    }
