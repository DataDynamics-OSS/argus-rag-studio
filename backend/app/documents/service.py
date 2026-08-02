# SPDX-License-Identifier: Apache-2.0
"""문서(Document) 서비스(비즈니스 로직 계층).

문서는 항상 컬렉션에 종속된다(``collection_id`` FK). 모든 함수는 컬렉션 존재를 전제로
하며, 라우터가 사전에 컬렉션을 검증한다.
"""

import json
import logging
import uuid

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunks.models import RagChunk
from app.documents.models import RagDocument
from app.documents.schemas import (
    ChunkInspectItem,
    DocumentChunksResponse,
    DocumentCreateRequest,
    DocumentResponse,
    DocumentUpdateRequest,
    PaginatedDocumentResponse,
)
from app.ingestion.models import RagIngestionJob

logger = logging.getLogger(__name__)


def _to_response(d: RagDocument) -> DocumentResponse:
    return DocumentResponse(
        id=d.id,
        document_id=d.document_id,
        collection_id=d.collection_id,
        name=d.name,
        source_type=d.source_type,
        source_uri=d.source_uri,
        content_hash=d.content_hash,
        size_bytes=d.size_bytes,
        status=d.status,
        chunk_count=d.chunk_count,
        metadata_json=d.metadata_json,
        indexed_at=d.indexed_at,
        created_by=d.created_by,
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


async def create_document(
    session: AsyncSession, collection_id: int, req: DocumentCreateRequest, created_by: str | None,
) -> DocumentResponse:
    """컬렉션에 문서를 등록한다(M1: 메타데이터). 상태는 ``registered`` 로 시작."""
    document = RagDocument(
        document_id=str(uuid.uuid4()),
        collection_id=collection_id,
        name=req.name,
        source_type=req.source_type.value,
        source_uri=req.source_uri,
        content_hash=req.content_hash,
        size_bytes=req.size_bytes,
        status="registered",
        chunk_count=0,
        metadata_json=req.metadata_json,
        created_by=created_by,
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)
    logger.info("문서 등록: %s (id=%d, collection=%d)", document.name, document.id, collection_id)
    return _to_response(document)


async def get_document(session: AsyncSession, document_id: int) -> DocumentResponse | None:
    """ID 로 문서 단건 조회. 없으면 None."""
    document = (await session.execute(
        select(RagDocument).where(RagDocument.id == document_id)
    )).scalars().first()
    if not document:
        return None
    return _to_response(document)


async def get_document_by_uuid(session: AsyncSession, document_uuid: str) -> DocumentResponse | None:
    """외부 노출용 UUID(document_id)로 조회. 내부 PK(id)는 응답에 포함된다."""
    document = (await session.execute(
        select(RagDocument).where(RagDocument.document_id == document_uuid)
    )).scalars().first()
    if not document:
        return None
    return _to_response(document)


async def update_document(
    session: AsyncSession, document_id: int, req: DocumentUpdateRequest,
) -> DocumentResponse | None:
    """문서 메타데이터/상태 부분 갱신."""
    document = (await session.execute(
        select(RagDocument).where(RagDocument.id == document_id)
    )).scalars().first()
    if not document:
        return None

    if req.name is not None:
        document.name = req.name
    if req.status is not None:
        document.status = req.status.value
    if req.metadata_json is not None:
        document.metadata_json = req.metadata_json

    await session.commit()
    await session.refresh(document)
    logger.info("문서 수정: %s (id=%d)", document.name, document.id)
    return _to_response(document)


def internal_snapshot_key(source_uri: str | None, document_uuid: str) -> str | None:
    """내부 저장소의 이 문서 소유 스냅샷 키만 반환(아니면 None) — 삭제 시 정리 대상 판별.

    표준 키(``collections/{collection_uuid}/{document_uuid}/…``)에 자기 uuid 가 있어야 한다.
    외부 파이프라인 등록(``/ingestion/register``)의 source_uri 는 우리가 소유한 오브젝트가
    아니므로 지우지 않는다(다른 버킷/비표준 키 → None).
    """
    if not source_uri:
        return None
    from app.core.config import settings
    from app.storage.client import parse_source_uri

    try:
        bucket, key = parse_source_uri(source_uri)
    except Exception:  # noqa: BLE001 — 비정상 URI 는 정리 대상 아님
        return None
    if bucket != settings.os_bucket:
        return None
    if key.startswith("collections/") and f"/{document_uuid}/" in key:
        return key
    return None


async def _delete_snapshot(source_uri: str | None, document_uuid: str) -> None:
    """내부 스냅샷 오브젝트 정리(best-effort) — 스토리지 장애가 삭제를 막지 않게 한다."""
    key = internal_snapshot_key(source_uri, document_uuid)
    if not key:
        return
    from app.storage.client import delete_object

    try:
        await delete_object(key)
    except Exception as e:  # noqa: BLE001
        logger.warning("문서 스냅샷 정리 실패(고아 오브젝트 잔존): %s err=%s", key, e)


async def delete_document(session: AsyncSession, document_id: int) -> bool:
    """문서 삭제 — DB 행 + 내부 저장소 스냅샷(있으면) 함께 정리."""
    document = (await session.execute(
        select(RagDocument).where(RagDocument.id == document_id)
    )).scalars().first()
    if not document:
        return False
    source_uri, doc_uuid = document.source_uri, document.document_id
    await session.delete(document)
    await session.commit()
    await _delete_snapshot(source_uri, doc_uuid)
    logger.info("문서 삭제: %s (id=%d)", document.name, document.id)
    return True


async def list_documents(
    session: AsyncSession,
    collection_id: int,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedDocumentResponse:
    """특정 컬렉션의 문서 목록을 필터·페이지네이션해 반환한다."""
    base = select(RagDocument).where(RagDocument.collection_id == collection_id)
    if status:
        base = base.where(RagDocument.status == status)
    if search:
        base = base.where(RagDocument.name.ilike(f"%{search}%"))

    total = (await session.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar() or 0

    query = base.order_by(RagDocument.created_at.desc())
    if page_size > 0:
        query = query.offset((page - 1) * page_size).limit(page_size)
    documents = (await session.execute(query)).scalars().all()

    items = [_to_response(d) for d in documents]
    return PaginatedDocumentResponse(items=items, total=total, page=page, page_size=page_size)


def _chunk_counts(meta_json: str | None) -> tuple[int | None, int | None]:
    """청크 metadata_json 에서 (char_count, token_count) 를 꺼낸다(없으면 None)."""
    if not meta_json:
        return None, None
    try:
        m = json.loads(meta_json)
    except (ValueError, TypeError):
        return None, None
    cc = m.get("char_count")
    tc = m.get("token_count")
    return (cc if isinstance(cc, int) else None, tc if isinstance(tc, int) else None)


async def list_document_chunks(
    session: AsyncSession,
    document: RagDocument,
    page: int = 1,
    page_size: int = 20,
) -> DocumentChunksResponse:
    """문서의 인제스천 현황 + 청크 목록(페이지). 임베딩 벡터 자체는 전송하지 않는다."""
    has_emb = RagChunk.embedding.isnot(None)

    total = (await session.execute(
        select(func.count()).select_from(RagChunk).where(RagChunk.document_id == document.id)
    )).scalar() or 0
    embedded = (await session.execute(
        select(func.count()).select_from(RagChunk)
        .where(RagChunk.document_id == document.id, has_emb)
    )).scalar() or 0

    query = (
        select(
            RagChunk.chunk_id, RagChunk.seq, RagChunk.section_path,
            RagChunk.metadata_json, RagChunk.text, has_emb.label("has_embedding"),
        )
        .where(RagChunk.document_id == document.id)
        .order_by(RagChunk.seq)
    )
    if page_size > 0:
        query = query.offset((page - 1) * page_size).limit(page_size)
    rows = (await session.execute(query)).all()

    items: list[ChunkInspectItem] = []
    for chunk_id, seq, section_path, meta_json, text, has_embedding in rows:
        cc, tc = _chunk_counts(meta_json)
        items.append(ChunkInspectItem(
            chunk_id=chunk_id, seq=seq, section_path=section_path,
            char_count=cc, token_count=tc, has_embedding=bool(has_embedding), text=text,
        ))

    # 마지막 인제스천 잡(단계/실패 사유) — 실패 원인 표시용
    job = (await session.execute(
        select(RagIngestionJob)
        .where(RagIngestionJob.document_id == document.id)
        .order_by(desc(RagIngestionJob.id)).limit(1)
    )).scalars().first()

    return DocumentChunksResponse(
        items=items, total=total, page=page, page_size=page_size, embedded=embedded,
        status=document.status,
        last_stage=job.stage if job else None,
        last_error=job.error if job else None,
    )
