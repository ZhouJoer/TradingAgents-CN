import importlib.util
import logging
import sys
import types
from pathlib import Path
from unittest import TestCase

tradingagents_stub = sys.modules.setdefault("tradingagents", types.ModuleType("tradingagents"))
tradingagents_stub.__path__ = []
sys.modules.setdefault("tradingagents.utils", types.ModuleType("tradingagents.utils"))
logging_manager_stub = types.ModuleType("tradingagents.utils.logging_manager")
logging_manager_stub.get_logger = logging.getLogger
sys.modules["tradingagents.utils.logging_manager"] = logging_manager_stub

module_path = Path(__file__).resolve().parents[2] / "tradingagents" / "industry_analysis" / "candidate_filter.py"
spec = importlib.util.spec_from_file_location("candidate_filter_under_test", module_path)
candidate_filter_module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(candidate_filter_module)

CandidateFilter = candidate_filter_module.CandidateFilter
StockCandidate = candidate_filter_module.StockCandidate


class CandidateFilterTests(TestCase):
    def setUp(self) -> None:
        self.filter = CandidateFilter(max_candidates=5)

    def test_hard_exclusion_rules(self) -> None:
        candidates = [
            StockCandidate(code="000001", name="*ST测试", price=10.0, total_mv=100.0),
            StockCandidate(code="000002", name="测试退市", price=10.0, total_mv=100.0),
            StockCandidate(code="000003", name="正常A", price=None, total_mv=100.0),
            StockCandidate(code="000004", name="正常B", price=12.0, total_mv=20.0),
            StockCandidate(code="000005", name="正常C", price=15.0, total_mv=120.0, pe=20.0, roe=18.0),
        ]

        result = self.filter.filter(candidates)

        self.assertEqual([candidate.code for candidate in result], ["000005"])

    def test_missing_optional_metrics_are_treated_neutrally(self) -> None:
        candidates = [
            StockCandidate(code="000010", name="缺失指标", price=10.0, total_mv=None),
            StockCandidate(code="000011", name="完整指标", price=10.0, total_mv=200.0, pe=15.0, pb=2.0, roe=20.0),
        ]

        result = self.filter.filter(candidates, max_output=5)

        self.assertEqual(len(result), 2)
        self.assertTrue(all(candidate.match_score > 0 for candidate in result))

    def test_composite_score_sorts_candidates_and_updates_match_score(self) -> None:
        candidates = [
            StockCandidate(
                code="000100",
                name="高质量龙头",
                price=25.0,
                total_mv=600.0,
                pe=18.0,
                pb=3.2,
                roe=22.0,
                pct_chg_20d=12.0,
                turnover_rate=4.5,
                source_boards=["AI", "算力", "芯片"],
                match_score=3.0,
            ),
            StockCandidate(
                code="000101",
                name="一般候选",
                price=18.0,
                total_mv=80.0,
                pe=70.0,
                pb=9.5,
                roe=8.0,
                pct_chg_20d=2.0,
                turnover_rate=12.0,
                source_boards=["AI"],
                match_score=1.0,
            ),
            StockCandidate(
                code="000102",
                name="缺少部分数据",
                price=9.0,
                total_mv=150.0,
                pe=None,
                pb=None,
                roe=None,
                pct_chg_20d=None,
                turnover_rate=None,
                source_boards=["AI", "算力"],
                match_score=2.0,
            ),
        ]

        result = self.filter.filter(candidates, max_output=3)

        self.assertEqual(result[0].code, "000100")
        self.assertEqual(len(result), 3)
        self.assertGreaterEqual(result[0].match_score, result[1].match_score)
        self.assertGreaterEqual(result[1].match_score, result[2].match_score)
        self.assertTrue(all(candidate.match_score > 0 for candidate in result))
