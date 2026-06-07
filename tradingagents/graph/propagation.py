# TradingAgents/graph/propagation.py

from typing import Dict, Any, Optional

from tradingagents.agents.utils.agent_states import (
    InvestDebateState,
    RiskDebateState,
)


class Propagator:
    """Handles state initialization and propagation through the graph."""

    def __init__(self, max_recur_limit=100):
        """Initialize with configuration parameters."""
        self.max_recur_limit = max_recur_limit

    def create_initial_state(
        self, company_name: str, trade_date: str, review_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create the initial state for the agent graph."""
        from langchain_core.messages import HumanMessage

        analysis_request = f"请对股票 {company_name} 进行全面分析，交易日期为 {trade_date}。"
        if review_context:
            analysis_request += (
                "\n\n本次启用了历史报告复盘。请在关键决策节点结合 "
                "state.history_review_report，识别观点变化、已验证假设和仍需验证的问题；"
                "不要把历史结论直接当作本次投资建议。请在交易计划和最终决策中单列"
                "“历史报告复盘”小节，说明历史判断哪些被当前信息支持、削弱或推翻。"
            )

        return {
            "messages": [HumanMessage(content=analysis_request)],
            "company_of_interest": company_name,
            "trade_date": str(trade_date),
            "investment_debate_state": InvestDebateState(
                {"history": "", "current_response": "", "count": 0}
            ),
            "risk_debate_state": RiskDebateState(
                {
                    "history": "",
                    "current_risky_response": "",
                    "current_safe_response": "",
                    "current_neutral_response": "",
                    "latest_speaker": "",
                    "stage": "independent_initial_review",
                    "count": 0,
                }
            ),
            "market_report": "",
            "fundamentals_report": "",
            "sentiment_report": "",
            "news_report": "",
            "history_review_report": review_context or "",
        }

    def get_graph_args(self, use_progress_callback: bool = False) -> Dict[str, Any]:
        """Get arguments for the graph invocation.

        Args:
            use_progress_callback: If True, use 'updates' mode for node-level progress tracking.
                                  If False, use 'values' mode for complete state updates.
        """
        stream_mode = "updates" if use_progress_callback else "values"

        return {
            "stream_mode": stream_mode,
            "config": {"recursion_limit": self.max_recur_limit},
        }
