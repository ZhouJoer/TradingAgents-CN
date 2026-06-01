import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

model_path = Path(__file__).resolve().parents[2] / "app" / "models" / "industry_analysis.py"
model_spec = importlib.util.spec_from_file_location("industry_analysis_model_for_cli_test", model_path)
model_module = importlib.util.module_from_spec(model_spec)
assert model_spec is not None and model_spec.loader is not None
sys.modules["industry_analysis_model_for_cli_test"] = model_module
model_spec.loader.exec_module(model_module)

DetailLevel = model_module.DetailLevel
IndustryAnalysisRequest = model_module.IndustryAnalysisRequest
IndustryAnalysisResult = model_module.IndustryAnalysisResult
StockRecommendation = model_module.StockRecommendation

app_pkg = types.ModuleType("app")
app_pkg.__path__ = []
models_pkg = types.ModuleType("app.models")
models_pkg.__path__ = []
industry_models_stub = types.ModuleType("app.models.industry_analysis")
industry_models_stub.DetailLevel = DetailLevel
industry_models_stub.IndustryAnalysisRequest = IndustryAnalysisRequest
industry_models_stub.IndustryAnalysisResult = IndustryAnalysisResult
industry_models_stub.StockRecommendation = StockRecommendation
sys.modules["app"] = app_pkg
sys.modules["app.models"] = models_pkg
sys.modules["app.models.industry_analysis"] = industry_models_stub


class _FakePipeline:
    init_configs = []
    last_request = None

    def __init__(self, config=None):
        self.config = config or {}
        type(self).init_configs.append(self.config)

    async def run(self, request, progress_callback=None):
        type(self).last_request = request
        if progress_callback is not None:
            progress_callback(10, "阶段1")
            progress_callback(60, "阶段2")
            progress_callback(100, "完成")
        return IndustryAnalysisResult(
            concept=request.concept,
            detail_level=request.detail_level,
            mapped_boards=["AI", "算力"],
            candidate_count=12,
            filtered_count=6,
            recommendations=[
                StockRecommendation(
                    rank=1,
                    code="000001",
                    name="平安银行",
                    score=92.5,
                    summary="受益于AI基础设施扩容",
                    concept_match="与AI算力需求强相关",
                    industry_position="细分赛道头部",
                    growth_prospect="订单释放预期较强",
                    fundamentals="估值合理，ROE稳定",
                    technicals="趋势向上",
                    financials="现金流稳健",
                    key_metrics={"roe": 12.5, "total_mv": 300.0},
                )
            ],
            market_overview="AI板块短期活跃，但分化明显。",
            selection_reasoning="优先选择兼具景气度和估值安全边际的标的。",
            risk_warning="行业波动较大，注意回撤风险。",
            analysis_time=1.23,
            llm_calls=2,
            data_date="2025-01-01",
        )


tradingagents_pkg = sys.modules.setdefault("tradingagents", types.ModuleType("tradingagents"))
tradingagents_pkg.__path__ = getattr(tradingagents_pkg, "__path__", [])

industry_pkg = types.ModuleType("tradingagents.industry_analysis")
industry_pkg.__path__ = []
sys.modules["tradingagents.industry_analysis"] = industry_pkg

llm_clients_pkg = types.ModuleType("tradingagents.llm_clients")
llm_clients_pkg.__path__ = []
sys.modules["tradingagents.llm_clients"] = llm_clients_pkg

model_catalog_stub = types.ModuleType("tradingagents.llm_clients.model_catalog")
model_catalog_stub.MODEL_OPTIONS = {
    "openai": {
        "quick": [("GPT-4o mini", "gpt-4o-mini")],
        "deep": [("GPT-4.1", "gpt-4.1")],
    },
    "qwen": {
        "quick": [("Qwen Turbo", "qwen-turbo")],
        "deep": [("Qwen Plus", "qwen-plus")],
    },
}
sys.modules["tradingagents.llm_clients.model_catalog"] = model_catalog_stub

provider_keys_stub = types.ModuleType("tradingagents.llm_clients.provider_keys")
provider_keys_stub.default_backend_url = lambda provider: f"https://{provider}.example.com/v1"
provider_keys_stub.env_key_for_provider = lambda provider: {"openai": "OPENAI_API_KEY", "qwen": "QWEN_API_KEY"}.get(provider, "")
provider_keys_stub.normalize_provider_key = lambda provider: provider
sys.modules["tradingagents.llm_clients.provider_keys"] = provider_keys_stub

default_config_stub = types.ModuleType("tradingagents.default_config")
default_config_stub.DEFAULT_CONFIG = {
    "llm_provider": "openai",
    "quick_think_llm": "gpt-4o-mini",
    "deep_think_llm": "gpt-4.1",
    "backend_url": "https://openai.example.com/v1",
}
sys.modules["tradingagents.default_config"] = default_config_stub

pipeline_stub = types.ModuleType("tradingagents.industry_analysis.pipeline")
pipeline_stub.IndustryAnalysisPipeline = _FakePipeline
sys.modules["tradingagents.industry_analysis.pipeline"] = pipeline_stub

module_path = Path(__file__).resolve().parents[2] / "cli" / "industry_analysis.py"
spec = importlib.util.spec_from_file_location("industry_cli_under_test", module_path)
cli_module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
sys.modules["industry_cli_under_test"] = cli_module
spec.loader.exec_module(cli_module)

runner = CliRunner()


class IndustryAnalysisCliTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakePipeline.init_configs.clear()
        _FakePipeline.last_request = None

    def test_analyze_renders_result_and_applies_provider_override(self):
        with patch.dict(os.environ, {"QWEN_API_KEY": "test-key"}, clear=False):
            result = runner.invoke(
                cli_module.app,
                ["AI相关", "--detail", "--top", "3", "--provider", "qwen"],
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(_FakePipeline.last_request.concept, "AI相关")
        self.assertEqual(_FakePipeline.last_request.detail_level, DetailLevel.DETAILED)
        self.assertEqual(_FakePipeline.last_request.top_n, 3)
        self.assertEqual(_FakePipeline.init_configs[-1]["llm_provider"], "qwen")
        self.assertIn("AI相关", result.output)
        self.assertIn("000001", result.output)
        self.assertIn("平安银行", result.output)
        self.assertIn("市场概览", result.output)
        self.assertIn("风险提示", result.output)

    def test_analyze_rejects_invalid_top_value(self):
        result = runner.invoke(cli_module.app, ["AI相关", "--top", "0"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("推荐股票数量必须在 1-20 之间", result.output)


if __name__ == "__main__":
    unittest.main()
