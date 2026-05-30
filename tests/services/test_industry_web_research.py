import asyncio


def test_bocha_provider_filters_authority_domains():
    from app.services.industry_web_research import BochaWebResearchProvider

    provider = BochaWebResearchProvider(api_key="sk-valid-bocha-key-123456")
    parsed = provider._parse_response(
        {
            "data": {
                "webPages": {
                    "value": [
                        {
                            "name": "政策文件",
                            "url": "https://www.ndrc.gov.cn/test.html",
                            "snippet": "产业政策",
                        },
                        {
                            "name": "非白名单",
                            "url": "https://example.com/a",
                            "snippet": "ignore",
                        },
                    ]
                }
            }
        }
    )

    assert len(parsed) == 1
    assert parsed[0].domain == "ndrc.gov.cn"


def test_build_authority_queries_uses_site_filters():
    from app.services.industry_web_research import build_authority_queries

    queries = build_authority_queries(["AI"], domains=["gov.cn", "ndrc.gov.cn"])

    assert queries == [
        "AI 行业 政策 报告 site:gov.cn",
        "AI 行业 政策 报告 site:ndrc.gov.cn",
    ]


def test_null_provider_returns_empty_results():
    from app.services.industry_web_research import NullIndustryWebResearchProvider

    async def _run():
        provider = NullIndustryWebResearchProvider()
        results = await provider.search(["AI site:gov.cn"], max_results=5)
        assert results == []

    asyncio.run(_run())
