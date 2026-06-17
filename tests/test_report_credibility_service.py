from datetime import datetime

import pytest

from app.services.report_credibility_service import ReportCredibilityService, format_credibility_markdown
from app.utils.report_exporter import ReportExporter


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def __aiter__(self):
        self._iter = iter(self.docs)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = docs or []

    async def find_one(self, query=None, sort=None):
        matches = [doc for doc in self.docs if self._matches(doc, query or {})]
        if sort:
            for key, direction in reversed(sort):
                matches.sort(key=lambda doc: doc.get(key) or "", reverse=direction < 0)
        return matches[0] if matches else None

    def find(self, query=None):
        return FakeCursor([doc for doc in self.docs if self._matches(doc, query or {})])

    def _matches(self, doc, query):
        if not query:
            return True
        if "$or" in query:
            return any(self._matches(doc, item) for item in query["$or"])
        for key, expected in query.items():
            value = doc.get(key)
            if isinstance(expected, dict) and "$in" in expected:
                if value not in expected["$in"]:
                    return False
            elif value != expected:
                return False
        return True


class FakeDB:
    def __init__(self, collections):
        self.collections = {
            name: FakeCollection(docs)
            for name, docs in collections.items()
        }

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCollection())

    def __getattr__(self, name):
        return self[name]


@pytest.mark.asyncio
async def test_report_credibility_complete_report_tracks_sources_and_cost():
    report = {
        "id": "report-1",
        "analysis_id": "analysis-1",
        "task_id": "task-1",
        "stock_symbol": "000001",
        "source": "api",
        "analysis_date": "2026-06-10",
        "created_at": datetime(2026, 6, 10, 10, 0, 0),
        "model_info": "qwen-max",
        "tokens_used": 12345,
        "confidence_score": 0.72,
        "analysts": ["market", "fundamentals", "news"],
        "reports": {
            "market_report": "市场趋势稳定。",
            "fundamentals_report": "基本面改善。",
            "news_report": "新闻偏正面。",
            "final_trade_decision": "最终结论谨慎买入，但需警惕估值高估风险。",
            "bear_researcher": "估值高估风险仍然存在，若需求下行可能带来压力。",
        },
    }
    db = FakeDB(
        {
            "market_quotes": [
                {"code": "000001", "updated_at": datetime(2026, 6, 10, 9, 30, 0), "source": "akshare"}
            ],
            "stock_basic_info": [
                {"code": "000001", "updated_at": datetime(2026, 6, 9, 8, 0, 0), "source": "tushare"}
            ],
            "stock_financial_data": [
                {"code": "000001", "updated_at": datetime(2026, 6, 8, 8, 0, 0), "source": "tushare"}
            ],
            "token_usage": [
                {
                    "session_id": "task-1",
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "cost": 0.03,
                    "currency": "CNY",
                }
            ],
            "system_configs": [
                {
                    "is_active": True,
                    "version": 1,
                    "data_source_configs": [
                        {"type": "akshare", "enabled": True},
                        {"type": "tushare", "enabled": True},
                    ],
                }
            ],
        }
    )

    credibility = await ReportCredibilityService(db).build(report)

    assert credibility["data_freshness"]["freshness_level"] == "fresh"
    assert credibility["data_sources"]["actual_source_recorded"] is True
    assert credibility["data_sources"]["enabled_sources"] == ["akshare", "tushare"]
    assert credibility["missing_items"] == []
    assert credibility["model_usage"]["cost_source"] == "token_usage"
    assert credibility["model_usage"]["cost"] == 0.03
    assert credibility["confidence_basis"]["label"] == "中上"
    assert credibility["counter_evidence"]


@pytest.mark.asyncio
async def test_report_credibility_old_report_marks_unknowns_without_inventing_sources():
    report = {
        "id": "old-report",
        "analysis_id": "old-analysis",
        "task_id": "old-task",
        "stock_symbol": "000002",
        "source": "unknown",
        "analysis_date": "2026-06-10",
        "model_info": "Unknown",
        "analysts": ["market", "fundamentals", "news"],
        "reports": {"market_report": "仅有市场分析。"},
    }

    credibility = await ReportCredibilityService(FakeDB({})).build(report)

    assert credibility["data_freshness"]["freshness_level"] == "unknown"
    assert credibility["data_sources"]["actual_source_recorded"] is False
    assert credibility["data_sources"]["observed_sources"] == []
    assert credibility["model_usage"]["cost_source"] == "unavailable"
    assert {item["key"] for item in credibility["missing_items"]} == {
        "fundamentals_report",
        "news_report",
        "final_trade_decision",
    }
    assert "实际使用的数据源未完整记录。" in credibility["confidence_basis"]["limiting_factors"]


def test_report_exporter_places_credibility_before_summary():
    exporter = ReportExporter()
    markdown = exporter.generate_markdown_report(
        {
            "stock_symbol": "000001",
            "analysis_date": "2026-06-10",
            "summary": "这是一段摘要。",
            "reports": {},
            "credibility": {
                "data_freshness": {"freshness_level": "unknown", "notes": []},
                "data_sources": {"enabled_sources": [], "observed_sources": [], "actual_source_recorded": False},
                "missing_items": [],
                "model_usage": {"model_info": "qwen-max", "tokens_used": 100, "currency": "CNY", "cost_source": "unavailable"},
                "confidence_basis": {"label": "中等", "positive_factors": [], "limiting_factors": []},
                "counter_evidence": [],
            },
        }
    )

    assert "## 可信度说明" in markdown
    assert markdown.index("## 可信度说明") < markdown.index("## 📊 执行摘要")


def test_report_credibility_fallback_is_exportable():
    credibility = ReportCredibilityService.fallback(
        {
            "stock_symbol": "000001",
            "analysis_date": "2026-06-10",
            "model_info": "qwen-max",
            "tokens_used": 100,
        },
        RuntimeError("boom"),
    )

    markdown = format_credibility_markdown(credibility)

    assert credibility["unavailable"] is True
    assert credibility["confidence_basis"]["label"] == "未知"
    assert "可信度说明" in markdown
    assert "可信度生成失败" in markdown
