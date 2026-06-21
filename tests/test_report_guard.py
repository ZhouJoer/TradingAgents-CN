from types import SimpleNamespace

from tradingagents.utils.report_guard import (
    INVALID_REPORT_PLACEHOLDER,
    is_tool_call_artifact,
    sanitize_report_modules,
)
from tradingagents.graph.conditional_logic import ConditionalLogic


DSML_ARTIFACT = """
<|DSML| tool_calls>
<|DSML| invoke name="get_state_history_review">
<|DSML| parameter name="ticker" string="true">002352</|DSML| parameter>
</|DSML| invoke>
</|DSML| tool_calls>
"""


def test_detects_dsml_tool_call_artifact():
    assert is_tool_call_artifact(DSML_ARTIFACT)
    assert is_tool_call_artifact(
        '< | | DSML | | tool_calls>< | | DSML | | invoke name="x">'
    )


def test_sanitize_report_modules_replaces_artifact_only():
    reports = {
        "market_report": DSML_ARTIFACT,
        "news_report": "这是一段正常的新闻分析报告。" * 10,
    }

    sanitized = sanitize_report_modules(reports)

    assert sanitized["market_report"] == INVALID_REPORT_PLACEHOLDER
    assert sanitized["news_report"] == reports["news_report"]


def test_market_condition_does_not_treat_artifact_as_completed_report():
    logic = ConditionalLogic()
    state = {
        "messages": [
            SimpleNamespace(
                tool_calls=[{"name": "get_stock_market_data_unified", "args": {}}]
            )
        ],
        "market_report": DSML_ARTIFACT,
    }

    assert logic.should_continue_market(state) == "tools_market"


def test_market_condition_still_clears_valid_completed_report():
    logic = ConditionalLogic()
    state = {
        "messages": [
            SimpleNamespace(
                tool_calls=[{"name": "get_stock_market_data_unified", "args": {}}]
            )
        ],
        "market_report": "这是一份完整的市场技术分析报告，包含价格趋势、技术指标、风险提示和投资建议。"
        * 8,
    }

    assert logic.should_continue_market(state) == "Msg Clear Market"
