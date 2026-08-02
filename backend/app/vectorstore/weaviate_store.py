# SPDX-License-Identifier: Apache-2.0
"""WeaviateStore — Weaviate 벡터DB 어댑터 (client v4).

요구: ``pip install weaviate-client`` + 가동 중인 Weaviate 서버.
v4 클라이언트는 동기라 호출을 asyncio.to_thread 로 오프로드한다.
컬렉션(Class): Argus 컬렉션별 1:1 — Weaviate Class 명은 대문자 시작 필요 → ``Argus_c{id}`` 형태로 정규화.
벡터는 자체 관리(vectorizer=none), 객체 UUID = chunk_id(UUID), document_id 프로퍼티로 필터.

NOTE: 이 환경에 Weaviate 서버가 없어 E2E 미검증(best-effort). 연결 파라미터/클래스명 규칙은 서버 버전에 맞게 조정 필요할 수 있음.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.vectorstore.base import CollectionSpec, VectorHit, VectorItem

logger = logging.getLogger(__name__)


class WeaviateStore:
    def __init__(self, url: str, api_key: str | None, prefix: str):
        if not url:
            raise ValueError("Weaviate URL(vector_store_url)이 설정되지 않았습니다.")
        import weaviate  # lazy
        from weaviate.classes.init import Auth
        p = urlparse(url if "://" in url else f"http://{url}")
        host = p.hostname or "localhost"
        secure = p.scheme == "https"
        http_port = p.port or (443 if secure else 8080)
        self._client = weaviate.connect_to_custom(
            http_host=host, http_port=http_port, http_secure=secure,
            grpc_host=host, grpc_port=50051, grpc_secure=secure,
            auth_credentials=Auth.api_key(api_key) if api_key else None,
            skip_init_checks=True,
        )
        # prefix 를 Class 명 접두로(첫 글자 대문자 강제)
        self._prefix = (prefix or "argus").capitalize()

    def _name(self, collection_id: int) -> str:
        return f"{self._prefix}_c{collection_id}"

    def _vector_distance(self, metric: str) -> str:
        return {"l2": "l2-squared", "inner_product": "dot"}.get(
            (metric or "cosine").lower(), "cosine"
        )

    async def ensure_collection(self, session: AsyncSession, spec: CollectionSpec) -> None:
        name = self._name(spec.collection_id)

        def _do():
            from weaviate.classes.config import Configure, DataType, Property
            if self._client.collections.exists(name):
                return
            self._client.collections.create(
                name,
                vectorizer_config=Configure.Vectorizer.none(),
                vector_index_config=Configure.VectorIndex.hnsw(
                    distance_metric=self._vector_distance(spec.metric)
                ),
                properties=[Property(name="document_id", data_type=DataType.INT)],
            )

        await asyncio.to_thread(_do)

    async def drop_collection(self, session: AsyncSession, collection_id: int) -> None:
        name = self._name(collection_id)

        def _do():
            if self._client.collections.exists(name):
                self._client.collections.delete(name)

        await asyncio.to_thread(_do)

    async def upsert(
        self, session: AsyncSession, collection_id: int, items: list[VectorItem]
    ) -> None:
        if not items:
            return
        name = self._name(collection_id)

        def _do():
            coll = self._client.collections.get(name)
            with coll.batch.dynamic() as batch:
                for it in items:
                    batch.add_object(
                        properties={"document_id": int(it.payload.get("document_id", 0))},
                        uuid=it.chunk_id, vector=it.vector,
                    )

        await asyncio.to_thread(_do)

    async def delete_by_document(
        self, session: AsyncSession, collection_id: int, document_id: int
    ) -> None:
        name = self._name(collection_id)

        def _do():
            from weaviate.classes.query import Filter
            coll = self._client.collections.get(name)
            coll.data.delete_many(
                where=Filter.by_property("document_id").equal(int(document_id))
            )

        await asyncio.to_thread(_do)

    async def search(
        self, session: AsyncSession, spec: CollectionSpec, query_vec: list[float], k: int,
        filters: dict | None = None, *, where=None,
    ) -> list[VectorHit]:
        # where(SQL 절)는 SQL 백엔드 전용 — 외부 스토어는 무시(호출부 하이드레이션이 강제).
        name = self._name(spec.collection_id)

        def _do():
            from weaviate.classes.query import Filter, MetadataQuery
            coll = self._client.collections.get(name)
            wfilter = None
            if filters:
                conds = [Filter.by_property(key).equal(v) for key, v in filters.items()]
                wfilter = conds[0] if len(conds) == 1 else Filter.all_of(conds)
            return coll.query.near_vector(
                near_vector=query_vec, limit=k, filters=wfilter,
                return_metadata=MetadataQuery(distance=True),
            )

        res = await asyncio.to_thread(_do)
        out: list[VectorHit] = []
        for obj in res.objects:
            dist = obj.metadata.distance if obj.metadata and obj.metadata.distance is not None else 1.0
            # Weaviate distance: cosine=1-sim, l2-squared=거리, dot=음수내적. 작을수록 유사 → 유사도로 변환.
            out.append(VectorHit(chunk_id=str(obj.uuid), score=1.0 / (1.0 + float(dist))))
        return out
