from tradingagents.tools.unified_news_tool import UnifiedNewsAnalyzer


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


def test_real_news_like_content_is_usable_news_content():
    content = """
### 紫金矿业发布矿山生产经营进展
发布时间: 2026-06-10 18:30:00
新闻来源: 东方财富

公司公告显示，相关项目建设进度符合预期，管理层表示将继续推进产能释放。
"""

    assert UnifiedNewsAnalyzer._is_usable_news_content(content)
