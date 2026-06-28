from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.database import get_mongo_db
from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services.backtest.backtest_service import BacktestService
from app.services.backtest.mining_service import (
    DEFAULT_SEARCH_SPACE,
    DEFAULT_TEMPLATES,
    MiningService,
    discovered_adaptive_topk_strategy_pack,
)
from app.services.paper_strategy_tracker_service import PaperStrategyTrackerService

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
    mode: str = Field(default="custom", pattern="^(custom|auto_robust)$")
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
    walk_forward: bool = True
    walk_forward_train_days: int = Field(default=504, ge=90, le=1500)
    walk_forward_validation_days: int = Field(default=126, ge=30, le=500)
    walk_forward_test_days: int = Field(default=126, ge=30, le=500)
    walk_forward_step_days: int = Field(default=126, ge=30, le=500)
    max_walk_forward_slices: int = Field(default=4, ge=0, le=12)


class SaveCandidateRequest(BaseModel):
    name: Optional[str] = None
    strategy_id: str
    params: Dict[str, Any] = Field(default_factory=dict)
    universe: Optional[List[str]] = None
    status: str = "active"
    tags: List[str] = Field(default_factory=list)
    note: str = ""
    favorite: bool = False
    source: str = "manual"
    run_id: Optional[str] = None
    trial_index: Optional[int] = None
    score: Optional[float] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
    evaluation: Dict[str, Any] = Field(default_factory=dict)


