# SPDX-License-Identifier: Apache-2.0
"""검색 서비스 — 벡터(pgvector) + 렉시컬(tsvector) + 하이브리드(RRF).

- vector_search: 쿼리 임베딩과 청크 임베딩의 코사인 거리 ANN 정렬
- lexical_search: tsvector @@ plainto_tsquery + ts_rank
- hybrid_search: 두 결과의 순위를 RRF(Reciprocal Rank Fusion)로 융합

컬렉션 단위로 필터링하며, 인덱싱된 문서(rag_documents.status='indexed')의 청크만 대상으로 한다.
"""

import json
import logging
import time

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunks.models import RagChunk
from app.collections.models import RagCollection
from app.core.config import settings
from app.documents.models import RagDocument
from app.embedding.service import embed_for_collection
from app.retrieval.filterspec import build_where
from app.retrieval.schemas import ChunkHit, FilterCond
from app.vectorstore import CollectionSpec, get_vector_store

logger = logging.getLogger(__name__)


def _image_refs_from_chunk(metadata_json: str | None) -> list[dict]:
    """청크 metadata_json 에서 연결된 이미지 참조 목록을 꺼낸다(없으면 빈 리스트).

    인제스천이 ``image_refs`` 로 저장한 [{index, page, type, summary}] 형태다. 파싱 오류는
    빈 리스트로 처리해 검색을 막지 않는다.
    """
    if not metadata_json:
        return []
    try:
        meta = json.loads(metadata_json)
    except (ValueError, TypeError):
        return []
    refs = meta.get("image_refs") if isinstance(meta, dict) else None
    return refs if isinstance(refs, list) else []


def _hit_from_row(chunk: RagChunk, document_name: str, score: float) -> ChunkHit:
    return ChunkHit(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        document_name=document_name,
        collection_id=chunk.collection_id,
        seq=chunk.seq,
        text=chunk.text,
        score=round(float(score), 6),
        section_path=chunk.section_path,
        image_refs=_image_refs_from_chunk(chunk.metadata_json),
    )


def _image_types_from_metadata(metadata_json: str | None) -> dict[str, int]:
    """문서 metadata_json 에서 이미지 분류 요약(유형→개수)을 꺼낸다(없으면 빈 dict).

    인제스천의 이미지 분류가 ``image_classification.counts_by_type`` 로 저장한 형태다.
    파싱/형식 오류는 빈 dict 로 처리해 검색을 막지 않는다.
    """
    if not metadata_json:
        return {}
    try:
        meta = json.loads(metadata_json)
    except (ValueError, TypeError):
        return {}
    clf = meta.get("image_classification") if isinstance(meta, dict) else None
    counts = clf.get("counts_by_type") if isinstance(clf, dict) else None
    if not isinstance(counts, dict):
        return {}
    # 값이 정수인 항목만 보존(방어적).
    return {str(k): int(v) for k, v in counts.items() if isinstance(v, (int, float))}


async def _attach_uuids(session: AsyncSession, hits: list[ChunkHit]) -> list[ChunkHit]:
    """ChunkHit.document_id(int PK) → 문서 UUID + 이미지 분류 요약을 채운다.

    프런트가 검색 결과에서 '문서 전체 보기'를 열 때 UUID 가 필요하고, 문서에 포함된 이미지
    유형(도표/차트 등)을 결과에 함께 표시한다. 최종 hit 리스트에 한 번의 쿼리로 매핑하므로
    모드(벡터/렉시컬/하이브리드)·리랭크·페더레이션 모두 자동 적용된다.
    """
    if not hits:
        return hits
    ids = {h.document_id for h in hits}
    rows = (await session.execute(
        select(RagDocument.id, RagDocument.document_id, RagDocument.metadata_json)
        .where(RagDocument.id.in_(ids))
    )).all()
    uuid_by_id = {rid: uuid for rid, uuid, _meta in rows}
    types_by_id = {rid: _image_types_from_metadata(meta) for rid, _uuid, meta in rows}
    for h in hits:
        h.document_uuid = uuid_by_id.get(h.document_id, "")
        h.document_image_types = types_by_id.get(h.document_id, {})
    return hits


