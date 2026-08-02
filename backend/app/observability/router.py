# SPDX-License-Identifier: Apache-2.0
"""관측 API (운영).

- GET /observability/stats         질의 통계(건수/성공률/지연 p50·p95/토큰/인기 질의)
- GET /observability/traces        최근 트레이스 목록(필터)
- GET /observability/traces/{id}   트레이스 단건
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.database import get_session
from app.observability import service
from app.observability.schemas import StatsResponse, TraceResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/observability", tags=["observability"])


@router.get("/stats", response_model=StatsResponse)
async def get_stats(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    return await service.stats(session)


@router.get("/traces", response_model=list[TraceResponse])
async def list_traces(
    _user: CurrentUser,
    collection_id: int | None = Query(None),
    kind: str | None = Query(None, description="search | query | chat"),
    status: str | None = Query(None, description="ok | error"),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    return await service.list_traces(session, collection_id, kind, status, limit)


@router.get("/traces/{trace_id}", response_model=TraceResponse)
async def get_trace(trace_id: str, _user: CurrentUser, session: AsyncSession = Depends(get_session)):
    t = await service.get_trace(session, trace_id)
    if not t:
        raise HTTPException(status_code=404, detail="트레이스를 찾을 수 없습니다.")
    return t
