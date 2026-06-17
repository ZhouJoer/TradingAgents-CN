from tradingagents.tools.unified_news_tool import (
    UnifiedNewsAnalyzer,
    build_news_fetch_failure_report,
    is_usable_news_content,
)


def test_failure_message_is_not_usable_news_content():
    content = """
实时新闻获取失败 - 601899
分析日期: 2026-06-10

错误信息: 所有可用的新闻源都未能获取到相关新闻

备用建议:
1. 检查网络连接和API密钥配置
2. 使用基础新闻分析作为备选
"""

    assert not UnifiedNewsAnalyzer._is_usable_news_content(content)


def test_short_or_empty_content_is_not_usable_news_content():
    assert not is_usable_news_content("")
    assert not is_usable_news_content("暂无新闻")


def test_market_failure_texts_are_not_usable_news_content():
    hk_failure = """
无法获取港股新闻数据 - 00700.HK
错误信息: 所有可用的新闻源均不可用，请检查 API 服务状态。
处理建议: 修复数据源后重新运行新闻分析。
"""
    us_failure = """
Real-time news unavailable for AAPL.
failed: all providers unavailable, no news content was returned by the configured API service.
"""

    assert not UnifiedNewsAnalyzer._is_usable_news_content(hk_failure)
    assert not is_usable_news_content(us_failure)


def test_real_news_like_content_is_usable_news_content():
    content = """
### 紫金矿业发布矿山生产经营进展
发布时间: 2026-06-10 18:30:00
新闻来源: 东方财富

公司公告显示，相关项目建设进度符合预期，管理层表示将继续推进产能释放。
"""

    assert UnifiedNewsAnalyzer._is_usable_news_content(content)


def test_failure_report_keeps_data_failure_distinct_from_no_news():
    report = build_news_fetch_failure_report("腾讯控股", "00700.HK", "无法获取港股新闻数据")

    assert "腾讯控股" in report
    assert "00700.HK" in report
    assert "新闻数据获取失败" in report
    assert "不能据此判断“该股票没有新闻”" in report
