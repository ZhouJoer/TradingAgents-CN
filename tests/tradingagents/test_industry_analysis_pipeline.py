import importlib.util
import logging
import sys
import types
import unittest
from pathlib import Path

model_path = Path(__file__).resolve().parents[2] / "app" / "models" / "industry_analysis.py"
model_spec = importlib.util.spec_from_file_location("industry_analysis_models_under_test", model_path)
model_module = importlib.util.module_from_spec(model_spec)
assert model_spec is not None and model_spec.loader is not None
sys.modules["industry_analysis_models_under_test"] = model_module
model_spec.loader.exec_module(model_module)

ConceptMappingResult = model_module.ConceptMappingResult
DetailLevel = model_module.DetailLevel
IndustryAnalysisRequest = model_module.IndustryAnalysisRequest
IndustryAnalysisResult = model_module.IndustryAnalysisResult
StockCandidate = model_module.StockCandidate

_created_llms = []


def _fake_create_llm_by_provider(**kwargs):
    _created_llms.append(kwargs)
    return {"model": kwargs["model"], "provider": kwargs["provider"]}


class _FakeConceptMapper:
    mapping_result = ConceptMappingResult(
        user_concept="AI",
        board_concepts=["AI", "算力"],
        board_industries=["软件服务"],
        keywords=["AI"],
        reasoning="test",
    )
    error = None

    def __init__(self, llm):
        self.llm = llm

    async def map_concept(self, user_concept: str):
        if self.error:
            raise self.error
        return self.mapping_result.model_copy(update={"user_concept": user_concept})


class _FakeCandidateFetcher:
    candidates = [
        StockCandidate(code="000001", name="平安银行", price=12.3, source_boards=["AI"]),
        StockCandidate(code="000002", name="万科A", price=9.8, source_boards=["算力"]),
    ]
    error = None

    def __init__(self):
        self.last_fetch_trace = []
        self.last_enrichment_trace = []

    async def fetch_candidates(self, mapping):
        if self.error:
            raise self.error
        self.last_fetch_trace = [
            {
                "board_name": "AI",
                "board_type": "concept",
                "fetched_count": len(self.candidates),
                "valid_count": len(self.candidates),
                "failed": False,
                "reason": "",
            }
        ]
        self.last_enrichment_trace = [
            {
                "source": "test",
                "attempted_count": len(self.candidates),
                "hit_count": len(self.candidates),
                "fields": ["price"],
                "note": "",
            }
        ]
        return list(self.candidates)


class _FakeFilterTraceItem:
    def __init__(self, candidate, included=True, reason="not_excluded"):
        self.code = candidate.code
        self.name = candidate.name
        self.industry = candidate.industry
        self.included = included
        self.reason = reason
        self.reason_detail = "进入选股阶段" if included else "未入围"
        self.rule_score = candidate.match_score
        self.source_boards = candidate.source_boards
        self.key_metrics = {"price": candidate.price}


class _FakeFilterResult:
    def __init__(self, selected, details):
        self.selected = selected
        self.details = details
        self.excluded_counts = {"not_excluded": len(selected)}
        self.score_distribution = {"max": 1.0}


class _FakeCandidateFilter:
    filtered = [StockCandidate(code="000001", name="平安银行", price=12.3, source_boards=["AI"])]
    error = None

    def __init__(self):
        self.max_candidates = 30

    def filter(self, candidates, max_output=30):
        return self.filter_with_trace(candidates, max_output=max_output).selected

    def filter_with_trace(self, candidates, max_output=30):
        if self.error:
            raise self.error
        selected = list(self.filtered)
        selected_codes = {item.code for item in selected}
        details = [
            _FakeFilterTraceItem(item, included=item.code in selected_codes, reason="not_excluded" if item.code in selected_codes else "low_rule_score")
            for item in candidates
        ]
        return _FakeFilterResult(selected, details)


