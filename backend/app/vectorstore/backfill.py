# SPDX-License-Identifier: Apache-2.0
"""벡터 재색인(백필) — PostgreSQL 정본(rag_chunks.embedding) → 현재 VectorStore 로 적재.

벡터DB 를 외부(qdrant/weaviate/milvus)로 전환한 직후엔 대상 스토어가 비어 있으므로,
이 백필을 한 번 돌려야 기존 문서가 검색된다. pgvector 가 대상이면 사실상 no-op(쓰기 무시).
정본이 Postgres 이므로 몇 번을 돌려도 안전(idempotent: drop → ensure → upsert).
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunks.models import RagChunk
from app.collections.models import RagCollection
from app.documents.models import RagDocument
from app.vectorstore.base import CollectionSpec, VectorItem
from app.vectorstore.factory import get_vector_store

logger = logging.getLogger(__name__)

_BATCH = 500


async def reindex_collection(session: AsyncSession, collection: RagCollection) -> int:
    """한 컬렉션의 인덱싱된 청크 벡터를 현재 스토어로 재적재. 적재한 벡터 수 반환."""
    store = get_vector_store()
    spec = CollectionSpec(collection.id, collection.embedding_dim, collection.distance_metric)
    await store.drop_collection(session, collection.id)
    await store.ensure_collection(session, spec)

    total = 0
    last_id = 0
    while True:
        rows = (await session.execute(
            select(RagChunk.id, RagChunk.chunk_id, RagChunk.document_id, RagChunk.seq, RagChunk.embedding)
            .join(RagDocument, RagChunk.document_id == RagDocument.id)
            .where(
                RagChunk.collection_id == collection.id,
                RagChunk.embedding.isnot(None),
                RagDocument.status == "indexed",
                RagChunk.id > last_id,
            )
            .order_by(RagChunk.id)
            .limit(_BATCH)
        )).all()
        if not rows:
            break
        items = [
            VectorItem(
                chunk_id=chunk_id, vector=list(emb),
                payload={"document_id": doc_id, "status": "indexed", "seq": seq},
            )
            for (_id, chunk_id, doc_id, seq, emb) in rows
        ]
        await store.upsert(session, collection.id, items)
        total += len(items)
        last_id = rows[-1][0]
    logger.info("reindex collection=%s indexed=%d vectors", collection.id, total)
    return total


async def reindex_all(session: AsyncSession) -> dict:
    """전체 컬렉션 재색인. {provider, collections, vectors} 요약 반환."""
    from app.core.config import settings
    collections = (await session.execute(select(RagCollection))).scalars().all()
    vectors = 0
    for coll in collections:
        vectors += await reindex_collection(session, coll)
    return {
        "provider": settings.vector_store_provider,
        "collections": len(collections),
        "vectors": vectors,
    }
