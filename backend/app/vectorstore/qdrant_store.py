# SPDX-License-Identifier: Apache-2.0
"""QdrantStore — Qdrant 벡터DB 어댑터.

요구: ``pip install qdrant-client`` + 가동 중인 Qdrant 서버.
컬렉션은 Argus 컬렉션별로 1:1(``{prefix}_c{id}``) — dim/metric 을 컬렉션마다 독립 설정.
포인트 ID = 청크 UUID(chunk_id). payload 에 document_id/status 를 넣어 필터링.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.vectorstore.base import CollectionSpec, VectorHit, VectorItem

logger = logging.getLogger(__name__)


class QdrantStore:
    def __init__(self, url: str, api_key: str | None, prefix: str):
        if not url:
            raise ValueError("Qdrant URL(vector_store_url)이 설정되지 않았습니다.")
        from qdrant_client import AsyncQdrantClient  # lazy
        self._client = AsyncQdrantClient(url=url, api_key=api_key)
        self._prefix = prefix

    def _name(self, collection_id: int) -> str:
        return f"{self._prefix}_c{collection_id}"

    def _distance(self, metric: str):
        from qdrant_client.models import Distance
        return {"l2": Distance.EUCLID, "inner_product": Distance.DOT}.get(
            (metric or "cosine").lower(), Distance.COSINE
        )

    async def ensure_collection(self, session: AsyncSession, spec: CollectionSpec) -> None:
        from qdrant_client.models import VectorParams
        name = self._name(spec.collection_id)
        if not await self._client.collection_exists(name):
            await self._client.create_collection(
                name, vectors_config=VectorParams(size=spec.dim, distance=self._distance(spec.metric))
            )

    async def drop_collection(self, session: AsyncSession, collection_id: int) -> None:
        name = self._name(collection_id)
        if await self._client.collection_exists(name):
            await self._client.delete_collection(name)

    async def upsert(
        self, session: AsyncSession, collection_id: int, items: list[VectorItem]
    ) -> None:
        if not items:
            return
        from qdrant_client.models import PointStruct
        points = [
            PointStruct(id=it.chunk_id, vector=it.vector, payload=it.payload)
            for it in items
        ]
        await self._client.upsert(self._name(collection_id), points=points, wait=True)

    async def delete_by_document(
        self, session: AsyncSession, collection_id: int, document_id: int
    ) -> None:
        from qdrant_client.models import (
            FieldCondition, Filter, FilterSelector, MatchValue,
        )
        flt = Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))])
        await self._client.delete(
            self._name(collection_id), points_selector=FilterSelector(filter=flt), wait=True
        )

    async def search(
        self, session: AsyncSession, spec: CollectionSpec, query_vec: list[float], k: int,
        filters: dict | None = None, *, where=None,
    ) -> list[VectorHit]:
        # where(SQL 절)는 SQL 백엔드 전용 — 외부 스토어는 무시(호출부 하이드레이션이 강제).
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        qfilter = None
        if filters:
            qfilter = Filter(
                must=[FieldCondition(key=key, match=MatchValue(value=v)) for key, v in filters.items()]
            )
        res = await self._client.query_points(
            self._name(spec.collection_id), query=query_vec, limit=k,
            query_filter=qfilter, with_payload=False,
        )
        # cosine/dot 은 점수가 클수록 유사. l2(EUCLID)는 거리라 역변환.
        m = (spec.metric or "cosine").lower()
        out: list[VectorHit] = []
        for p in res.points:
            score = float(p.score)
            if m == "l2":
                score = 1.0 / (1.0 + score)
            out.append(VectorHit(chunk_id=str(p.id), score=score))
        return out
