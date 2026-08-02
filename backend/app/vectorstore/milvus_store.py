# SPDX-License-Identifier: Apache-2.0
"""MilvusStore — Milvus 벡터DB 어댑터.

요구: ``pip install pymilvus`` + 가동 중인 Milvus(또는 Zilliz Cloud uri+token).
pymilvus 는 동기 클라이언트라 호출을 asyncio.to_thread 로 오프로드한다.
컬렉션: Argus 컬렉션별 1:1, PK=chunk_id(VARCHAR), document_id 필터.

NOTE: 이 환경에 Milvus 서버가 없어 E2E 미검증(best-effort). 점수 정규화는 metric 별로 조정 필요할 수 있음.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.vectorstore.base import CollectionSpec, VectorHit, VectorItem

logger = logging.getLogger(__name__)


class MilvusStore:
    def __init__(self, uri: str, token: str | None, prefix: str):
        if not uri:
            raise ValueError("Milvus URI(vector_store_url)가 설정되지 않았습니다.")
        from pymilvus import MilvusClient  # lazy
        self._client = MilvusClient(uri=uri, token=token or "")
        self._prefix = prefix

    def _name(self, collection_id: int) -> str:
        return f"{self._prefix}_c{collection_id}"

    def _metric(self, metric: str) -> str:
        return {"l2": "L2", "inner_product": "IP"}.get((metric or "cosine").lower(), "COSINE")

    async def ensure_collection(self, session: AsyncSession, spec: CollectionSpec) -> None:
        name = self._name(spec.collection_id)

        def _do():
            if self._client.has_collection(name):
                return
            from pymilvus import DataType
            schema = self._client.create_schema(auto_id=False, enable_dynamic_field=True)
            schema.add_field("chunk_id", DataType.VARCHAR, is_primary=True, max_length=64)
            schema.add_field("vector", DataType.FLOAT_VECTOR, dim=spec.dim)
            schema.add_field("document_id", DataType.INT64)
            self._client.create_collection(name, schema=schema)
            idx = self._client.prepare_index_params()
            idx.add_index("vector", index_type="AUTOINDEX", metric_type=self._metric(spec.metric))
            self._client.create_index(name, idx)
            self._client.load_collection(name)

        await asyncio.to_thread(_do)

    async def drop_collection(self, session: AsyncSession, collection_id: int) -> None:
        name = self._name(collection_id)

        def _do():
            if self._client.has_collection(name):
                self._client.drop_collection(name)

        await asyncio.to_thread(_do)

    async def upsert(
        self, session: AsyncSession, collection_id: int, items: list[VectorItem]
    ) -> None:
        if not items:
            return
        name = self._name(collection_id)
        data = [
            {"chunk_id": it.chunk_id, "vector": it.vector,
             "document_id": int(it.payload.get("document_id", 0))}
            for it in items
        ]
        await asyncio.to_thread(lambda: self._client.upsert(collection_name=name, data=data))

    async def delete_by_document(
        self, session: AsyncSession, collection_id: int, document_id: int
    ) -> None:
        name = self._name(collection_id)
        await asyncio.to_thread(
            lambda: self._client.delete(collection_name=name, filter=f"document_id == {int(document_id)}")
        )

    async def search(
        self, session: AsyncSession, spec: CollectionSpec, query_vec: list[float], k: int,
        filters: dict | None = None, *, where=None,
    ) -> list[VectorHit]:
        # where(SQL 절)는 SQL 백엔드 전용 — 외부 스토어는 무시(호출부 하이드레이션이 강제).
        name = self._name(spec.collection_id)
        expr = ""
        if filters:
            expr = " and ".join(
                (f'{key} == "{v}"' if isinstance(v, str) else f"{key} == {v}")
                for key, v in filters.items()
            )

        def _do():
            return self._client.search(
                collection_name=name, data=[query_vec], limit=k,
                output_fields=["chunk_id"], filter=expr,
                search_params={"metric_type": self._metric(spec.metric)},
            )

        res = await asyncio.to_thread(_do)
        hits = res[0] if res else []
        m = (spec.metric or "cosine").lower()
        out: list[VectorHit] = []
        for h in hits:
            ent = h.get("entity", {}) if isinstance(h, dict) else {}
            cid = ent.get("chunk_id") or (h.get("id") if isinstance(h, dict) else None)
            dist = float(h.get("distance", 0.0)) if isinstance(h, dict) else 0.0
            # COSINE/IP: distance 가 곧 유사도(클수록 좋음). L2: 거리 → 역변환.
            score = 1.0 / (1.0 + dist) if m == "l2" else dist
            out.append(VectorHit(chunk_id=str(cid), score=score))
        return out
