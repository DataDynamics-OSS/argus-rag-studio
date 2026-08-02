# SPDX-License-Identifier: Apache-2.0
"""평가 API (M4).

데이터셋/항목 CRUD + 평가 Run 실행(비동기) + 지표/결과 조회.

권한: 조회는 로그인 사용자, 생성/삭제/실행은 슈퍼유저 이상.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, SuperUser
from app.core.database import get_session
from app.evaluation import service, sweep_service
from app.evaluation.models import RagEvalRun
from app.evaluation.schemas import (
    DatasetCreateRequest,
    DatasetResponse,
    ItemCreateRequest,
    ItemResponse,
    LeaderboardResponse,
    ResultResponse,
    RunCreateRequest,
    RunResponse,
    SweepApplyResponse,
    SweepCreateRequest,
    SweepResponse,
)
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/eval", tags=["evaluation"])


# ---------------------------------------------------------------------------
# 데이터셋
# ---------------------------------------------------------------------------

@router.post("/datasets", response_model=DatasetResponse, status_code=201)
async def create_dataset(req: DatasetCreateRequest, user: SuperUser, session: AsyncSession = Depends(get_session)):
    try:
        return await service.create_dataset(session, req, created_by=user.username)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/datasets", response_model=list[DatasetResponse])
async def list_datasets(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    return await service.list_datasets(session)


@router.get("/datasets/{dataset_uuid}", response_model=DatasetResponse)
async def get_dataset(dataset_uuid: str, _user: CurrentUser, session: AsyncSession = Depends(get_session)):
    ds = await service.get_dataset_by_uuid(session, dataset_uuid)
    if not ds:
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다.")
    items = await service.list_items(session, ds.id)
    return service._dataset_resp(ds, len(items))


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: int, _user: SuperUser, session: AsyncSession = Depends(get_session)):
    if not await service.delete_dataset(session, dataset_id):
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다.")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# 항목
# ---------------------------------------------------------------------------

@router.post("/datasets/{dataset_id}/items", response_model=ItemResponse, status_code=201)
async def add_item(dataset_id: int, req: ItemCreateRequest, _user: SuperUser, session: AsyncSession = Depends(get_session)):
    if not await service.get_dataset(session, dataset_id):
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다.")
    return await service.add_item(session, dataset_id, req)


@router.get("/datasets/{dataset_id}/items", response_model=list[ItemResponse])
async def list_items(dataset_id: int, _user: CurrentUser, session: AsyncSession = Depends(get_session)):
    return await service.list_items(session, dataset_id)


@router.delete("/items/{item_uuid}")
async def delete_item(item_uuid: str, _user: SuperUser, session: AsyncSession = Depends(get_session)):
    if not await service.delete_item(session, item_uuid):
        raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다.")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Run / 결과
# ---------------------------------------------------------------------------

@router.post("/datasets/{dataset_id}/runs", response_model=RunResponse, status_code=202)
async def create_run(dataset_id: int, req: RunCreateRequest, user: SuperUser, session: AsyncSession = Depends(get_session)):
    """평가 Run 을 enqueue 한다(비동기 실행). run_id 로 진행/지표를 폴링한다."""
    ds = await service.get_dataset(session, dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다.")
    try:
        return await service.create_run(session, ds, req, created_by=user.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/datasets/{dataset_id}/runs", response_model=list[RunResponse])
async def list_runs(dataset_id: int, _user: CurrentUser, session: AsyncSession = Depends(get_session)):
    return await service.list_runs(session, dataset_id)


@router.get("/runs", response_model=list[RunResponse])
async def list_all_runs(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    """전역 평가 런 목록(최신순) — 잡 모니터링용."""
    return await service.list_all_runs(session)


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: str, _user: CurrentUser, session: AsyncSession = Depends(get_session)):
    run = await service.get_run(session, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="평가 Run 을 찾을 수 없습니다.")
    return run


@router.get("/runs/{run_id}/results", response_model=list[ResultResponse])
async def list_results(run_id: str, _user: CurrentUser, session: AsyncSession = Depends(get_session)):
    return await service.list_results(session, run_id)


# ---------------------------------------------------------------------------
# 설정 스윕 / 리더보드
# ---------------------------------------------------------------------------

@router.post("/datasets/{dataset_id}/sweeps", response_model=SweepResponse, status_code=202)
async def create_sweep(
    dataset_id: int, req: SweepCreateRequest, user: SuperUser,
    session: AsyncSession = Depends(get_session),
):
    """설정 스윕을 enqueue 한다(비동기). 스윕 워커가 Run 들을 만들고 평가 워커가 실행한다."""
    ds = await service.get_dataset(session, dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다.")
    try:
        return await sweep_service.create_sweep(session, ds, req, created_by=user.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/datasets/{dataset_id}/sweeps", response_model=list[SweepResponse])
async def list_sweeps(dataset_id: int, _user: CurrentUser, session: AsyncSession = Depends(get_session)):
    return await sweep_service.list_sweeps(session, dataset_id)


@router.get("/sweeps", response_model=list[SweepResponse])
async def list_all_sweeps(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    """전역 스윕 목록(최신순) — 잡 모니터링용."""
    return await sweep_service.list_all_sweeps(session)


@router.get("/sweeps/{sweep_id}", response_model=SweepResponse)
async def get_sweep(sweep_id: str, _user: CurrentUser, session: AsyncSession = Depends(get_session)):
    sweep = await sweep_service.get_sweep(session, sweep_id)
    if not sweep:
        raise HTTPException(status_code=404, detail="스윕을 찾을 수 없습니다.")
    return sweep_service.sweep_resp(sweep)


@router.get("/sweeps/{sweep_id}/leaderboard", response_model=LeaderboardResponse)
async def sweep_leaderboard(sweep_id: str, _user: CurrentUser, session: AsyncSession = Depends(get_session)):
    sweep = await sweep_service.get_sweep(session, sweep_id)
    if not sweep:
        raise HTTPException(status_code=404, detail="스윕을 찾을 수 없습니다.")
    return await sweep_service.leaderboard(session, sweep)


@router.post("/sweeps/{sweep_id}/cancel", response_model=SweepResponse)
async def cancel_sweep(sweep_id: str, _user: SuperUser, session: AsyncSession = Depends(get_session)):
    sweep = await sweep_service.get_sweep(session, sweep_id)
    if not sweep:
        raise HTTPException(status_code=404, detail="스윕을 찾을 수 없습니다.")
    if sweep.status in ("succeeded", "failed", "canceled"):
        raise HTTPException(status_code=409, detail="이미 종료된 스윕입니다.")
    await sweep_service.cancel_sweep(session, sweep)
    return sweep_service.sweep_resp(sweep)


@router.post("/sweeps/{sweep_id}/apply/{run_id}", response_model=SweepApplyResponse)
async def apply_sweep_config(
    sweep_id: str, run_id: str, _user: SuperUser, session: AsyncSession = Depends(get_session),
):
    """우승(또는 선택) Run 의 설정을 base 컬렉션에 적용. 인덱스 설정이 바뀌면 재인덱싱."""
    sweep = await sweep_service.get_sweep(session, sweep_id)
    if not sweep:
        raise HTTPException(status_code=404, detail="스윕을 찾을 수 없습니다.")
    run = (await session.execute(
        select(RagEvalRun).where(RagEvalRun.run_id == run_id, RagEvalRun.sweep_id == sweep.id)
    )).scalars().first()
    if not run:
        raise HTTPException(status_code=404, detail="해당 스윕의 Run 을 찾을 수 없습니다.")
    try:
        result = await sweep_service.apply_config(session, sweep, run)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SweepApplyResponse(**result)
