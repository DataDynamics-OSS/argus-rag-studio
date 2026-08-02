# SPDX-License-Identifier: Apache-2.0
"""워커 모니터링 API."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.database import get_session
from app.workers import service
from app.workers.schemas import WorkerInfo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workers"])


@router.get("/workers", response_model=list[WorkerInfo])
async def list_workers(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    """인제스천 워커 목록 — 하트비트 기반 생존·현재 잡·처리량(잡 모니터링 '워커' 탭).

    워커는 별도 프로세스(또는 API in-process)로 돌며 기동 시 자신을 등록하고 주기적으로
    하트비트한다. ``alive=false`` 는 최근 하트비트가 끊긴 워커다.
    """
    return await service.list_workers(session)
