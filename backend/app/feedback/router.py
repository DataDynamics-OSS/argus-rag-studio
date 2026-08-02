# SPDX-License-Identifier: Apache-2.0
"""피드백 API — 답변 평가 수집 + 골든셋 승격.

- POST /feedback              피드백 수집(👍/👎 + 코멘트/수정답변) — 로그인 사용자
- GET  /feedback              목록(필터)
- GET  /feedback/stats        통계(up/down/promoted)
- POST /feedback/{id}/promote 평가 골든셋 항목으로 승격 (슈퍼유저)
- POST /feedback/{id}/dismiss 무시 처리
- DELETE /feedback/{id}
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, SuperUser
from app.core.database import get_session
from app.feedback import service
from app.feedback.schemas import (
    FeedbackCreateRequest,
    FeedbackResponse,
    FeedbackStats,
    PromoteRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", response_model=FeedbackResponse, status_code=201)
async def create_feedback(req: FeedbackCreateRequest, user: CurrentUser, session: AsyncSession = Depends(get_session)):
    return await service.create_feedback(session, req, created_by=user.username)


@router.get("", response_model=list[FeedbackResponse])
async def list_feedback(
    _user: CurrentUser,
    rating: str | None = Query(None, description="up | down"),
    status: str | None = Query(None, description="new | promoted | dismissed"),
    collection_id: int | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    return await service.list_feedback(session, rating, status, collection_id, limit)


@router.get("/stats", response_model=FeedbackStats)
async def get_stats(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    return await service.stats(session)


@router.post("/{feedback_id}/promote", response_model=FeedbackResponse)
async def promote(feedback_id: str, req: PromoteRequest, _user: SuperUser, session: AsyncSession = Depends(get_session)):
    f = await service.get(session, feedback_id)
    if not f:
        raise HTTPException(status_code=404, detail="피드백을 찾을 수 없습니다.")
    try:
        return await service.promote(session, f, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{feedback_id}/dismiss", response_model=FeedbackResponse)
async def dismiss(feedback_id: str, _user: SuperUser, session: AsyncSession = Depends(get_session)):
    f = await service.get(session, feedback_id)
    if not f:
        raise HTTPException(status_code=404, detail="피드백을 찾을 수 없습니다.")
    return await service.set_status(session, f, "dismissed")


@router.delete("/{feedback_id}")
async def delete(feedback_id: str, _user: SuperUser, session: AsyncSession = Depends(get_session)):
    if not await service.delete(session, feedback_id):
        raise HTTPException(status_code=404, detail="피드백을 찾을 수 없습니다.")
    return {"status": "ok"}
