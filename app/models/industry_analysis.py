"""Industry analysis request and response models."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_serializer

from app.models.analysis import AnalysisStatus
from app.utils.timezone import now_tz


class IndustryAnalysisParameters(BaseModel):
    market: str = Field(default="CN", description="Market scope. First version supports CN A-shares.")
    top_n: int = Field(default=5, ge=1, le=10, description="Number of selected stocks")
    enable_web_search: bool = Field(default=True, description="Whether to use online industry research")
    language: str = Field(default="zh-CN")
    quick_analysis_model: Optional[str] = Field(default="qwen-turbo")
    deep_analysis_model: Optional[str] = Field(default="qwen-max")


class IndustryAnalysisRequest(BaseModel):
    industry_query: str = Field(..., min_length=1, max_length=100, description="Industry or fuzzy concept")
    parameters: Optional[IndustryAnalysisParameters] = None


class IndustrySource(BaseModel):
    title: str = ""
    url: str = ""
    source: str = ""
    domain: str = ""
    published_at: Optional[str] = None
    snippet: str = ""


class IndustryStockPick(BaseModel):
    code: str
    name: str
    industry: Optional[str] = None
    total_score: float = 0.0
    scores: Dict[str, float] = Field(default_factory=dict)
    risk_deduction: float = 0.0
    reason: str = ""
    risk: str = ""
    metrics: Dict[str, Any] = Field(default_factory=dict)


class IndustryAnalysisResult(BaseModel):
    analysis_id: str
    industry_query: str
    market: str = "CN"
    top_n: int = 5
    summary: str = ""
    due_diligence_report: str = ""
    stock_selection_report: str = ""
    picks: List[IndustryStockPick] = Field(default_factory=list)
    candidates_count: int = 0
    keywords: List[str] = Field(default_factory=list)
    sources: List[IndustrySource] = Field(default_factory=list)
    web_search_enabled: bool = False
    web_search_status: str = ""
    disclaimer: str = "仅供研究参考，不构成投资建议。"
    execution_time: float = 0.0
    model_info: Optional[str] = None
    created_at: datetime = Field(default_factory=now_tz)

    @field_serializer("created_at")
    def serialize_datetime(self, dt: Optional[datetime], _info) -> Optional[str]:
        return dt.isoformat() if dt else None


class IndustryAnalysisTaskResponse(BaseModel):
    task_id: str
    industry_query: str
    status: AnalysisStatus
    progress: int = 0
    message: str = ""
    current_step: str = ""
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[IndustryAnalysisResult] = None

    @field_serializer("created_at", "started_at", "completed_at")
    def serialize_datetime(self, dt: Optional[datetime], _info) -> Optional[str]:
        return dt.isoformat() if dt else None
