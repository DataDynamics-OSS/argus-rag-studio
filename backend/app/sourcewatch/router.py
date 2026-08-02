# SPDX-License-Identifier: Apache-2.0
"""소스 워치 API — 자동 수집(드롭존 무인화) 워치 CRUD·즉시 실행·이력. 설계 design/source-watch.md §5.

엔드포인트(관리자):
    - GET    /source-watches                 워치 목록(+소스명·마지막 실행 요약)
    - POST   /source-watches                 등록(등록 즉시 첫 실행)
    - PUT    /source-watches/{watch_id}      수정
    - DELETE /source-watches/{watch_id}      삭제
    - POST   /source-watches/{watch_id}/run  지금 실행(next_run_at=now — 루프가 즉시 집어감)
    - GET    /source-watches/{watch_id}/runs 실행 이력(최근 100)
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, SuperUser
from app.core.config import settings
from app.core.database import get_session
from app.sourcewatch import service
from app.sourcewatch.models import RagSourceWatch
from app.sourcewatch.schemas import (
    WatchCreateRequest,
    WatchResponse,
    WatchRunResponse,
    WatchUpdateRequest,
)
from app.sources import service as sources_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["source-watches"])


def _to_response(w: RagSourceWatch, source_uuid: str, source_name: str) -> WatchResponse:
    try:
        last_counts = json.loads(w.last_counts_json or "{}")
    except ValueError:
        last_counts = {}
    return WatchResponse(
        watch_id=w.watch_id, source_id=source_uuid, source_name=source_name,
        name=w.name, prefix=w.prefix or "", recursive=w.recursive,
        interval_seconds=w.interval_seconds, enabled=w.enabled,
        next_run_at=w.next_run_at, last_run_at=w.last_run_at,
        last_status=w.last_status, last_error=w.last_error, last_counts=last_counts,
        consecutive_failures=w.consecutive_failures or 0,
        created_by=w.created_by, created_at=w.created_at,
    )


async def _get_or_404(session: AsyncSession, watch_id: str) -> RagSourceWatch:
    w = await service.get_watch(session, watch_id)
    if not w:
        raise HTTPException(status_code=404, detail="워치를 찾을 수 없습니다.")
    return w


def _validate_interval(seconds: int) -> None:
    if seconds < settings.watch_min_interval_seconds:
        raise HTTPException(
            status_code=400,
            detail=f"주기는 최소 {settings.watch_min_interval_seconds}초입니다.",
        )


@router.get("/source-watches", response_model=list[WatchResponse])
async def list_watches(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    watches = await service.list_watches(session)
    out: list[WatchResponse] = []
    for w in watches:
        source = await sources_service.get_source_by_pk(session, w.source_id)
        out.append(_to_response(
            w, source.source_id if source else "", source.name if source else "(삭제됨)"
        ))
    return out


@router.post("/source-watches", response_model=WatchResponse, status_code=201)
async def create_watch(
    req: WatchCreateRequest, user: SuperUser, session: AsyncSession = Depends(get_session)
):
    _validate_interval(req.interval_seconds)
    source = await sources_service.get_source(session, req.source_id)
    if not source:
        raise HTTPException(status_code=404, detail="스토리지 소스를 찾을 수 없습니다.")
    if not source.enabled:
        raise HTTPException(status_code=409, detail=f"비활성화된 소스입니다: {source.name}")
    w = await service.create_watch(session, {
        "source_id": source.id, "name": req.name, "prefix": req.prefix,
        "recursive": req.recursive, "interval_seconds": req.interval_seconds,
        "enabled": req.enabled,
    }, user.username)
    logger.info("워치 등록: %s (source=%s prefix=%s %ds) by %s",
                req.name, source.name, req.prefix, req.interval_seconds, user.username)
    return _to_response(w, source.source_id, source.name)


@router.put("/source-watches/{watch_id}", response_model=WatchResponse)
async def update_watch(
    watch_id: str,
    req: WatchUpdateRequest,
    _user: SuperUser,
    session: AsyncSession = Depends(get_session),
):
    if req.interval_seconds is not None:
        _validate_interval(req.interval_seconds)
    w = await _get_or_404(session, watch_id)
    w = await service.update_watch(session, w, req.model_dump(exclude_unset=True))
    source = await sources_service.get_source_by_pk(session, w.source_id)
    return _to_response(
        w, source.source_id if source else "", source.name if source else "(삭제됨)"
    )


@router.delete("/source-watches/{watch_id}", status_code=204)
async def delete_watch(
    watch_id: str, user: SuperUser, session: AsyncSession = Depends(get_session)
):
    w = await _get_or_404(session, watch_id)
    await service.delete_watch(session, w)
    logger.info("워치 삭제: %s by %s", w.name, user.username)


@router.post("/source-watches/{watch_id}/run", status_code=202)
async def run_watch_now(
    watch_id: str, _user: SuperUser, session: AsyncSession = Depends(get_session)
):
    """지금 실행 — next_run_at 을 당겨 워처 루프가 다음 tick(기본 15초 내)에 집어가게 한다."""
    w = await _get_or_404(session, watch_id)
    if not w.enabled:
        raise HTTPException(status_code=409, detail="비활성화된 워치입니다 — 먼저 활성화하세요.")
    await service.run_now(session, w)
    return {"scheduled": True, "tick_seconds": settings.watch_tick_seconds,
            "watch_enabled": settings.watch_enabled}


@router.get("/source-watches/{watch_id}/runs", response_model=list[WatchRunResponse])
async def watch_runs(
    watch_id: str, _user: CurrentUser, session: AsyncSession = Depends(get_session)
):
    w = await _get_or_404(session, watch_id)
    runs = await service.list_runs(session, w.id, limit=settings.watch_runs_keep)
    out: list[WatchRunResponse] = []
    for r in runs:
        try:
            counts = json.loads(r.counts_json or "{}")
        except ValueError:
            counts = {}
        out.append(WatchRunResponse(
            started_at=r.started_at, finished_at=r.finished_at,
            scanned=r.scanned, skipped=r.skipped, counts=counts,
            truncated=r.truncated, error=r.error,
        ))
    return out
