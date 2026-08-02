# SPDX-License-Identifier: Apache-2.0
"""에이전트 하트비트 수신 API."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import heartbeat_service
from app.agent.schemas import HeartbeatRequest
from app.core.database import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/heartbeat")
async def agent_heartbeat(
    req: HeartbeatRequest,
    session: AsyncSession = Depends(get_session),
):
    """에이전트 하트비트 수신. 신규는 UNREGISTERED 로 INSERT, 기존은 메트릭 갱신."""
    await heartbeat_service.process_heartbeat(session, req)
    return {"status": "ok"}