class _FakeStockComparator:
    result = IndustryAnalysisResult(
        concept="placeholder",
        detail_level=DetailLevel.BRIEF,
        recommendations=[],
        market_overview="overview",
        selection_reasoning="reasoning",
        risk_warning="AI分析仅供参考，不构成投资建议",
        llm_calls=2,
        data_date="2025-01-01",
    )
    error = None

    def __init__(self, llm):
        self.llm = llm

    async def generate_due_diligence(self, concept):
        if self.error:
            raise self.error
        return "due diligence"

    async def select_stocks(self, concept, due_diligence_report, candidates, top_n=5):
        if self.error:
            raise self.error
        return types.SimpleNamespace(
            recommendations=self.result.recommendations,
            market_overview=self.result.market_overview,
            selection_reasoning=self.result.selection_reasoning,
            risk_warning=self.result.risk_warning,
            due_diligence_report=due_diligence_report,
            stock_selection_report="stock selection",
            exclusion_reasons=self.result.exclusion_reasons,
            portfolio_advice=self.result.portfolio_advice,
            tracking_indicators=self.result.tracking_indicators,
            conclusion=self.result.conclusion,
            industry_logic_sections=None,
            stock_selection_sections=None,
            supply_chain_analysis=[],
            recommendation_groups=[],
        )


tradingagents_stub = sys.modules.setdefault("tradingagents", types.ModuleType("tradingagents"))
tradingagents_stub.__path__ = []
industry_analysis_stub = sys.modules.setdefault(
    "tradingagents.industry_analysis", types.ModuleType("tradingagents.industry_analysis")
)
industry_analysis_stub.__path__ = []
utils_stub = sys.modules.setdefault("tradingagents.utils", types.ModuleType("tradingagents.utils"))
utils_stub.__path__ = [str(Path(__file__).resolve().parents[2] / "tradingagents" / "utils")]
logging_manager_stub = types.ModuleType("tradingagents.utils.logging_manager")
logging_manager_stub.get_logger = logging.getLogger
sys.modules["tradingagents.utils.logging_manager"] = logging_manager_stub

default_config_stub = types.ModuleType("tradingagents.default_config")
default_config_stub.DEFAULT_CONFIG = {
    "llm_provider": "openai",
    "quick_think_llm": "quick-default",
    "deep_think_llm": "deep-default",
    "backend_url": "https://example.com/v1",
}
sys.modules["tradingagents.default_config"] = default_config_stub

graph_stub = types.ModuleType("tradingagents.graph.trading_graph")
graph_stub.create_llm_by_provider = _fake_create_llm_by_provider
sys.modules["tradingagents.graph.trading_graph"] = graph_stub

concept_mapper_stub = types.ModuleType("tradingagents.industry_analysis.concept_mapper")
concept_mapper_stub.ConceptMapper = _FakeConceptMapper
sys.modules["tradingagents.industry_analysis.concept_mapper"] = concept_mapper_stub

candidate_fetcher_stub = types.ModuleType("tradingagents.industry_analysis.candidate_fetcher")
candidate_fetcher_stub.CandidateFetcher = _FakeCandidateFetcher
sys.modules["tradingagents.industry_analysis.candidate_fetcher"] = candidate_fetcher_stub

candidate_filter_stub = types.ModuleType("tradingagents.industry_analysis.candidate_filter")
candidate_filter_stub.CandidateFilter = _FakeCandidateFilter
candidate_filter_stub.FilterResult = _FakeFilterResult
sys.modules["tradingagents.industry_analysis.candidate_filter"] = candidate_filter_stub

stock_comparator_stub = types.ModuleType("tradingagents.industry_analysis.stock_comparator")
stock_comparator_stub.StockComparator = _FakeStockComparator
sys.modules["tradingagents.industry_analysis.stock_comparator"] = stock_comparator_stub

module_path = Path(__file__).resolve().parents[2] / "tradingagents" / "industry_analysis" / "pipeline.py"
spec = importlib.util.spec_from_file_location("tradingagents.industry_analysis.pipeline_under_test", module_path)
pipeline_module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
sys.modules["tradingagents.industry_analysis.pipeline_under_test"] = pipeline_module
spec.loader.exec_module(pipeline_module)