async def _vector_rank(
    session: AsyncSession, collection_id: int, dim: int, query_vec: list[float], k: int,
    metric: str = "cosine", where=None,
) -> list[tuple[RagChunk, str, float]]:
    """벡터 ANN 검색 — VectorStore 경유로 (chunk_id, score) 를 받고 Postgres 에서 hydrate.

    검색 백엔드(pgvector/qdrant)는 get_vector_store() 로 추상화. 청크 본문·문서명은 정본인
    Postgres 에서 가져와 모든 백엔드가 동일한 결과 형태를 갖는다.

    ``where`` (메타데이터 필터 WHERE 절)가 있으면:
      - pgvector 는 스토어 ANN 쿼리에서 push-down(정확 필터, top-k 보존).
      - 외부 스토어는 push-down 을 못 하므로, 아래 하이드레이션 쿼리의 WHERE 가 보편 enforcement
        역할을 한다(비대상 문서를 절대 더 반환하지 않음 = fail-open 아님). pgvector 는 이미
        걸러져 멱등.
    """
    spec = CollectionSpec(collection_id=collection_id, dim=dim, metric=metric)
    hits = await get_vector_store().search(session, spec, query_vec, k, where=where)
    if not hits:
        return []
    score_by_id = {h.chunk_id: h.score for h in hits}
    stmt = (
        select(RagChunk, RagDocument.name)
        .join(RagDocument, RagChunk.document_id == RagDocument.id)
        .where(RagChunk.chunk_id.in_(list(score_by_id.keys())))
    )
    if where is not None:
        stmt = stmt.where(where)  # 하이드레이션 플로어 — 외부 스토어 enforcement(pgvector 는 멱등)
    rows = (await session.execute(stmt)).all()
    by_id = {chunk.chunk_id: (chunk, name) for chunk, name in rows}
    # 검색 순서를 보존하며 점수를 매핑
    out: list[tuple[RagChunk, str, float]] = []
    for h in hits:
        cn = by_id.get(h.chunk_id)
        if cn:
            out.append((cn[0], cn[1], h.score))
    return out


async def _lexical_rank(
    session: AsyncSession, collection_id: int, query: str, k: int, where=None
) -> list[tuple[RagChunk, str, float]]:
    """렉시컬(FTS) 검색 — ts_rank 점수 내림차순. ``where`` 가 있으면 메타데이터 필터를 적용(정확)."""
    tsq = func.plainto_tsquery("simple", query)
    rank = func.ts_rank(RagChunk.tsv, tsq).label("rank")
    stmt = (
        select(RagChunk, RagDocument.name, rank)
        .join(RagDocument, RagChunk.document_id == RagDocument.id)
        .where(
            RagChunk.collection_id == collection_id,
            RagChunk.tsv.op("@@")(tsq),
            RagDocument.status == "indexed",
        )
    )
    if where is not None:
        stmt = stmt.where(where)
    rows = (await session.execute(
        stmt.order_by(desc("rank")).limit(k)
    )).all()
    return [(chunk, name, float(r)) for chunk, name, r in rows]


def _rrf_fuse(
    ranked_lists: list[list[tuple[RagChunk, str, float]]], rrf_k: int, top_k: int
) -> list[ChunkHit]:
    """여러 순위 리스트를 RRF 로 융합한다. score = Σ 1/(rrf_k + rank)."""
    fused: dict[str, dict] = {}
    for ranked in ranked_lists:
        for rank, (chunk, name, _raw) in enumerate(ranked):
            entry = fused.setdefault(
                chunk.chunk_id, {"chunk": chunk, "name": name, "score": 0.0}
            )
            entry["score"] += 1.0 / (rrf_k + rank + 1)
    ordered = sorted(fused.values(), key=lambda e: e["score"], reverse=True)[:top_k]
    return [_hit_from_row(e["chunk"], e["name"], e["score"]) for e in ordered]


