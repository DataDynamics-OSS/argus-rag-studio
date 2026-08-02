# SPDX-License-Identifier: Apache-2.0
"""외부 확장 서버 레지스트리 API — 레플리카 하트비트 수신 + 목록."""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.config import settings
from app.core.database import get_session
from app.embedding.router import ExtServerStat
from app.extservers import service
from app.extservers.schemas import ExtServerHeartbeat

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ext-servers"])


def _verify_token(x_heartbeat_token: str | None) -> None:
    """하트비트 토큰 검증. ``monitoring.heartbeat_token`` 이 비어 있으면(개발) 강제하지 않는다."""
    expected = settings.ext_heartbeat_token
    if not expected:
        return
    if x_heartbeat_token != expected:
        raise HTTPException(status_code=401, detail="유효하지 않은 하트비트 토큰")


@router.post("/ext-servers/heartbeat", status_code=204)
async def heartbeat(
    hb: ExtServerHeartbeat,
    x_heartbeat_token: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
):
    """확장 서버 레플리카가 주기적으로 보내는 하트비트(자기 등록). 인증은 공유 토큰(선택)."""
    _verify_token(x_heartbeat_token)
    await service.record_heartbeat(session, hb)


@router.delete("/ext-servers/{instance_id}", status_code=204)
async def deregister(
    instance_id: str,
    x_heartbeat_token: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
):
    """레플리카가 정상 종료 시 자신을 즉시 제거(서버 종료 훅에서 호출). 인증은 하트비트 토큰(선택)."""
    _verify_token(x_heartbeat_token)
    await service.deregister(session, instance_id)


@router.get("/ext-servers", response_model=list[ExtServerStat])
async def list_ext_servers(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    """등록된 확장 서버 레플리카(하트비트 기반) — LB 뒤 풀 전체를 본다. '외부 서버' 탭이 사용."""
    return await service.list_registered(session)