IndustryAnalysisPipeline = pipeline_module.IndustryAnalysisPipeline


class IndustryAnalysisPipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _created_llms.clear()
        _FakeConceptMapper.error = None
        _FakeCandidateFetcher.error = None
        _FakeCandidateFilter.error = None
        _FakeStockComparator.error = None
        _FakeConceptMapper.mapping_result = ConceptMappingResult(
            user_concept="AI",
            board_concepts=["AI", "算力"],
            board_industries=["软件服务"],
            keywords=["AI"],
            reasoning="test",
        )
        _FakeCandidateFetcher.candidates = [
            StockCandidate(code="000001", name="平安银行", price=12.3, source_boards=["AI"]),
            StockCandidate(code="000002", name="万科A", price=9.8, source_boards=["算力"]),
        ]
        _FakeCandidateFilter.filtered = [
            StockCandidate(code="000001", name="平安银行", price=12.3, source_boards=["AI"])
        ]
        _FakeStockComparator.result = IndustryAnalysisResult(
            concept="placeholder",
            detail_level=DetailLevel.BRIEF,
            recommendations=[],
            market_overview="overview",
            selection_reasoning="reasoning",
            risk_warning="AI分析仅供参考，不构成投资建议",
            llm_calls=2,
            data_date="2025-01-01",
        )

    async def test_run_orchestrates_pipeline_and_fills_metadata(self):
        pipeline = IndustryAnalysisPipeline(
            {
                "llm_provider": "openai",
                "quick_think_llm": "gpt-4o-mini",
                "deep_think_llm": "gpt-4.1",
                "backend_url": "https://api.openai.com/v1",
                "quick_api_key": "quick-key",
                "deep_api_key": "deep-key",
            }
        )
        request = IndustryAnalysisRequest(concept="AI相关", detail_level=DetailLevel.DETAILED, top_n=3)
        progress = []

        result = await pipeline.run(request, progress_callback=lambda percent, message: progress.append((percent, message)))

        self.assertIn(0, [item[0] for item in progress])
        self.assertIn(100, [item[0] for item in progress])
        self.assertEqual([call["model"] for call in _created_llms], ["gpt-4o-mini", "gpt-4.1"])
        self.assertEqual(result.concept, "AI相关")
        self.assertEqual(result.detail_level, DetailLevel.DETAILED)
        self.assertEqual(result.mapped_boards, ["AI", "算力", "软件服务"])
        self.assertEqual(result.candidate_count, 2)
        self.assertEqual(result.filtered_count, 1)
        self.assertEqual(result.llm_calls, 3)
        self.assertTrue(result.data_date)
        self.assertIsNotNone(result.candidate_trace)
        self.assertEqual(result.candidate_trace.mapping.user_concept, "AI相关")
        self.assertEqual(result.candidate_trace.original_count, 2)
        self.assertEqual(result.candidate_trace.filtered_count, 1)
        self.assertGreater(result.analysis_time, 0)

    async def test_run_raises_when_mapping_has_no_boards(self):
        pipeline = IndustryAnalysisPipeline()
        request = IndustryAnalysisRequest(concept="未知概念")
        _FakeConceptMapper.mapping_result = ConceptMappingResult(
            user_concept="未知概念",
            board_concepts=[],
            board_industries=[],
            keywords=["未知概念"],
            reasoning="未命中",
        )

        with self.assertRaisesRegex(ValueError, "未能获取到候选股票"):
            await pipeline.run(request)

    async def test_run_raises_when_fetcher_returns_no_candidates(self):
        pipeline = IndustryAnalysisPipeline()
        request = IndustryAnalysisRequest(concept="AI")
        _FakeCandidateFetcher.candidates = []

        with self.assertRaisesRegex(ValueError, "未能获取到候选股票"):
            await pipeline.run(request)