def rrf_merge(ranked_lists: list[list[ChunkHit]], rrf_k: int, top_k: int) -> list[ChunkHit]:
    """여러 컬렉션의 순위 리스트(이미 컬렉션 내부 검색을 마친 ChunkHit)를 RRF 로 병합한다.

    컬렉션마다 임베딩 모델·점수 스케일이 달라 raw 점수를 직접 비교할 수 없으므로, **순위**
    기반(score = Σ 1/(rrf_k + rank))으로 정규화해 공정 비교한다. ``chunk_id`` 로 식별하며
    (컬렉션 간 중복은 없으나) 동일 청크가 여러 리스트에 있으면 점수가 누적된다.
    반환 ChunkHit 의 ``score`` 는 융합된 RRF 점수로 갱신한다.
    """
    fused: dict[str, dict] = {}
    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked):
            entry = fused.setdefault(hit.chunk_id, {"hit": hit, "score": 0.0})
            entry["score"] += 1.0 / (rrf_k + rank + 1)
    ordered = sorted(fused.values(), key=lambda e: e["score"], reverse=True)[:top_k]
    return [e["hit"].model_copy(update={"score": round(e["score"], 6)}) for e in ordered]


async def search(
    session: AsyncSession,
    collection: RagCollection,
    query: str,
    mode: str = "hybrid",
    top_k: int | None = None,
    *,
    vector_k: int | None = None,
    lexical_k: int | None = None,
    rrf_k: int | None = None,
    distance_metric: str | None = None,
    filters: list[FilterCond] | None = None,
    timings: dict[str, float] | None = None,
) -> list[ChunkHit]:
    """컬렉션에서 질의에 대한 청크를 검색한다(모드별 벡터/렉시컬/하이브리드).

    vector_k/lexical_k/rrf_k 미지정 시 전역 설정값을 사용한다(파이프라인이 override 가능).
    distance_metric 을 주면 컬렉션 기본 메트릭 대신 사용한다(파이프라인 실험용 override).
    filters 가 있으면 비-보안 메타데이터(문서유형·부서·기간 등)로 결과를 좁힌다. 미등록 필드는
    ``UnknownFilterField``(라우터에서 400). 보안 격리에는 절대 쓰지 않는다(컬렉션 경계가 담당).
    timings 딕셔너리를 주면 단계별 지연(ms)을 채운다: embedding_ms(쿼리 임베딩) · search_ms(검색·융합).
    """
    top_k = top_k or settings.retrieval_top_k
    vector_k = vector_k or settings.retrieval_vector_k
    lexical_k = lexical_k or settings.retrieval_lexical_k
    rrf_k = rrf_k or settings.retrieval_rrf_k
    where = build_where(filters)  # 세 검색 경로가 공유하는 WHERE 절(없으면 None)

    def _mark(key: str, t0: float) -> None:
        if timings is not None:
            timings[key] = timings.get(key, 0.0) + (time.monotonic() - t0) * 1000

    if mode == "lexical":
        t0 = time.monotonic()
        ranked = await _lexical_rank(session, collection.id, query, lexical_k, where)
        _mark("search_ms", t0)
        return await _attach_uuids(session, [_hit_from_row(c, n, s) for c, n, s in ranked[:top_k]])

    # 벡터/하이브리드는 쿼리 임베딩이 필요(instruction-aware 모델의 쿼리 전처리 적용)
    t_embed = time.monotonic()
    query_vec = (await embed_for_collection([query], collection, is_query=True))[0]
    _mark("embedding_ms", t_embed)
    metric = distance_metric or collection.distance_metric

    if mode == "vector":
        t0 = time.monotonic()
        ranked = await _vector_rank(session, collection.id, collection.embedding_dim, query_vec, vector_k, metric, where)
        _mark("search_ms", t0)
        return await _attach_uuids(session, [_hit_from_row(c, n, s) for c, n, s in ranked[:top_k]])

    # hybrid — 벡터 + 렉시컬 RRF 융합
    t0 = time.monotonic()
    vec = await _vector_rank(session, collection.id, collection.embedding_dim, query_vec, vector_k, metric, where)
    lex = await _lexical_rank(session, collection.id, query, lexical_k, where)
    fused = _rrf_fuse([vec, lex], rrf_k, top_k)
    _mark("search_ms", t0)
    return await _attach_uuids(session, fused)
