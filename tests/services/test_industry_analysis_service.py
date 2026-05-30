def test_score_candidates_returns_a_share_top_picks():
    from app.services.industry_analysis_service import IndustryAnalysisService

    svc = IndustryAnalysisService()
    candidates = [
        {
            "code": "000001",
            "name": "平安银行",
            "industry": "银行",
            "total_mv": 1000,
            "amount": 50,
            "roe": 12,
            "pe": 6,
            "pb": 0.8,
            "pct_chg": 1,
        },
        {
            "code": "300001",
            "name": "AI服务器公司",
            "industry": "人工智能",
            "total_mv": 500,
            "amount": 80,
            "roe": 8,
            "pe": 30,
            "pb": 3,
            "pct_chg": 2,
        },
    ]

    picks = svc._score_candidates(candidates, "AI相关", ["AI", "人工智能", "服务器"], 1)

    assert len(picks) == 1
    assert picks[0].code == "300001"
    assert picks[0].total_score > 0
    assert "概念相关性" in picks[0].scores
