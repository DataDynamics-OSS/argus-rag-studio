# SPDX-License-Identifier: Apache-2.0
"""VectorStore 인터페이스 + 값 객체.

검색은 (chunk_id, score) 만 반환한다 — 청크 본문·문서명은 호출부(retrieval)가 PostgreSQL 에서
hydrate 한다. 따라서 어떤 백엔드(pgvector/qdrant)든 결과 형태가 동일하다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class VectorItem:
    """업서트 단위 — 청크 UUID(포인트 ID) + 벡터 + 필터용 payload."""

    chunk_id: str
    vector: list[float]
    payload: dict = field(default_factory=dict)  # {document_id, status, acl_tags?, seq, ...}


@dataclass
class VectorHit:
    """검색 결과 — 청크 UUID + 점수(클수록 유사, 메트릭 정규화는 어댑터 책임)."""

    chunk_id: str
    score: float


@dataclass
class CollectionSpec:
    """벡터 공간 정의 — 컬렉션 내부 PK + 차원 + 거리 메트릭."""

    collection_id: int
    dim: int
    metric: str = "cosine"  # cosine | l2 | inner_product


@runtime_checkable
class VectorStore(Protocol):
    """벡터 저장/검색 백엔드. session 은 pgvector 어댑터가 사용하고, 외부 스토어는 무시한다."""

    async def ensure_collection(self, session: AsyncSession, spec: CollectionSpec) -> None:
        """벡터 컬렉션을 (없으면) 생성/구성한다. pgvector 는 공유 컬럼이라 no-op."""

    async def drop_collection(self, session: AsyncSession, collection_id: int) -> None:
        """컬렉션의 벡터를 제거한다. pgvector 는 청크 FK CASCADE 로 처리되어 no-op."""

    async def upsert(
        self, session: AsyncSession, collection_id: int, items: list[VectorItem]
    ) -> None:
        """벡터를 업서트한다."""

    async def delete_by_document(
        self, session: AsyncSession, collection_id: int, document_id: int
    ) -> None:
        """문서에 속한 벡터를 제거한다."""

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
        """질의 벡터로 ANN 검색 → (chunk_id, score) 상위 k.

        ``filters`` 는 페이로드 동등 매칭(백엔드별 번역). ``where`` 는 SQLAlchemy WHERE 절로,
        SQL 기반 백엔드(pgvector)만 적용한다(문서 메타데이터 필터 push-down). 외부 스토어는
        ``where`` 를 무시하고, 호출부(``_vector_rank``)의 하이드레이션 단계가 동일 필터를 강제한다.
        """
        ...
