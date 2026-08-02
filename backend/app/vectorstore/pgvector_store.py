# SPDX-License-Identifier: Apache-2.0
"""PgVectorStore — pgvector 백엔드 어댑터.

벡터는 ``rag_chunks.embedding`` 컬럼(정본)에 저장된다. pgvector 에서는 "벡터 스토어"와
"기본 DB"가 같으므로:
  - 벡터 쓰기/삭제는 인제스천 파이프라인이 청크 행과 함께 관리한다 → upsert/delete 는 no-op.
  - 검색만 이 어댑터가 pgvector 거리 연산자로 수행한다.

외부 스토어(Qdrant 등) 어댑터는 upsert/delete/ensure 를 실제 구현으로 오버라이드한다.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunks.models import RagChunk
from app.documents.models import RagDocument
from app.vectorstore.base import CollectionSpec, VectorHit, VectorItem

logger = logging.getLogger(__name__)


def _distance_expr(query_vec: list[float], metric: str):
    """컬렉션 거리 메트릭 → pgvector 거리식. 모든 연산자는 '작을수록 가까움'(거리)을 반환한다."""
    col = RagChunk.embedding
    m = (metric or "cosine").lower()
    if m == "l2":
        return col.l2_distance(query_vec)
    if m == "inner_product":
        return col.max_inner_product(query_vec)
    return col.cosine_distance(query_vec)


def _to_score(metric: str, dist: float) -> float:
    """거리 → '클수록 유사' 점수로 정규화.
      - cosine: 1-거리, l2: 1/(1+거리), inner_product: <#> 는 -(a·b) → -거리.
    """
    m = (metric or "cosine").lower()
    d = float(dist)
    if m == "l2":
        return 1.0 / (1.0 + d)
    if m == "inner_product":
        return -d
    return 1.0 - d


class PgVectorStore:
    """벡터 정본이 PostgreSQL 인 경우의 어댑터(no-op 쓰기 + pgvector 검색)."""

    async def ensure_collection(self, session: AsyncSession, spec: CollectionSpec) -> None:
        return  # 공유 Vector 컬럼 — 별도 생성 불필요

    async def drop_collection(self, session: AsyncSession, collection_id: int) -> None:
        return  # 컬렉션 삭제 시 청크 FK CASCADE 로 벡터도 제거됨

    async def upsert(
        self, session: AsyncSession, collection_id: int, items: list[VectorItem]
    ) -> None:
        return  # 임베딩은 인제스천이 청크 행에 함께 INSERT(정본). pgvector 는 별도 업서트 불필요.

    async def delete_by_document(
        self, session: AsyncSession, collection_id: int, document_id: int
    ) -> None:
        return  # 청크 행 삭제(인제스천)로 임베딩도 제거됨

    async def search(
        self,
        session: AsyncSession,
        spec: CollectionSpec,
        query_vec: list[float],
        k: int,
        filters: dict | None = None,
        *,
        where=None,
    ) -> list[VectorHit]:
        """pgvector ANN 검색 — 인덱싱된 문서의 청크만, 거리 ASC 상위 k.

        ``where`` (메타데이터 필터 WHERE 절)가 있으면 ANN 쿼리에 push-down 한다 — 벡터 거리와
        메타데이터 필터가 한 SQL 에서 평가돼 정확히 상위 k 를 만족 문서에서만 뽑는다(top-k 보존).
        이미 ``RagDocument`` 를 JOIN 하므로(status 필터) 추가 비용은 WHERE 절뿐이다.
        """
        dist = _distance_expr(query_vec, spec.metric).label("dist")
        stmt = (
            select(RagChunk.chunk_id, dist)
            .join(RagDocument, RagChunk.document_id == RagDocument.id)
            .where(
                RagChunk.collection_id == spec.collection_id,
                RagChunk.embedding.isnot(None),
                RagDocument.status == "indexed",
            )
        )
        if where is not None:
            stmt = stmt.where(where)
        rows = (await session.execute(stmt.order_by(dist).limit(k))).all()
        return [VectorHit(chunk_id=cid, score=_to_score(spec.metric, d)) for cid, d in rows]
