from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.database import get_mongo_db
from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services.backtest.backtest_service import BacktestService
from app.services.backtest.mining_service import DEFAULT_SEARCH_SPACE, DEFAULT_TEMPLATES, MiningService

router = APIRouter(prefix="/backtest", tags=["backtest"])


class RunBacktestRequest(BaseModel):
    strategy_id: str
    start_date: str
    end_date: str
    universe: Optional[List[str]] = None
    initial_cash: float = Field(default=1_000_000.0, gt=0)
    commission_bps: float = Field(default=5.0, ge=0)
    slippage_bps: float = Field(default=5.0, ge=0)
    adjust: str = Field(default="qfq", pattern="^(qfq|hfq|none)$")
    params: Dict[str, Any] = Field(default_factory=dict)


class CompareStrategyRequest(BaseModel):
    strategy_id: str
    label: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)


class CompareBacktestRequest(BaseModel):
    start_date: str
    end_date: str
    universe: Optional[List[str]] = None
    initial_cash: float = Field(default=1_000_000.0, gt=0)
    commission_bps: float = Field(default=5.0, ge=0)
    slippage_bps: float = Field(default=5.0, ge=0)
    adjust: str = Field(default="qfq", pattern="^(qfq|hfq|none)$")
    strategies: List[CompareStrategyRequest] = Field(default_factory=list, min_length=1)


class EntryOffsetStabilityRequest(BaseModel):
    strategy_id: str
    start_date: str
    end_date: str
    universe: Optional[List[str]] = None
    initial_cash: float = Field(default=1_000_000.0, gt=0)
    commission_bps: float = Field(default=5.0, ge=0)
    slippage_bps: float = Field(default=5.0, ge=0)
    adjust: str = Field(default="qfq", pattern="^(qfq|hfq|none)$")
    params: Dict[str, Any] = Field(default_factory=dict)
    offset_start: int = Field(default=0, ge=0, le=120)
    offset_end: int = Field(default=20, ge=0, le=120)
    offset_step: int = Field(default=1, ge=1, le=30)


class MiningRequest(BaseModel):
    start_date: str
    end_date: str
    universe: Optional[List[str]] = None
    templates: List[str] = Field(default_factory=lambda: list(DEFAULT_TEMPLATES))
    search_method: str = Field(default="random", pattern="^(random|grid)$")
    search_space: Dict[str, List[Any]] = Field(default_factory=lambda: dict(DEFAULT_SEARCH_SPACE))
    max_trials: int = Field(default=40, ge=1, le=300)
    seed: int = 7
    initial_cash: float = Field(default=1_000_000.0, gt=0)
    commission_bps: float = Field(default=5.0, ge=0)
    slippage_bps: float = Field(default=5.0, ge=0)
    adjust: str = Field(default="qfq", pattern="^(qfq|hfq|none)$")
    objective: str = "sample_out_calmar"
    constraints: Dict[str, Any] = Field(default_factory=dict)


class SaveCandidateRequest(BaseModel):
    name: Optional[str] = None
    strategy_id: str
    params: Dict[str, Any] = Field(default_factory=dict)
    run_id: Optional[str] = None
    trial_index: Optional[int] = None
    score: Optional[float] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)


def _service() -> BacktestService:
    return BacktestService(get_mongo_db())


def _mining_service() -> MiningService:
    return MiningService(get_mongo_db())


@router.get("/strategies", response_model=dict)
async def list_strategies(current_user: dict = Depends(get_current_user)):
    service = _service()
    return ok({"items": await service.strategies()})


@router.get("/etf-universe", response_model=dict)
async def get_etf_universe(current_user: dict = Depends(get_current_user)):
    service = _service()
    return ok({"items": await service.etf_universe()})


@router.post("/run", response_model=dict)
async def run_backtest(payload: RunBacktestRequest, current_user: dict = Depends(get_current_user)):
    service = _service()
    try:
        result = await service.run_backtest(**payload.model_dump())
        return ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/compare", response_model=dict)
async def compare_backtests(payload: CompareBacktestRequest, current_user: dict = Depends(get_current_user)):
    service = _service()
    common = payload.model_dump(exclude={"strategies"})
    requests = [item.model_dump() for item in payload.strategies]
    try:
        result = await service.compare(requests, common)
        return ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/stability/entry-offset", response_model=dict)
async def entry_offset_stability(
    payload: EntryOffsetStabilityRequest,
    current_user: dict = Depends(get_current_user),
):
    service = _service()
    try:
        result = await service.entry_offset_stability(**payload.model_dump())
        return ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/mine", response_model=dict)
async def start_mining(payload: MiningRequest, current_user: dict = Depends(get_current_user)):
    service = _mining_service()
    run_id = await service.start(payload.model_dump(), current_user["id"])
    return ok({"run_id": run_id, "status": "pending"})


@router.get("/mine/{run_id}", response_model=dict)
async def get_mining_run(run_id: str, current_user: dict = Depends(get_current_user)):
    service = _mining_service()
    result = await service.get(run_id, current_user["id"])
    if not result:
        raise HTTPException(status_code=404, detail="Mining run not found")
    return ok(result)


@router.get("/candidates", response_model=dict)
async def list_candidates(limit: int = 100, current_user: dict = Depends(get_current_user)):
    service = _mining_service()
    return ok({"items": await service.list_candidates(current_user["id"], limit=limit)})


@router.post("/candidates", response_model=dict)
async def save_candidate(payload: SaveCandidateRequest, current_user: dict = Depends(get_current_user)):
    service = _mining_service()
    return ok(await service.save_candidate(payload.model_dump(), current_user["id"]))