class UpdateCandidateRequest(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[List[str]] = None
    note: Optional[str] = None
    favorite: Optional[bool] = None
    universe: Optional[List[str]] = None


class SaveDiscoveredAdaptiveTopKRequest(BaseModel):
    universe: Optional[List[str]] = None
    favorite: bool = True


class CandidatePaperTrackerRequest(BaseModel):
    name: Optional[str] = None
    start_date: Optional[str] = None
    tracking_start_date: Optional[str] = None
    open_policy: str = Field(default="next_signal", pattern="^(next_signal|sync_current)$")
    initial_cash: float = Field(default=1_000_000.0, gt=0)
    commission_bps: float = Field(default=5.0, ge=0)
    slippage_bps: float = Field(default=5.0, ge=0)
    adjust: str = Field(default="qfq", pattern="^(qfq|hfq|none)$")
    status: str = "active"
    run_now: bool = False


class ETFUniverseItemRequest(BaseModel):
    code: str
    name: Optional[str] = None
    group: str = "sector"
    active: bool = True
    tags: List[str] = Field(default_factory=list)
    note: str = ""
    source: str = "manual"


class ETFUniverseItemUpdateRequest(BaseModel):
    name: Optional[str] = None
    group: Optional[str] = None
    active: Optional[bool] = None
    tags: Optional[List[str]] = None
    note: Optional[str] = None


def _service() -> BacktestService:
    return BacktestService(get_mongo_db())


def _mining_service() -> MiningService:
    return MiningService(get_mongo_db())


def _paper_tracker_service() -> PaperStrategyTrackerService:
    return PaperStrategyTrackerService(get_mongo_db())


@router.get("/strategies", response_model=dict)
async def list_strategies(current_user: dict = Depends(get_current_user)):
    service = _service()
    return ok({"items": await service.strategies()})


@router.get("/etf-universe", response_model=dict)
async def get_etf_universe(
    include_inactive: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    service = _service()
    return ok({"items": await service.etf_universe(current_user["id"], include_inactive=include_inactive)})


@router.post("/etf-universe", response_model=dict)
async def save_etf_universe_item(payload: ETFUniverseItemRequest, current_user: dict = Depends(get_current_user)):
    service = _service()
    try:
        return ok(await service.etf_universe_service.upsert_item(current_user["id"], payload.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/etf-universe/{code}", response_model=dict)
async def update_etf_universe_item(
    code: str,
    payload: ETFUniverseItemUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    service = _service()
    try:
        return ok(await service.etf_universe_service.update_item(current_user["id"], code, payload.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/etf-universe/refresh-basic", response_model=dict)
async def refresh_etf_basic_info(
    source: str = Query("akshare", pattern="^(akshare|tushare)$"),
    current_user: dict = Depends(get_current_user),
):
    service = _service()
    return ok(await service.etf_universe_service.refresh_basic_info(source=source))


@router.get("/etf-search", response_model=dict)
async def search_etfs(
    q: str = Query("", max_length=80),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    service = _service()
    return ok({"items": await service.etf_universe_service.search_basic(q, limit=limit)})


@router.post("/run", response_model=dict)
async def run_backtest(payload: RunBacktestRequest, current_user: dict = Depends(get_current_user)):
    service = _service()
    try:
        result = await service.run_backtest(**payload.model_dump(), user_id=current_user["id"])
        return ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/compare", response_model=dict)
async def compare_backtests(payload: CompareBacktestRequest, current_user: dict = Depends(get_current_user)):
    service = _service()
    common = payload.model_dump(exclude={"strategies"})
    requests = [item.model_dump() for item in payload.strategies]
    try:
        result = await service.compare(requests, common, user_id=current_user["id"])
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
        result = await service.entry_offset_stability(**payload.model_dump(), user_id=current_user["id"])
        return ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/mine", response_model=dict)
async def start_mining(payload: MiningRequest, current_user: dict = Depends(get_current_user)):
    service = _mining_service()
    run_id = await service.start(payload.model_dump(), current_user["id"])
    return ok({"run_id": run_id, "status": "pending"})


@router.get("/strategy-packs/discovered/adaptive-topk-gap02", response_model=dict)
async def get_discovered_adaptive_topk_strategy_pack(current_user: dict = Depends(get_current_user)):
    return ok(discovered_adaptive_topk_strategy_pack())


@router.get("/mine/{run_id}", response_model=dict)
async def get_mining_run(run_id: str, current_user: dict = Depends(get_current_user)):
    service = _mining_service()
    result = await service.get(run_id, current_user["id"])
    if not result:
        raise HTTPException(status_code=404, detail="Mining run not found")
    return ok(result)


@router.get("/candidates", response_model=dict)
async def list_candidates(
    limit: int = Query(100, ge=1, le=500),
    strategy_id: Optional[str] = None,
    status: str = Query("active"),
    tag: Optional[str] = None,
    favorite: Optional[bool] = None,
    keyword: Optional[str] = None,
    sort_by: str = Query("created", pattern="^(created|updated|score|applied)$"),
    current_user: dict = Depends(get_current_user),
):
    service = _mining_service()
    return ok(
        {
            "items": await service.list_candidates(
                current_user["id"],
                limit=limit,
                strategy_id=strategy_id,
                status=status,
                tag=tag,
                favorite=favorite,
                keyword=keyword,
                sort_by=sort_by,
            )
        }
    )


@router.post("/candidates", response_model=dict)
async def save_candidate(payload: SaveCandidateRequest, current_user: dict = Depends(get_current_user)):
    service = _mining_service()
    return ok(await service.save_candidate(payload.model_dump(), current_user["id"]))


@router.post("/candidates/discovered/adaptive-topk-gap02", response_model=dict)
async def save_discovered_adaptive_topk_candidate(
    payload: SaveDiscoveredAdaptiveTopKRequest,
    current_user: dict = Depends(get_current_user),
):
    service = _mining_service()
    return ok(
        await service.save_discovered_adaptive_topk_candidate(
            current_user["id"],
            universe=payload.universe,
            favorite=payload.favorite,
        )
    )


@router.post("/candidates/{candidate_id}/paper-tracker", response_model=dict)
async def create_paper_tracker_from_candidate(
    candidate_id: str,
    payload: CandidatePaperTrackerRequest,
    current_user: dict = Depends(get_current_user),
):
    mining = _mining_service()
    paper = _paper_tracker_service()
    try:
        applied = await mining.apply_candidate(candidate_id, current_user["id"])
        candidate = applied["candidate"]
        tracker = await paper.create_tracker(
            current_user["id"],
            {
                "name": payload.name or candidate.get("name") or f"{candidate['strategy_id']} 参数跟踪",
                "strategy_id": candidate["strategy_id"],
                "params": candidate.get("params") or {},
                "universe": candidate.get("universe") or None,
                "candidate_id": candidate_id,
                "start_date": payload.start_date,
                "tracking_start_date": payload.tracking_start_date,
                "open_policy": payload.open_policy,
                "initial_cash": payload.initial_cash,
                "commission_bps": payload.commission_bps,
                "slippage_bps": payload.slippage_bps,
                "adjust": payload.adjust,
                "status": payload.status,
            },
        )
        run_result = await paper.run_tracker(tracker["tracker_id"], current_user["id"], force=True) if payload.run_now else None
        return ok({"candidate": candidate, "tracker": tracker, "run": run_result})
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/candidates/{candidate_id}", response_model=dict)
async def update_candidate(
    candidate_id: str,
    payload: UpdateCandidateRequest,
    current_user: dict = Depends(get_current_user),
):
    service = _mining_service()
    try:
        return ok(await service.update_candidate(candidate_id, payload.model_dump(exclude_unset=True), current_user["id"]))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/candidates/{candidate_id}", response_model=dict)
async def delete_candidate(candidate_id: str, current_user: dict = Depends(get_current_user)):
    service = _mining_service()
    deleted = await service.delete_candidate(candidate_id, current_user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return ok({"deleted": True})


@router.post("/candidates/{candidate_id}/apply", response_model=dict)
async def apply_candidate(candidate_id: str, current_user: dict = Depends(get_current_user)):
    service = _mining_service()
    try:
        return ok(await service.apply_candidate(candidate_id, current_user["id"]))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
