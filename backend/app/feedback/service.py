# SPDX-License-Identifier: Apache-2.0
"""피드백 서비스 — 수집 + 조회/통계 + 골든셋 승격(promote).

승격은 피드백(질문/수정답변/기대출처)을 평가 데이터셋의 항목으로 추가하고, 피드백
상태를 ``promoted`` 로 바꾼다. 이렇게 사용자 피드백이 평가 골든셋을 보강하는 루프가 닫힌다.
"""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.feedback.models import RagFeedback
from app.feedback.schemas import (
    FeedbackCreateRequest,
    FeedbackResponse,
    FeedbackStats,
    PromoteRequest,
)

logger = logging.getLogger(__name__)


def _split(text: str | None) -> list[str]:
    return [s.strip() for s in (text or "").splitlines() if s.strip()]


def _resp(f: RagFeedback) -> FeedbackResponse:
    return FeedbackResponse(
        id=f.id, feedback_id=f.feedback_id, trace_id=f.trace_id, collection_id=f.collection_id,
        query=f.query, answer=f.answer, rating=f.rating, comment=f.comment,
        corrected_answer=f.corrected_answer, expected_sources=_split(f.expected_sources),
        status=f.status, promoted_item_id=f.promoted_item_id, created_by=f.created_by,
        created_at=f.created_at,
    )


async def create_feedback(
    session: AsyncSession, req: FeedbackCreateRequest, created_by: str | None
) -> FeedbackResponse:
    f = RagFeedback(
        feedback_id=str(uuid.uuid4()), trace_id=req.trace_id, collection_id=req.collection_id,
        query=req.query, answer=req.answer, rating=req.rating, comment=req.comment,
        corrected_answer=req.corrected_answer,
        expected_sources="\n".join(req.expected_sources), status="new", created_by=created_by,
    )
    session.add(f)
    await session.commit()
    await session.refresh(f)
    logger.info("피드백 수집: %s (%s)", req.rating, req.query[:30])
    return _resp(f)


async def list_feedback(
    session: AsyncSession, rating: str | None = None, status: str | None = None,
    collection_id: int | None = None, limit: int = 100,
) -> list[FeedbackResponse]:
    stmt = select(RagFeedback)
    if rating:
        stmt = stmt.where(RagFeedback.rating == rating)
    if status:
        stmt = stmt.where(RagFeedback.status == status)
    if collection_id is not None:
        stmt = stmt.where(RagFeedback.collection_id == collection_id)
    stmt = stmt.order_by(RagFeedback.created_at.desc()).limit(limit)
    return [_resp(f) for f in (await session.execute(stmt)).scalars().all()]


async def get(session: AsyncSession, feedback_uuid: str) -> RagFeedback | None:
    # 외부 노출 식별자는 피드백 UUID(feedback_id).
    return (await session.execute(
        select(RagFeedback).where(RagFeedback.feedback_id == feedback_uuid)
    )).scalars().first()


async def stats(session: AsyncSession) -> FeedbackStats:
    async def _count(**w):
        stmt = select(func.count()).select_from(RagFeedback)
        for k, v in w.items():
            stmt = stmt.where(getattr(RagFeedback, k) == v)
        return (await session.execute(stmt)).scalar() or 0

    return FeedbackStats(
        total=await _count(), up=await _count(rating="up"), down=await _count(rating="down"),
        new=await _count(status="new"), promoted=await _count(status="promoted"),
    )


async def promote(
    session: AsyncSession, feedback: RagFeedback, req: PromoteRequest
) -> FeedbackResponse:
    """피드백을 평가 데이터셋 항목으로 승격한다(질문/기대답변/기대출처 → 골든셋)."""
    from app.evaluation.models import RagEvalDataset
    from app.evaluation.schemas import ItemCreateRequest
    from app.evaluation.service import add_item

    ds = (await session.execute(
        select(RagEvalDataset).where(RagEvalDataset.id == req.dataset_id)
    )).scalars().first()
    if not ds:
        raise ValueError("데이터셋을 찾을 수 없습니다.")

    expected_answer = req.expected_answer or feedback.corrected_answer or feedback.answer
    expected_sources = (
        req.expected_sources if req.expected_sources is not None
        else _split(feedback.expected_sources)
    )
    item = await add_item(session, ds.id, ItemCreateRequest(
        question=feedback.query, expected_answer=expected_answer, expected_sources=expected_sources,
    ))
    feedback.status = "promoted"
    feedback.promoted_item_id = item.id
    await session.commit()
    await session.refresh(feedback)
    logger.info("피드백 승격: feedback=%d → dataset=%s item=%d", feedback.id, ds.name, item.id)
    return _resp(feedback)


async def set_status(session: AsyncSession, feedback: RagFeedback, status: str) -> FeedbackResponse:
    feedback.status = status
    await session.commit()
    await session.refresh(feedback)
    return _resp(feedback)


async def delete(session: AsyncSession, feedback_uuid: str) -> bool:
    f = await get(session, feedback_uuid)
    if not f:
        return False
    await session.delete(f)
    await session.commit()
    return True
