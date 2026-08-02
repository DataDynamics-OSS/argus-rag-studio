# SPDX-License-Identifier: Apache-2.0
"""관측 서비스 — 트레이스 기록 + 조회 + 통계 집계.

``record_trace`` 는 요청 트랜잭션과 분리된 자체 세션으로 best-effort 기록한다(관측이
요청을 깨뜨리지 않도록 예외를 삼킨다). ``stats`` 는 Postgres percentile_cont 로 p50/p95 를 낸다.
"""

import logging
import uuid

from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session
from app.observability.models import RagQueryTrace
from app.observability.schemas import (
    LatencyStat,
    StatsResponse,
    TopQuery,
    TraceResponse,
)

logger = logging.getLogger(__name__)


async def record_trace(
    *,
    kind: str,
    collection_id: int | None,
    query: str | None,
    mode: str | None,
    distance_metric: str | None = None,
    rerank: bool,
    status: str,
    error: str | None,
    hit_count: int,
    embedding_ms: float | None = None,
    search_ms: float | None = None,
    retrieval_ms: float | None,
    rerank_ms: float | None,
    generation_ms: float | None,
    total_ms: float | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    answer: str | None,
    created_by: str | None,
) -> str | None:
    """질의 트레이스를 기록하고 trace_id 를 반환한다(자체 세션, 실패해도 조용히 무시)."""
    tid = str(uuid.uuid4())
    try:
        async with async_session() as session:
            session.add(RagQueryTrace(
                trace_id=tid, kind=kind, collection_id=collection_id,
                query=(query or "")[:2000], mode=mode, distance_metric=distance_metric,
                rerank=rerank, status=status,
                error=(error or None) and str(error)[:2000], hit_count=hit_count,
                embedding_ms=embedding_ms, search_ms=search_ms,
                retrieval_ms=retrieval_ms, rerank_ms=rerank_ms, generation_ms=generation_ms,
                total_ms=total_ms, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                answer=(answer or None) and answer[:settings.observability_answer_limit], created_by=created_by,
            ))
            await session.commit()
        return tid
    except Exception as e:  # 관측은 요청을 막지 않는다
        logger.warning("트레이스 기록 실패: %s", e)
        return None


def _to_response(t: RagQueryTrace) -> TraceResponse:
    return TraceResponse(
        id=t.id, trace_id=t.trace_id, kind=t.kind, collection_id=t.collection_id,
        query=t.query, mode=t.mode, distance_metric=t.distance_metric,
        rerank=t.rerank, status=t.status, error=t.error,
        hit_count=t.hit_count, retrieval_ms=t.retrieval_ms, rerank_ms=t.rerank_ms,
        generation_ms=t.generation_ms, total_ms=t.total_ms, prompt_tokens=t.prompt_tokens,
        completion_tokens=t.completion_tokens, answer=t.answer, created_by=t.created_by,
        created_at=t.created_at,
    )


async def list_traces(
    session: AsyncSession,
    collection_id: int | None = None,
    kind: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[TraceResponse]:
    stmt = select(RagQueryTrace)
    if collection_id is not None:
        stmt = stmt.where(RagQueryTrace.collection_id == collection_id)
    if kind:
        stmt = stmt.where(RagQueryTrace.kind == kind)
    if status:
        stmt = stmt.where(RagQueryTrace.status == status)
    stmt = stmt.order_by(desc(RagQueryTrace.created_at)).limit(limit)
    return [_to_response(t) for t in (await session.execute(stmt)).scalars().all()]


async def get_trace(session: AsyncSession, trace_id: str) -> TraceResponse | None:
    t = (await session.execute(
        select(RagQueryTrace).where(RagQueryTrace.trace_id == trace_id)
    )).scalars().first()
    return _to_response(t) if t else None


async def _latency(session: AsyncSession, column) -> LatencyStat:
    row = (await session.execute(
        select(
            func.avg(column),
            func.percentile_cont(0.5).within_group(column.asc()),
            func.percentile_cont(0.95).within_group(column.asc()),
        ).where(column.isnot(None))
    )).first()
    rnd = lambda v: round(float(v), 1) if v is not None else None  # noqa: E731
    return LatencyStat(avg=rnd(row[0]), p50=rnd(row[1]), p95=rnd(row[2]))


async def stats(session: AsyncSession) -> StatsResponse:
    total = (await session.execute(select(func.count()).select_from(RagQueryTrace))).scalar() or 0
    ok = (await session.execute(
        select(func.count()).where(RagQueryTrace.status == "ok")
    )).scalar() or 0
    err = total - ok

    pt = (await session.execute(select(func.coalesce(func.sum(RagQueryTrace.prompt_tokens), 0)))).scalar() or 0
    ct = (await session.execute(select(func.coalesce(func.sum(RagQueryTrace.completion_tokens), 0)))).scalar() or 0

    top_rows = (await session.execute(
        select(RagQueryTrace.query, func.count().label("c"))
        .where(RagQueryTrace.query.isnot(None), RagQueryTrace.query != "")
        .group_by(RagQueryTrace.query)
        .order_by(text("c DESC"))
        .limit(10)
    )).all()

    return StatsResponse(
        total=total, ok=ok, error=err,
        success_rate=round(ok / total, 4) if total else None,
        total_ms=await _latency(session, RagQueryTrace.total_ms),
        embedding_ms=await _latency(session, RagQueryTrace.embedding_ms),
        search_ms=await _latency(session, RagQueryTrace.search_ms),
        retrieval_ms=await _latency(session, RagQueryTrace.retrieval_ms),
        rerank_ms=await _latency(session, RagQueryTrace.rerank_ms),
        generation_ms=await _latency(session, RagQueryTrace.generation_ms),
        prompt_tokens=int(pt), completion_tokens=int(ct),
        top_queries=[TopQuery(query=q, count=c) for q, c in top_rows],
    )
