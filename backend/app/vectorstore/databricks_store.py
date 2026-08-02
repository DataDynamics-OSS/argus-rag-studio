# SPDX-License-Identifier: Apache-2.0
"""DatabricksVectorStore — Databricks Mosaic AI Vector Search 어댑터.

요구: ``pip install databricks-vectorsearch`` + Databricks workspace(PAT 토큰) + 가동 중인
Vector Search 엔드포인트(컴퓨트). 인증은 기반 환경 설정(databricks_host/token)을 재사용한다.

설계
----
- Argus 가 임베딩을 직접 계산해 밀어넣으므로 **Direct Vector Access Index** 를 쓴다(Delta Sync 아님).
  Argus 컬렉션마다 인덱스 1:1 — Unity Catalog 이름 ``{catalog}.{schema}.{prefix}_c{id}``.
- primary key = 청크 UUID(chunk_id). 벡터 컬럼 = ``embedding``. 메타데이터 컬럼으로
  document_id/status/seq 를 함께 저장해 필터·문서 단위 삭제에 사용한다.
- ``delete_by_document`` 은 Direct Access 인덱스가 메타데이터 필터 삭제를 지원하지 않으므로,
  전달받은 PostgreSQL 세션에서 해당 문서의 chunk UUID 를 조회해 primary key 로 삭제한다(정본은 Postgres).
- SDK 는 동기(blocking)라 모든 호출을 ``asyncio.to_thread`` 로 감싸 이벤트 루프를 막지 않는다.

검색 결과는 (chunk_id, score) 만 반환한다 — 본문/문서명은 호출부(retrieval)가 Postgres 에서 hydrate.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.vectorstore.base import CollectionSpec, VectorHit, VectorItem

logger = logging.getLogger(__name__)

# Direct Access Index 스키마(컬럼 → 타입). VectorItem.chunk_id + payload({document_id,status,seq}) 와 일치.
_PRIMARY_KEY = "chunk_id"
_VECTOR_COLUMN = "embedding"


class DatabricksVectorStore:
    def __init__(
        self,
        *,
        host: str,
        token: str,
        endpoint: str,
        catalog: str,
        schema: str,
        prefix: str,
    ):
        if not host:
            raise ValueError("Databricks Host(databricks.host)가 설정되지 않았습니다.")
        if not token:
            raise ValueError("Databricks PAT 토큰(databricks.token)이 설정되지 않았습니다.")
        if not endpoint:
            raise ValueError(
                "Vector Search 엔드포인트(retrieval.vector_store_databricks_endpoint)가 설정되지 않았습니다."
            )
        from databricks.vector_search.client import VectorSearchClient  # lazy

        self._client = VectorSearchClient(
            workspace_url=host, personal_access_token=token, disable_notice=True
        )
        self._endpoint = endpoint
        self._catalog = catalog or "main"
        self._schema = schema or "argus"
        self._prefix = prefix or "argus"

    def _index_name(self, collection_id: int) -> str:
        """Unity Catalog 3-level 인덱스 전체 이름."""
        return f"{self._catalog}.{self._schema}.{self._prefix}_c{collection_id}"

    def _get_index(self, collection_id: int):
        return self._client.get_index(
            endpoint_name=self._endpoint, index_name=self._index_name(collection_id)
        )

    # ── 컬렉션 수명주기 ────────────────────────────────────────────────────────
    def _ensure_sync(self, spec: CollectionSpec) -> None:
        name = self._index_name(spec.collection_id)
        try:
            self._client.get_index(endpoint_name=self._endpoint, index_name=name).describe()
            return  # 이미 존재
        except Exception:
            pass  # 없음 → 생성
        self._client.create_direct_access_index(
            endpoint_name=self._endpoint,
            index_name=name,
            primary_key=_PRIMARY_KEY,
            embedding_dimension=spec.dim,
            embedding_vector_column=_VECTOR_COLUMN,
            schema={
                _PRIMARY_KEY: "string",
                _VECTOR_COLUMN: f"array<float>[{spec.dim}]",
                "document_id": "int",
                "status": "string",
                "seq": "int",
            },
        )
        logger.info("Databricks Vector Search 인덱스 생성: %s (dim=%d)", name, spec.dim)

    async def ensure_collection(self, session: AsyncSession, spec: CollectionSpec) -> None:
        await asyncio.to_thread(self._ensure_sync, spec)

    async def drop_collection(self, session: AsyncSession, collection_id: int) -> None:
        name = self._index_name(collection_id)

        def _drop():
            try:
                self._client.delete_index(endpoint_name=self._endpoint, index_name=name)
            except Exception as e:  # 없는 인덱스 삭제는 무시
                logger.warning("Databricks 인덱스 삭제 무시(%s): %s", name, e)

        await asyncio.to_thread(_drop)

    # ── 업서트 / 삭제 ─────────────────────────────────────────────────────────
    async def upsert(
        self, session: AsyncSession, collection_id: int, items: list[VectorItem]
    ) -> None:
        if not items:
            return
        rows = [
            {
                _PRIMARY_KEY: it.chunk_id,
                _VECTOR_COLUMN: it.vector,
                "document_id": int(it.payload.get("document_id", 0)),
                "status": str(it.payload.get("status", "indexed")),
                "seq": int(it.payload.get("seq", 0)),
            }
            for it in items
        ]
        index = await asyncio.to_thread(self._get_index, collection_id)
        await asyncio.to_thread(index.upsert, rows)

    async def delete_by_document(
        self, session: AsyncSession, collection_id: int, document_id: int
    ) -> None:
        # Direct Access 인덱스는 primary key 삭제만 지원 → 정본(Postgres)에서 chunk UUID 를 조회해 삭제.
        from app.chunks.models import RagChunk

        chunk_ids = (
            (
                await session.execute(
                    select(RagChunk.chunk_id).where(RagChunk.document_id == document_id)
                )
            )
            .scalars()
            .all()
        )
        if not chunk_ids:
            return
        index = await asyncio.to_thread(self._get_index, collection_id)
        await asyncio.to_thread(index.delete, list(chunk_ids))

    # ── 검색 ──────────────────────────────────────────────────────────────────
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
        # where(SQL 절)는 SQL 백엔드 전용 — 외부 스토어는 무시(호출부 하이드레이션이 동일 필터 강제).
        index = await asyncio.to_thread(self._get_index, spec.collection_id)

        def _search():
            return index.similarity_search(
                query_vector=query_vec,
                columns=[_PRIMARY_KEY],
                num_results=k,
                filters=filters or None,
            )

        res = await asyncio.to_thread(_search)
        return _parse_hits(res)


def _parse_hits(res: dict) -> list[VectorHit]:
    """Mosaic similarity_search 응답 → VectorHit 목록.

    응답 형태: ``{"result": {"data_array": [[<chunk_id>, ..., <score>], ...]}}``.
    요청 columns 뒤에 점수가 마지막 컬럼으로 붙는다(클수록 유사). 첫 컬럼이 primary key.
    """
    if not res:
        return []
    rows = ((res.get("result") or {}).get("data_array")) or []
    out: list[VectorHit] = []
    for row in rows:
        if not row:
            continue
        out.append(VectorHit(chunk_id=str(row[0]), score=float(row[-1])))
    return out
