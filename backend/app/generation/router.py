# SPDX-License-Identifier: Apache-2.0
"""검색·생성·챗 API (M3) + 파이프라인 적용 + 질의 트레이스 계측(운영).

- POST /collections/{id}/search  하이브리드 검색(청크+점수)
- POST /collections/{id}/query   검색 → (리랭크) → 인용 포함 답변 생성(비스트리밍)
- POST /collections/{id}/chat    멀티턴 챗 — SSE 스트리밍(토큰 + 출처)

요청에 ``pipeline_id`` 가 있으면 해당 파이프라인 활성 버전 설정을 적용한다(검색 파라미터·
리랭크·생성 모델/토큰). 각 호출은 단계별 지연·토큰·상태를 ``rag_query_traces`` 에 기록한다.
"""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections.models import RagCollection
from app.core.auth import CurrentUser
from app.core.database import async_session, get_session
from app.generation import service as gen
from app.generation.schemas import (
    ChatRequest,
    FederatedQueryResponse,
    QueryRequest,
    QueryResponse,
)
from app.llm import service as llm
from app.observability.service import record_trace
from app.pipelines.service import resolve_config
from app.rerank.service import rerank
from app.retrieval import service as retrieval
from app.retrieval.filterspec import UnknownFilterField, validate_fields
from app.retrieval.schemas import (
    CollectionContribution,
    FederatedSearchRequest,
    FederatedSearchResponse,
    SearchRequest,
    SearchResponse,
)

logger = logging.getLogger(__name__)

# 페더레이션에서 rerank=true 일 때, 병합 후보를 이만큼 모아 cross-encoder 로 재정렬한 뒤 top_k 로 자른다.
_FED_RERANK_POOL = 50

router = APIRouter(tags=["search-generation"])


def _ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 1)


async def _get_collection(session: AsyncSession, collection_id: int) -> RagCollection:
    collection = (await session.execute(
        select(RagCollection).where(RagCollection.id == collection_id)
    )).scalars().first()
    if not collection:
        raise HTTPException(status_code=404, detail="컬렉션을 찾을 수 없습니다.")
    return collection


async def _resolve_plan(
    session: AsyncSession, *, mode: str, top_k: int | None, rerank: bool, pipeline_id: int | None,
    collection_rerank_provider: str = "none", collection_rerank_model: str | None = None,
) -> dict:
    """파이프라인이 지정되면 활성 버전 설정을, 아니면 요청 필드를 실행 계획으로 만든다.

    파이프라인 미지정 시 리랭커는 컬렉션 기본값(``collection_rerank_provider``)을 사용한다.
    컬렉션에 리랭커가 설정돼 있으면(none 아님) 기본 적용하고, 요청 rerank 플래그로도 켤 수 있다.
    """
    cfg = await resolve_config(session, pipeline_id) if pipeline_id else None
    if cfg:
        r = cfg.retrieval
        return {
            "mode": r.mode.value, "top_k": r.top_k, "vector_k": r.vector_k,
            "lexical_k": r.lexical_k, "rrf_k": r.rrf_k, "metric": r.distance_metric or None,
            "rerank": cfg.rerank.enabled, "rerank_provider": cfg.rerank.provider,
            "rerank_top_n": cfg.rerank.top_n, "rerank_model": None,
            "gen_overrides": {
                "model": cfg.generation.model or None,
                "max_tokens": cfg.generation.max_tokens,
                "temperature": cfg.generation.temperature,
            },
        }
    crp = (collection_rerank_provider or "none").lower()
    return {
        "mode": mode, "top_k": top_k, "vector_k": None, "lexical_k": None, "rrf_k": None,
        "metric": None,
        "rerank": rerank or crp != "none",
        "rerank_provider": (crp if crp != "none" else None),
        "rerank_model": collection_rerank_model or None,
        "rerank_top_n": top_k, "gen_overrides": None,
    }


