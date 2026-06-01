import importlib.util
import logging
import sys
import types
import unittest
from pathlib import Path

import pandas as pd

from app.models.industry_analysis import ConceptMappingResult

tradingagents_stub = sys.modules.setdefault("tradingagents", types.ModuleType("tradingagents"))
tradingagents_stub.__path__ = []
sys.modules.setdefault("tradingagents.utils", types.ModuleType("tradingagents.utils"))
logging_manager_stub = types.ModuleType("tradingagents.utils.logging_manager")
logging_manager_stub.get_logger = logging.getLogger
sys.modules["tradingagents.utils.logging_manager"] = logging_manager_stub

module_path = Path(__file__).resolve().parents[2] / "tradingagents" / "industry_analysis" / "candidate_fetcher.py"
spec = importlib.util.spec_from_file_location("candidate_fetcher_under_test", module_path)
candidate_fetcher_module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
sys.modules["candidate_fetcher_under_test"] = candidate_fetcher_module
spec.loader.exec_module(candidate_fetcher_module)

CandidateFetcher = candidate_fetcher_module.CandidateFetcher


class _FakeAK:
    def stock_board_concept_cons_em(self, symbol: str):
        if symbol == "不存在概念":
            raise RuntimeError("board not found")
        payload = {
            "AI": [
                {"代码": "000001", "名称": "平安银行", "所属行业": "银行"},
                {"代码": "sz000002", "名称": "万科A", "所属行业": "房地产"},
            ],
            "算力": [
                {"代码": "000001", "名称": "平安银行", "所属行业": "银行"},
                {"代码": "sh600000", "名称": "浦发银行", "所属行业": "银行"},
            ],
        }
        return pd.DataFrame(payload.get(symbol, []))

    def stock_board_industry_cons_em(self, symbol: str):
        payload = {
            "软件服务": [
                {"代码": "000001", "名称": "平安银行", "所属行业": "银行"},
                {"代码": "600000", "名称": "浦发银行", "所属行业": "银行"},
            ]
        }
        return pd.DataFrame(payload.get(symbol, []))

    def stock_zh_a_spot_em(self):
        return pd.DataFrame(
            [
                {
                    "代码": "sz000001",
                    "名称": "平安银行",
                    "所处行业": "银行",
                    "最新价": 12.34,
                    "涨跌幅": 1.23,
                    "市盈率-动态": 6.7,
                    "市净率": 0.8,
                    "总市值": 30_000_000_000,
                    "流通市值": 25_000_000_000,
                    "换手率": 0.56,
                    "量比": 1.12,
                },
                {
                    "代码": "000002",
                    "名称": "万科A",
                    "所处行业": "房地产",
                    "最新价": 9.87,
                    "涨跌幅": -0.45,
                    "市盈率-动态": 10.1,
                    "市净率": 1.1,
                    "总市值": 5_000_000_000,
                    "流通市值": 4_500_000_000,
                    "换手率": 1.23,
                    "量比": 0.91,
                },
                {
                    "代码": "sh600000",
                    "名称": "浦发银行",
                    "所处行业": "银行",
                    "最新价": 8.88,
                    "涨跌幅": 0.67,
                    "市盈率-动态": 5.5,
                    "市净率": 0.6,
                    "总市值": 20_000_000_000,
                    "流通市值": 18_000_000_000,
                    "换手率": 0.78,
                    "量比": 1.03,
                },
            ]
        )

    def stock_financial_analysis_indicator(self, symbol: str):
        if symbol != "000001":
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "日期": "2023-12-31",
                    "净资产收益率(%)": 9.1,
                    "主营业务收入增长率(%)": 5.2,
                    "净利润增长率(%)": 3.4,
                    "资产负债率(%)": 49.6,
                },
                {
                    "日期": "2024-12-31",
                    "净资产收益率(%)": 12.5,
                    "主营业务收入增长率(%)": 10.0,
                    "净利润增长率(%)": 8.0,
                    "资产负债率(%)": 45.0,
                },
            ]
        )


class CandidateFetcherTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_candidates_deduplicates_and_enriches_metrics(self):
        fetcher = CandidateFetcher(
            ak_client=_FakeAK(),
            request_delay=0,
            financial_enrichment_limit=1,
            data_source_manager=object(),
        )
        mapping = ConceptMappingResult(
            user_concept="AI",
            board_concepts=["AI", "算力", "不存在概念"],
            board_industries=["软件服务"],
            keywords=["AI", "算力"],
            reasoning="test",
        )

        candidates = await fetcher.fetch_candidates(mapping)

        self.assertEqual([item.code for item in candidates], ["000001", "600000", "000002"])

        top_candidate = candidates[0]
        self.assertEqual(top_candidate.name, "平安银行")
        self.assertEqual(top_candidate.source_boards, ["AI", "算力", "软件服务"])
        self.assertEqual(top_candidate.match_score, 3.0)
        self.assertEqual(top_candidate.pe, 6.7)
        self.assertEqual(top_candidate.pb, 0.8)
        self.assertEqual(top_candidate.total_mv, 300.0)
        self.assertEqual(top_candidate.circ_mv, 250.0)
        self.assertEqual(top_candidate.price, 12.34)
        self.assertEqual(top_candidate.pct_chg, 1.23)
        self.assertEqual(top_candidate.turnover_rate, 0.56)
        self.assertEqual(top_candidate.volume_ratio, 1.12)
        self.assertEqual(top_candidate.roe, 12.5)
        self.assertEqual(top_candidate.revenue_growth, 10.0)
        self.assertEqual(top_candidate.net_profit_growth, 8.0)
        self.assertEqual(top_candidate.debt_ratio, 45.0)

        second_candidate = candidates[1]
        self.assertEqual(second_candidate.match_score, 2.0)
        self.assertIsNone(second_candidate.roe)

    async def test_fetch_candidates_returns_empty_when_no_boards(self):
        fetcher = CandidateFetcher(
            ak_client=_FakeAK(),
            request_delay=0,
            financial_enrichment_limit=1,
            data_source_manager=object(),
        )
        mapping = ConceptMappingResult(
            user_concept="AI",
            board_concepts=[],
            board_industries=[],
            keywords=[],
            reasoning="test",
        )

        candidates = await fetcher.fetch_candidates(mapping)

        self.assertEqual(candidates, [])
