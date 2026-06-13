import unittest
import asyncio
import importlib.util
import sys
import types
from pathlib import Path

model_path = Path(__file__).resolve().parents[2] / "app" / "models" / "industry_analysis.py"
model_spec = importlib.util.spec_from_file_location("industry_analysis_model_for_structured_test", model_path)
model_module = importlib.util.module_from_spec(model_spec)
assert model_spec is not None and model_spec.loader is not None
sys.modules["industry_analysis_model_for_structured_test"] = model_module
model_spec.loader.exec_module(model_module)

StockCandidate = model_module.StockCandidate
app_pkg = types.ModuleType("app")
app_pkg.__path__ = []
models_pkg = types.ModuleType("app.models")
models_pkg.__path__ = []
industry_models_stub = types.ModuleType("app.models.industry_analysis")
for name in (
    "DetailLevel",
    "DiscoveryInsightItem",
    "IndustryDiscoveryInsights",
    "IndustryLogicSections",
    "IndustryAnalysisResult",
    "RecommendationGroup",
    "StockCandidate",
    "StockRecommendation",
    "StockSelectionSections",
    "SupplyChainSegment",
):
    setattr(industry_models_stub, name, getattr(model_module, name))
sys.modules["app"] = app_pkg
sys.modules["app.models"] = models_pkg
sys.modules["app.models.industry_analysis"] = industry_models_stub

module_path = Path(__file__).resolve().parents[2] / "tradingagents" / "industry_analysis" / "stock_comparator.py"
tradingagents_pkg = sys.modules.setdefault("tradingagents", types.ModuleType("tradingagents"))
tradingagents_pkg.__path__ = [str(Path(__file__).resolve().parents[2] / "tradingagents")]
industry_pkg = sys.modules.setdefault("tradingagents.industry_analysis", types.ModuleType("tradingagents.industry_analysis"))
industry_pkg.__path__ = [str(module_path.parent)]
utils_pkg = types.ModuleType("tradingagents.utils")
utils_pkg.__path__ = [str(Path(__file__).resolve().parents[2] / "tradingagents" / "utils")]
logging_stub = types.ModuleType("tradingagents.utils.logging_manager")
logging_stub.get_logger = lambda name: types.SimpleNamespace(
    info=lambda *args, **kwargs: None,
    debug=lambda *args, **kwargs: None,
    warning=lambda *args, **kwargs: None,
    error=lambda *args, **kwargs: None,
)
sys.modules["tradingagents.utils"] = utils_pkg
sys.modules["tradingagents.utils.logging_manager"] = logging_stub
spec = importlib.util.spec_from_file_location("tradingagents.industry_analysis.stock_comparator_structured_under_test", module_path)
stock_comparator_module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
sys.modules[spec.name] = stock_comparator_module
spec.loader.exec_module(stock_comparator_module)
StockComparator = stock_comparator_module.StockComparator


class _FakeLLM:
    def __init__(self, response):
        self.response = response

    def invoke(self, prompt):
        return self.response


class StockComparatorStructuredTests(unittest.TestCase):
    def test_parse_structured_json_payload_populates_enhanced_sections(self):
        comparator = StockComparator(llm=object())
        candidates = [
            StockCandidate(
                code="000001",
                name="平安银行",
                industry="银行",
                price=10.0,
                total_mv=1000.0,
                source_boards=["高股息"],
            )
        ]
        response = """
# 一、Top 5结论摘要
测试内容

```json
{
  "industry_logic_sections": {
    "supply_chain": "现金流来源",
    "policy": "政策稳定",
    "cycle": "景气平稳",
    "demand": "配置需求",
    "competition": "集中度较高",
    "risks": "利率风险"
  },
  "stock_selection_sections": {
    "leaders": "稳健龙头",
    "growth_beta": "弹性较低",
    "valuation_repair": "估值修复",
    "high_risk": "高波动较少",
    "watchlist": "继续观察"
  },
  "supply_chain_analysis": [
    {
      "segment_key": "cashflow_sources",
      "segment_name": "现金流来源",
      "business": "银行分红",
      "benefit_logic": "利润稳定",
      "key_indicators": "股息率",
      "risks": "息差下行",
      "related_stocks": [{"code": "000001", "name": "平安银行", "summary": "高股息银行"}]
    }
  ],
  "recommendation_groups": [
    {
      "group_key": "stable_leaders",
      "group_name": "稳健龙头",
      "description": "低波动",
      "suitable_style": "稳健",
      "main_risks": "利率风险",
      "stocks": [{"code": "000001", "name": "平安银行", "score": 88, "recommendation_logic": "分红稳定"}]
    }
  ],
  "discovery_insights": {
    "industry_bottlenecks": [
      {"title": "息差瓶颈", "summary": "息差下行压制利润", "evidence": "行业净息差承压", "tracking_signal": "净息差", "expected_timing": "季度财报", "severity": "high", "related_stocks": [{"code": "000001", "name": "平安银行"}]}
    ],
    "non_consensus_targets": [],
    "financial_inflections": [],
    "red_team_counterpoints": [],
    "future_catalysts": []
  },
  "recommendations": [
    {"rank": 1, "code": "000001", "name": "平安银行", "industry": "银行", "score": 88, "summary": "分红稳定"}
  ]
}
```
"""

        result = comparator._parse_stock_selection(response, candidates, top_n=5)

        self.assertIsNotNone(result.industry_logic_sections)
        self.assertEqual(result.industry_logic_sections.supply_chain, "现金流来源")
        self.assertIsNotNone(result.stock_selection_sections)
        self.assertEqual(result.stock_selection_sections.leaders, "稳健龙头")
        self.assertEqual(len(result.supply_chain_analysis), 1)
        self.assertEqual(result.supply_chain_analysis[0].related_stocks[0].code, "000001")
        self.assertEqual(len(result.recommendation_groups), 1)
        self.assertEqual(result.recommendation_groups[0].stocks[0].name, "平安银行")
        self.assertEqual(result.discovery_insights.industry_bottlenecks[0].title, "息差瓶颈")
        self.assertEqual(result.discovery_insights.industry_bottlenecks[0].related_stocks[0].code, "000001")
        self.assertEqual(result.recommendations[0].score, 88)

    def test_select_stocks_removes_structured_json_from_user_report(self):
        response = """
# Top 5
report body

```json
{
  "industry_logic_sections": {"supply_chain": "chain"},
  "stock_selection_sections": {"leaders": "leader"},
  "discovery_insights": {"future_catalysts": [{"title": "订单催化", "summary": "订单落地"}]},
  "recommendations": [
    {"rank": 1, "code": "000001", "name": "Ping An", "score": 88, "summary": "stable"}
  ]
}
```
"""
        comparator = StockComparator(llm=_FakeLLM(response))
        candidates = [StockCandidate(code="000001", name="Ping An", price=10.0, source_boards=["AI"])]

        result = asyncio.run(comparator.select_stocks("AI", "# DD", candidates, top_n=5))

        self.assertIn("report body", result.stock_selection_report)
        self.assertNotIn("industry_logic_sections", result.stock_selection_report)
        self.assertNotIn("```json", result.stock_selection_report)
        self.assertEqual(result.recommendations[0].code, "000001")


if __name__ == "__main__":
    unittest.main()