def _validate_filters(filters):
    """비-보안 메타데이터 필터의 필드를 사전 검증 — 미등록 필드면 400(fail-closed)."""
    if not filters:
        return
    try:
        validate_fields(filters)
    except UnknownFilterField as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _retrieve(session, collection, query, plan, filters=None):
    """검색(+리랭크)을 수행하고 (hits, timings) 를 반환한다.

    timings(ms): embedding_ms · search_ms(검색 세부) · rerank_ms(리랭크 사용 시).
    """
    timings: dict[str, float] = {}
    hits = await retrieval.search(
        session, collection, query, plan["mode"], plan["top_k"],
        vector_k=plan["vector_k"], lexical_k=plan["lexical_k"], rrf_k=plan["rrf_k"],
        distance_metric=plan["metric"], filters=filters, timings=timings,
    )
    if plan["rerank"]:
        t0 = time.monotonic()
        hits = await rerank(
            query, hits, plan["rerank_top_n"],
            provider=plan["rerank_provider"], model=plan.get("rerank_model"),
        )
        timings["rerank_ms"] = (time.monotonic() - t0) * 1000
    return hits, timings


@router.post("/collections/{collection_id}/search", response_model=SearchResponse)
async def search(
    collection_id: int, req: SearchRequest, user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    """하이브리드/벡터/렉시컬 검색. pipeline_id 또는 요청 필드로 검색 방식을 결정."""
    collection = await _get_collection(session, collection_id)
    _validate_filters(req.filters)
    plan = await _resolve_plan(
        session, mode=req.mode.value, top_k=req.top_k, rerank=req.rerank, pipeline_id=req.pipeline_id,
        collection_rerank_provider=collection.rerank_provider,
        collection_rerank_model=collection.rerank_model,
    )
    t0 = time.monotonic()
    try:
        hits, tm = await _retrieve(session, collection, req.query, plan, filters=req.filters)
    except Exception as e:
        await record_trace(
            kind="search", collection_id=collection_id, query=req.query, mode=plan["mode"], distance_metric=(plan["metric"] or collection.distance_metric),
            rerank=plan["rerank"], status="error", error=str(e), hit_count=0,
            retrieval_ms=None, rerank_ms=None, generation_ms=None, total_ms=_ms(t0),
            prompt_tokens=None, completion_tokens=None, answer=None, created_by=user.username,
        )
        raise HTTPException(status_code=502, detail=f"검색 실패: {e}")
    total = _ms(t0)
    await record_trace(
        kind="search", collection_id=collection_id, query=req.query, mode=plan["mode"], distance_metric=(plan["metric"] or collection.distance_metric),
        rerank=plan["rerank"], status="ok", error=None, hit_count=len(hits),
        embedding_ms=tm.get("embedding_ms"), search_ms=tm.get("search_ms"),
        retrieval_ms=tm.get("embedding_ms", 0) + tm.get("search_ms", 0), rerank_ms=tm.get("rerank_ms"),
        generation_ms=None, total_ms=total,
        prompt_tokens=None, completion_tokens=None, answer=None, created_by=user.username,
    )
    return SearchResponse(
        query=req.query, mode=plan["mode"], reranked=plan["rerank"],
        distance_metric=(plan["metric"] or collection.distance_metric), hits=hits,
        filters_applied=req.filters or [],
    )


async def _run_federation(session: AsyncSession, req: FederatedSearchRequest):
    """페더레이션 검색 공통 코어 — search/query 가 공유한다.

    각 컬렉션을 자기 임베딩 모델로 독립 검색(이종 벡터 공간 허용) → 순위 기반 RRF 병합 →
    (선택) 글로벌 cross-encoder 재정렬. 컬렉션별 검색은 동시 실행하며, 일부 실패해도 나머지로
    진행하고 실패는 contributions 에 기록한다.

    반환: (merged_hits, contributions, reranked, gen_overrides)
    """
    _validate_filters(req.filters)
    # 1) 대상 컬렉션 로드(중복 제거, 요청 순서 유지)
    collections: list[RagCollection] = []
    for cid in dict.fromkeys(req.collection_ids):
        c = (await session.execute(
            select(RagCollection).where(RagCollection.id == cid)
        )).scalars().first()
        if c:
            collections.append(c)
    if not collections:
        raise HTTPException(status_code=404, detail="유효한 컬렉션이 없습니다.")

    # 파이프라인 지정 시 모든 컬렉션에 동일 검색/생성 설정 적용(미지정이면 요청 필드)
    cfg = await resolve_config(session, req.pipeline_id) if req.pipeline_id else None

    async def _search_one(c: RagCollection):
        if cfg:
            r = cfg.retrieval
            return await retrieval.search(
                session, c, req.query, r.mode.value, req.per_collection_k,
                vector_k=r.vector_k, lexical_k=r.lexical_k, rrf_k=r.rrf_k,
                distance_metric=r.distance_metric or None, filters=req.filters,
            )
        return await retrieval.search(
            session, c, req.query, req.mode.value, req.per_collection_k, filters=req.filters
        )

    # 2) 컬렉션별 검색을 동시에(장애 격리 — 한 곳이 죽어도 전체는 진행)
    results = await asyncio.gather(*[_search_one(c) for c in collections], return_exceptions=True)

    ranked_lists: list[list] = []
    contributions: list[CollectionContribution] = []
    for c, res in zip(collections, results):
        if isinstance(res, Exception):
            logger.warning("페더레이션 검색 실패(collection=%s): %s", c.id, res)
            contributions.append(CollectionContribution(
                collection_id=c.id, name=c.name, embedding_model=c.embedding_model,
                candidates=0, in_final=0, status="error", error=str(res)[:200],
            ))
        else:
            ranked_lists.append(res)
            contributions.append(CollectionContribution(
                collection_id=c.id, name=c.name, embedding_model=c.embedding_model,
                candidates=len(res), in_final=0, status="ok",
            ))

    # 3) 컬렉션 간 RRF 병합. rerank 시 더 넓은 후보 풀을 모은 뒤 재정렬해서 자른다.
    merge_k = max(req.top_k, _FED_RERANK_POOL) if req.rerank else req.top_k
    merged = retrieval.rrf_merge(ranked_lists, req.rrf_k, merge_k)

    # 4) (선택) 글로벌 cross-encoder 재정렬 — 임베딩 공간과 무관하게 컬렉션 경계를 넘어 정렬
    reranked = False
    if req.rerank and merged:
        merged = await rerank(req.query, merged, req.top_k, provider="cross_encoder")
        reranked = True
    else:
        merged = merged[: req.top_k]

    # 5) 최종에 살아남은 컬렉션별 건수 집계
    final_counts: dict[int, int] = {}
    for h in merged:
        final_counts[h.collection_id] = final_counts.get(h.collection_id, 0) + 1
    for con in contributions:
        con.in_final = final_counts.get(con.collection_id, 0)

    gen_overrides = None
    if cfg:
        gen_overrides = {
            "model": cfg.generation.model or None,
            "max_tokens": cfg.generation.max_tokens,
            "temperature": cfg.generation.temperature,
        }
    return merged, contributions, reranked, gen_overrides


@router.post("/search/federated", response_model=FederatedSearchResponse)
async def federated_search(
    req: FederatedSearchRequest, user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    """여러 컬렉션을 한 번에 검색 → 순위 기반 RRF 병합 → (선택) 글로벌 cross-encoder 재정렬."""
    merged, contributions, reranked, _ = await _run_federation(session, req)
    return FederatedSearchResponse(
        query=req.query, mode=req.mode.value, reranked=reranked,
        top_k=req.top_k, hits=merged, contributions=contributions,
    )


@router.post("/query/federated", response_model=FederatedQueryResponse)
async def federated_query(
    req: FederatedSearchRequest, user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    """여러 컬렉션 페더레이션 검색 → 병합 결과로 인용 포함 답변 생성(비스트리밍).

    여러 지식베이스에 흩어진 근거를 한 답변으로 종합한다. 검색은 ``/search/federated`` 와 동일.
    """
    merged, contributions, reranked, gen_overrides = await _run_federation(session, req)
    messages = gen.build_messages(merged, [{"role": "user", "content": req.query}])
    try:
        answer, _usage = await llm.complete_with_usage(messages, overrides=gen_overrides)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"답변 생성 실패(LLM 설정 확인): {e}")
    citations = gen.extract_citations(answer, merged)
    return FederatedQueryResponse(
        answer=answer, citations=citations, hits=merged,
        contributions=contributions, reranked=reranked,
    )


@router.post("/collections/{collection_id}/query", response_model=QueryResponse)
async def query(
    collection_id: int, req: QueryRequest, user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    """단일 질의 → 검색 → (리랭크) → 인용 포함 답변 생성(비스트리밍)."""
    collection = await _get_collection(session, collection_id)
    _validate_filters(req.filters)
    plan = await _resolve_plan(
        session, mode=req.mode.value, top_k=req.top_k, rerank=req.rerank, pipeline_id=req.pipeline_id,
        collection_rerank_provider=collection.rerank_provider,
        collection_rerank_model=collection.rerank_model,
    )
    t0 = time.monotonic()
    generation_ms = None
    tm: dict[str, float] = {}
    hits = []
    try:
        hits, tm = await _retrieve(session, collection, req.query, plan, filters=req.filters)
        messages = gen.build_messages(hits, [{"role": "user", "content": req.query}])
        t2 = time.monotonic()
        answer, usage = await llm.complete_with_usage(messages, overrides=plan["gen_overrides"])
        generation_ms = _ms(t2)
    except Exception as e:
        await record_trace(
            kind="query", collection_id=collection_id, query=req.query, mode=plan["mode"], distance_metric=(plan["metric"] or collection.distance_metric),
            rerank=plan["rerank"], status="error", error=str(e), hit_count=len(hits),
            embedding_ms=tm.get("embedding_ms"), search_ms=tm.get("search_ms"),
            retrieval_ms=(tm.get("embedding_ms", 0) + tm.get("search_ms", 0)) or None, rerank_ms=tm.get("rerank_ms"),
            generation_ms=generation_ms, total_ms=_ms(t0),
            prompt_tokens=None, completion_tokens=None, answer=None, created_by=user.username,
        )
        raise HTTPException(status_code=502, detail=f"답변 생성 실패(LLM 설정 확인): {e}")
    citations = gen.extract_citations(answer, hits)
    trace_id = await record_trace(
        kind="query", collection_id=collection_id, query=req.query, mode=plan["mode"], distance_metric=(plan["metric"] or collection.distance_metric),
        rerank=plan["rerank"], status="ok", error=None, hit_count=len(hits),
        embedding_ms=tm.get("embedding_ms"), search_ms=tm.get("search_ms"),
        retrieval_ms=tm.get("embedding_ms", 0) + tm.get("search_ms", 0), rerank_ms=tm.get("rerank_ms"),
        generation_ms=generation_ms, total_ms=_ms(t0),
        prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
        answer=answer, created_by=user.username,
    )
    return QueryResponse(answer=answer, citations=citations, hits=hits, trace_id=trace_id)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/collections/{collection_id}/chat")
async def chat(collection_id: int, req: ChatRequest, user: CurrentUser):
    """멀티턴 챗 — SSE 스트리밍. 마지막 user 메시지로 검색 후 답변을 토큰 단위로 흘린다."""
    history = [{"role": m.role, "content": m.content} for m in req.messages]
    last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), None)
    if not last_user:
        raise HTTPException(status_code=400, detail="마지막 사용자 메시지가 필요합니다.")
    base_mode, base_top_k, base_rerank, pipeline_id, username = (
        req.mode.value, req.top_k, req.rerank, req.pipeline_id, user.username
    )

    async def gen_stream():
        t0 = time.monotonic()
        generation_ms = None
        tm: dict[str, float] = {}
        hit_count = 0
        async with async_session() as session:
            collection = (await session.execute(
                select(RagCollection).where(RagCollection.id == collection_id)
            )).scalars().first()
            if not collection:
                yield _sse({"type": "error", "detail": "컬렉션을 찾을 수 없습니다."})
                return
            plan = await _resolve_plan(
                session, mode=base_mode, top_k=base_top_k, rerank=base_rerank, pipeline_id=pipeline_id,
                collection_rerank_provider=collection.rerank_provider,
        collection_rerank_model=collection.rerank_model,
            )
            metric = plan["metric"] or collection.distance_metric
            try:
                hits, tm = await _retrieve(session, collection, last_user, plan)
                hit_count = len(hits)
            except Exception as e:
                await record_trace(
                    kind="chat", collection_id=collection_id, query=last_user, mode=plan["mode"], distance_metric=metric,
                    rerank=plan["rerank"], status="error", error=str(e), hit_count=0,
                    embedding_ms=tm.get("embedding_ms"), search_ms=tm.get("search_ms"),
                    retrieval_ms=(tm.get("embedding_ms", 0) + tm.get("search_ms", 0)) or None, rerank_ms=tm.get("rerank_ms"),
                    generation_ms=None, total_ms=_ms(t0),
                    prompt_tokens=None, completion_tokens=None, answer=None, created_by=username,
                )
                yield _sse({"type": "error", "detail": f"검색 실패: {e}"})
                return

        yield _sse({
            "type": "hits", "hits": [h.model_dump() for h in hits],
            "mode": plan["mode"], "distance_metric": metric,
        })

        messages = gen.build_messages(hits, history)
        full = []
        t2 = time.monotonic()
        try:
            async for token in llm.stream(messages, overrides=plan["gen_overrides"]):
                full.append(token)
                yield _sse({"type": "token", "text": token})
        except Exception as e:
            generation_ms = _ms(t2)
            await record_trace(
                kind="chat", collection_id=collection_id, query=last_user, mode=plan["mode"], distance_metric=metric,
                rerank=plan["rerank"], status="error", error=str(e), hit_count=hit_count,
                embedding_ms=tm.get("embedding_ms"), search_ms=tm.get("search_ms"),
                retrieval_ms=tm.get("embedding_ms", 0) + tm.get("search_ms", 0), rerank_ms=tm.get("rerank_ms"),
                generation_ms=generation_ms, total_ms=_ms(t0),
                prompt_tokens=None, completion_tokens=None, answer=None, created_by=username,
            )
            yield _sse({"type": "error", "detail": f"답변 생성 실패(LLM 설정 확인): {e}"})
            return

        generation_ms = _ms(t2)
        answer = "".join(full)
        citations = gen.extract_citations(answer, hits)
        yield _sse({"type": "citations", "citations": [c.model_dump() for c in citations]})
        trace_id = await record_trace(
            kind="chat", collection_id=collection_id, query=last_user, mode=plan["mode"], distance_metric=metric,
            rerank=plan["rerank"], status="ok", error=None, hit_count=hit_count,
            embedding_ms=tm.get("embedding_ms"), search_ms=tm.get("search_ms"),
            retrieval_ms=tm.get("embedding_ms", 0) + tm.get("search_ms", 0), rerank_ms=tm.get("rerank_ms"),
            generation_ms=generation_ms, total_ms=_ms(t0),
            prompt_tokens=None, completion_tokens=None, answer=answer, created_by=username,
        )
        yield _sse({"type": "done", "trace_id": trace_id, "query": last_user})

    return StreamingResponse(gen_stream(), media_type="text/event-stream")
