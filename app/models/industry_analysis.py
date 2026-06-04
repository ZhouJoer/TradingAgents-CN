"""
行业/概念分析 - 数据模型
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class DetailLevel(str, Enum):
    """已弃用：分析详细程度。当前流水线始终执行完整两阶段分析。"""
    BRIEF = "brief"      # 已弃用，仅保留向后兼容
    DETAILED = "detailed"  # 已弃用，仅保留向后兼容


class IndustryAnalysisRequest(BaseModel):
    """行业分析请求"""
    concept: str = Field(..., description="行业/概念关键词，如'AI相关'、'高股息'、'新能源'")
    detail_level: Optional[DetailLevel] = Field(
        DetailLevel.DETAILED,
        description="已弃用；仅为向后兼容保留，当前始终执行完整两阶段分析",
    )
    top_n: int = Field(5, ge=1, le=20, description="推荐股票数量")
    market: str = Field("CN", description="市场（目前仅支持CN）")
    quick_analysis_model: Optional[str] = Field(None, description="快速分析模型（可选，默认系统推荐）")
    deep_analysis_model: Optional[str] = Field(None, description="深度分析模型（可选，默认系统推荐）")


class IndustryAnalysisTaskResponse(BaseModel):
    """行业分析任务提交响应"""
    task_id: str
    status: str = "pending"
    concept: str
    created_at: datetime = Field(default_factory=datetime.now)


class ConceptMappingResult(BaseModel):
    """概念映射结果"""
    user_concept: str = Field(..., description="用户输入的原始概念")
    board_concepts: List[str] = Field(default_factory=list, description="映射到的AKShare概念板块名称")
    board_industries: List[str] = Field(default_factory=list, description="映射到的AKShare行业板块名称")
    keywords: List[str] = Field(default_factory=list, description="相关搜索关键词")
    reasoning: str = Field("", description="映射推理过程")


class StockCandidate(BaseModel):
    """候选股票数据"""
    code: str = Field(..., description="股票代码")
    name: str = Field("", description="股票名称")
    industry: str = Field("", description="所属行业")
    # 基本面指标
    pe: Optional[float] = Field(None, description="市盈率")
    pb: Optional[float] = Field(None, description="市净率")
    roe: Optional[float] = Field(None, description="净资产收益率(%)")
    total_mv: Optional[float] = Field(None, description="总市值(亿)")
    circ_mv: Optional[float] = Field(None, description="流通市值(亿)")
    revenue_growth: Optional[float] = Field(None, description="营收增速(%)")
    net_profit_growth: Optional[float] = Field(None, description="净利润增速(%)")
    debt_ratio: Optional[float] = Field(None, description="资产负债率(%)")
    # 技术面指标
    price: Optional[float] = Field(None, description="当前价格")
    pct_chg: Optional[float] = Field(None, description="当日涨跌幅(%)")
    pct_chg_5d: Optional[float] = Field(None, description="近5日涨跌幅(%)")
    pct_chg_20d: Optional[float] = Field(None, description="近20日涨跌幅(%)")
    turnover_rate: Optional[float] = Field(None, description="换手率(%)")
    volume_ratio: Optional[float] = Field(None, description="量比")
    # 来源信息
    source_boards: List[str] = Field(default_factory=list, description="来自哪些板块")
    match_score: float = Field(0.0, description="概念匹配度评分")


class StockRecommendation(BaseModel):
    """单只股票推荐结果"""
    rank: int = Field(..., description="排名")
    code: str = Field(..., description="股票代码")
    name: str = Field("", description="股票名称")
    industry: str = Field("", description="所属行业")
    # 核心推荐信息
    summary: str = Field("", description="推荐理由摘要")
    score: float = Field(0.0, description="综合评分(0-100)")
    recommendation_logic: str = Field("", description="推荐逻辑")
    main_advantages: str = Field("", description="主要优势")
    main_risks: str = Field("", description="主要风险")
    suitable_style: str = Field("", description="适合风格")
    supply_chain_position: str = Field("", description="产业链位置")
    score_breakdown: Dict[str, float] = Field(default_factory=dict, description="各维度评分明细")
    # 兼容旧版详版字段
    concept_match: Optional[str] = Field(None, description="概念匹配度分析")
    industry_position: Optional[str] = Field(None, description="行业地位分析")
    growth_prospect: Optional[str] = Field(None, description="发展前景分析")
    fundamentals: Optional[str] = Field(None, description="基本面分析")
    technicals: Optional[str] = Field(None, description="技术面分析")
    financials: Optional[str] = Field(None, description="财务状况分析")
    # 关键指标快照
    key_metrics: Dict[str, Any] = Field(default_factory=dict, description="关键指标")


class IndustryAnalysisResult(BaseModel):
    """行业分析最终结果"""
    concept: str = Field(..., description="分析的概念/行业")
    detail_level: Optional[DetailLevel] = Field(
        DetailLevel.DETAILED,
        description="已弃用；仅为向后兼容保留，当前始终输出完整分析",
    )
    # 概念映射信息
    mapped_boards: List[str] = Field(default_factory=list, description="映射到的板块")
    candidate_count: int = Field(0, description="初始候选股数量")
    filtered_count: int = Field(0, description="预筛后候选股数量")
    # 推荐结果
    recommendations: List[StockRecommendation] = Field(default_factory=list)
    due_diligence_report: str = Field("", description="Stage 1 行业尽调完整 Markdown 报告")
    stock_selection_report: str = Field("", description="Stage 2 个股筛选完整 Markdown 报告")
    # 整体分析
    market_overview: str = Field("", description="该概念/行业整体市场概述")
    selection_reasoning: str = Field("", description="选股逻辑说明")
    risk_warning: str = Field("", description="风险提示")
    exclusion_reasons: str = Field("", description="未入选/剔除原因（Markdown）")
    portfolio_advice: str = Field("", description="组合建议（Markdown）")
    tracking_indicators: str = Field("", description="跟踪指标（Markdown）")
    conclusion: str = Field("", description="最终结论（Markdown）")
    # 元信息
    analysis_time: float = Field(0.0, description="分析耗时(秒)")
    llm_calls: int = Field(0, description="LLM调用次数")
    data_date: str = Field("", description="数据日期")


class IndustryAnalysisStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IndustryAnalysisTask(BaseModel):
    """行业分析任务（存储在MongoDB）"""
    task_id: str
    user_id: Optional[str] = None
    concept: str
    detail_level: Optional[DetailLevel] = DetailLevel.DETAILED
    top_n: int = 5
    status: IndustryAnalysisStatus = IndustryAnalysisStatus.PENDING
    progress: int = Field(0, ge=0, le=100, description="进度百分比")
    progress_message: str = Field("", description="当前进度描述")
    result: Optional[IndustryAnalysisResult] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
