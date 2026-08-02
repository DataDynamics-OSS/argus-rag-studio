# SPDX-License-Identifier: Apache-2.0
"""컬렉션(지식베이스) 서비스(비즈니스 로직 계층).

모든 public 함수는 첫 인자로 ``AsyncSession`` 을 받는다. 문서 수는 ``rag_documents`` 를
컬렉션별로 그룹 카운트해 응답에 합성한다(M1 — 별도 캐시 컬럼 없이 조인 집계).
"""

import logging
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections.models import RagCollection
from app.collections.schemas import (
    CollectionCreateRequest,
    CollectionReindexRequest,
    CollectionReindexResponse,
    CollectionResponse,
    CollectionUpdateRequest,
    PaginatedCollectionResponse,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


class DuplicateCollectionError(ValueError):
    """동일 이름 컬렉션 존재(라우터가 409 로 변환). 일반 검증 오류(ValueError)는 400."""


def _validate_store_dim(dim: int) -> None:
    """벡터 스토어의 고정 차원 제약 검증 — 생성 시점에 fail-fast.

    pgvector 는 ``rag_chunks.embedding`` 이 DDL 에서 ``vector(N)`` 으로 고정이라(전 컬렉션 공유)
    다른 차원의 컬렉션은 생성돼도 색인 시점에 "expected N dimensions" 로 실패한다.
    외부 스토어(qdrant/weaviate/milvus/databricks)는 컬렉션별 차원 생성이 가능하므로 통과.
    """
    if (settings.vector_store_provider or "pgvector").lower() != "pgvector":
        return
    fixed = settings.embedding_default_dim  # DDL vector(N) 과 단일 소스(chunks/models.py 동일)
    if dim != fixed:
        raise ValueError(
            f"pgvector 벡터 스토어는 임베딩 차원이 {fixed} 로 고정입니다"
            f"(rag_chunks.embedding vector({fixed})). {dim} 차원 모델은 사용할 수 없습니다 — "
            f"{fixed} 차원 모델을 선택하거나 외부 벡터 스토어를 구성하세요."
        )


def _validate_local_embedding(provider: str, model: str, dim: int) -> None:
    """local(FastEmbed) 프로바이더면 모델 지원 여부 + 차원 일치를 검증한다.

    사용자가 임의 모델명을 넣거나 차원이 안 맞으면 색인이 깨지므로 생성 전에 막는다.
    """
    if (provider or "").lower() != "local":
        return
    from app.embedding.provider import list_local_models
    supported = {m["model"]: m["dim"] for m in list_local_models()}
    if not supported:
        raise ValueError("로컬 임베딩(FastEmbed)을 사용할 수 없습니다(의존성 미설치).")
    if model not in supported:
        raise ValueError(
            f"지원하지 않는 로컬 임베딩 모델입니다: '{model}'. 지원 모델 목록에서 선택하세요."
        )
    if supported[model] != dim:
        raise ValueError(
            f"모델 '{model}'의 출력 차원({supported[model]})이 컬렉션 차원({dim})과 다릅니다."
        )


async def _document_count(session: AsyncSession, collection_id: int) -> int:
    """컬렉션에 속한 문서 수를 센다. ``rag_documents`` 미생성 환경에서도 안전하게 0 반환."""
    from app.documents.models import RagDocument
    return (await session.execute(
        select(func.count()).where(RagDocument.collection_id == collection_id)
    )).scalar() or 0


def _to_response(c: RagCollection, document_count: int) -> CollectionResponse:
    return CollectionResponse(
        id=c.id,
        collection_id=c.collection_id,
        name=c.name,
        description=c.description,
        embedding_provider=c.embedding_provider,
        embedding_model=c.embedding_model,
        embedding_dim=c.embedding_dim,
        embedding_server_url=c.embedding_server_url,
        distance_metric=c.distance_metric,
        rerank_provider=c.rerank_provider,
        parse_strategy=c.parse_strategy,
        rerank_model=c.rerank_model,
        chunk_strategy=c.chunk_strategy,
        chunk_unit=c.chunk_unit,
        chunk_size=c.chunk_size,
        chunk_overlap=c.chunk_overlap,
        ingestion_pipeline=c.ingestion_pipeline,
        status=c.status,
        document_count=document_count,
        created_by=c.created_by,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


async def create_collection(
    session: AsyncSession, req: CollectionCreateRequest, created_by: str | None,
) -> CollectionResponse:
    """컬렉션 생성. 임베딩 설정 미지정 시 서버 기본값으로 채운다(생성 후 불변).

    Raises:
        DuplicateCollectionError: 동일 이름 컬렉션이 이미 있으면(라우터가 409 로 변환).
        ValueError: 설정 검증 실패(차원/모델 등 — 라우터가 400 으로 변환).
    """
    existing = (await session.execute(
        select(RagCollection).where(RagCollection.name == req.name)
    )).scalars().first()
    if existing:
        raise DuplicateCollectionError(f"Collection '{req.name}' already exists")

    e_provider = (req.embedding_provider.value if req.embedding_provider
                  else settings.embedding_provider)
    e_model = req.embedding_model or settings.embedding_default_model
    e_dim = req.embedding_dim or settings.embedding_default_dim
    _validate_store_dim(e_dim)
    _validate_local_embedding(e_provider, e_model, e_dim)

    collection = RagCollection(
        collection_id=str(uuid.uuid4()),
        name=req.name,
        description=req.description,
        embedding_provider=e_provider,
        embedding_model=e_model,
        embedding_dim=e_dim,
        embedding_server_url=req.embedding_server_url or None,
        distance_metric=(req.distance_metric.value if req.distance_metric
                         else settings.embedding_default_metric),
        rerank_provider=(req.rerank_provider.value if req.rerank_provider else "none"),
        rerank_model=(req.rerank_model or None),
        parse_strategy=(req.parse_strategy.value if req.parse_strategy else "auto"),
        chunk_strategy=(req.chunk_strategy.value if req.chunk_strategy else "auto"),
        chunk_unit=(req.chunk_unit.value if req.chunk_unit else "char"),
        chunk_size=req.chunk_size or settings.ingestion_chunk_size,
        chunk_overlap=(req.chunk_overlap if req.chunk_overlap is not None
                       else settings.ingestion_chunk_overlap),
        status="active",
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(collection)
    await session.commit()
    await session.refresh(collection)
    # 벡터 스토어 컬렉션 보장(pgvector 는 no-op — 공유 컬럼).
    from app.vectorstore import CollectionSpec, get_vector_store
    await get_vector_store().ensure_collection(
        session, CollectionSpec(collection.id, collection.embedding_dim, collection.distance_metric)
    )
    logger.info(
        "컬렉션 생성: %s (id=%d, provider=%s, model=%s/%d, chunk=%s %d/%d)",
        collection.name, collection.id, collection.embedding_provider,
        collection.embedding_model, collection.embedding_dim,
        collection.chunk_strategy, collection.chunk_size, collection.chunk_overlap,
    )
    return _to_response(collection, 0)


async def get_collection(session: AsyncSession, collection_id: int) -> CollectionResponse | None:
    """ID 로 단건 조회. 문서 수를 합성해 반환. 없으면 None."""
    collection = (await session.execute(
        select(RagCollection).where(RagCollection.id == collection_id)
    )).scalars().first()
    if not collection:
        return None
    count = await _document_count(session, collection.id)
    return _to_response(collection, count)


async def get_collection_by_uuid(
    session: AsyncSession, collection_uuid: str
) -> CollectionResponse | None:
    """외부 노출용 UUID(collection_id)로 단건 조회. 내부 PK(id)는 응답에 포함된다."""
    collection = (await session.execute(
        select(RagCollection).where(RagCollection.collection_id == collection_uuid)
    )).scalars().first()
    if not collection:
        return None
    count = await _document_count(session, collection.id)
    return _to_response(collection, count)


async def update_collection(
    session: AsyncSession, collection_id: int, req: CollectionUpdateRequest,
) -> CollectionResponse | None:
    """컬렉션 메타데이터 부분 갱신. 임베딩 설정은 변경 불가."""
    collection = (await session.execute(
        select(RagCollection).where(RagCollection.id == collection_id)
    )).scalars().first()
    if not collection:
        return None

    if req.description is not None:
        collection.description = req.description
    if req.status is not None:
        collection.status = req.status.value
    if req.rerank_provider is not None:
        collection.rerank_provider = req.rerank_provider.value
    if req.rerank_model is not None:
        collection.rerank_model = req.rerank_model or None

    await session.commit()
    await session.refresh(collection)
    count = await _document_count(session, collection.id)
    logger.info("컬렉션 수정: %s (id=%d)", collection.name, collection.id)
    return _to_response(collection, count)


async def reindex_collection(
    session: AsyncSession, collection_id: int, req: CollectionReindexRequest,
) -> CollectionReindexResponse | None:
    """색인 설정(임베딩/청킹)을 변경하고 컬렉션의 모든 문서를 새 설정으로 재인덱싱한다.

    제공된 필드만 갱신한다. ``embedding_dim`` 은 물리 벡터 컬럼 고정으로 변경 불가.
    원본(source_uri)이 있는 문서만 재처리 대상이며, 각 문서를 ``registered`` 로 되돌리고
    인제스천 잡을 enqueue 한다(워커가 새 설정으로 parse→chunk→embed→index).

    Raises:
        ValueError: chunk_overlap >= chunk_size 등 설정이 유효하지 않을 때(라우터가 400 변환).
    """
    from app.documents.models import RagDocument
    from app.ingestion.service import enqueue_job

    collection = (await session.execute(
        select(RagCollection).where(RagCollection.id == collection_id)
    )).scalars().first()
    if not collection:
        return None

    # 1) 설정 부분 갱신(제공된 필드만)
    if req.embedding_provider is not None:
        collection.embedding_provider = req.embedding_provider.value
    if req.embedding_model is not None:
        collection.embedding_model = req.embedding_model
    if req.clear_server_url:
        collection.embedding_server_url = None
    elif req.embedding_server_url is not None:
        collection.embedding_server_url = req.embedding_server_url
    if req.distance_metric is not None:
        collection.distance_metric = req.distance_metric.value
    if req.parse_strategy is not None:
        collection.parse_strategy = req.parse_strategy.value
    if req.chunk_strategy is not None:
        collection.chunk_strategy = req.chunk_strategy.value
    if req.chunk_unit is not None:
        collection.chunk_unit = req.chunk_unit.value
    if req.chunk_size is not None:
        collection.chunk_size = req.chunk_size
    if req.chunk_overlap is not None:
        collection.chunk_overlap = req.chunk_overlap

    # 인제스천 보강 파이프라인(post_parse/post_chunk) — 제공 시 검증 후 저장
    if req.post_parse is not None or req.post_chunk is not None:
        from app.ingestion.transforms import normalize_pipeline, validate_pipeline

        raw = {
            "post_parse": [s.model_dump() for s in (req.post_parse or [])],
            "post_chunk": [s.model_dump() for s in (req.post_chunk or [])],
        }
        errors = validate_pipeline(raw)
        if errors:
            raise ValueError("보강 파이프라인 오류: " + "; ".join(errors))
        collection.ingestion_pipeline = normalize_pipeline(raw)

    if collection.chunk_overlap >= collection.chunk_size:
        raise ValueError("chunk_overlap 은 chunk_size 보다 작아야 합니다.")
    _validate_store_dim(collection.embedding_dim)
    _validate_local_embedding(
        collection.embedding_provider, collection.embedding_model, collection.embedding_dim
    )

    # 2) 재처리 대상 문서 수집(원본이 있는 것만)
    documents = list((await session.execute(
        select(RagDocument).where(
            RagDocument.collection_id == collection.id,
            RagDocument.source_uri.isnot(None),
        )
    )).scalars().all())

    # 3) 설정 커밋 후 문서별 잡 enqueue
    for doc in documents:
        doc.status = "registered"
    await session.commit()
    await session.refresh(collection)

    job_ids: list[str] = []
    for doc in documents:
        job = await enqueue_job(session, doc.id, collection.id)
        job_ids.append(job.job_id)

    count = await _document_count(session, collection.id)
    logger.info(
        "컬렉션 재인덱싱: %s (id=%d) — 문서 %d개 enqueue (provider=%s model=%s chunk=%s %d/%d)",
        collection.name, collection.id, len(job_ids), collection.embedding_provider,
        collection.embedding_model, collection.chunk_strategy,
        collection.chunk_size, collection.chunk_overlap,
    )
    return CollectionReindexResponse(
        collection=_to_response(collection, count),
        document_count=len(job_ids),
        job_ids=job_ids,
    )


async def delete_collection(session: AsyncSession, collection_id: int) -> bool:
    """컬렉션 삭제. 하위 문서는 FK ON DELETE CASCADE 로 함께 제거된다."""
    collection = (await session.execute(
        select(RagCollection).where(RagCollection.id == collection_id)
    )).scalars().first()
    if not collection:
        return False
    cid, coll_uuid = collection.id, collection.collection_id
    await session.delete(collection)
    await session.commit()
    # 벡터 스토어 정리(pgvector 는 청크 FK CASCADE 로 처리 — no-op).
    from app.vectorstore import get_vector_store
    await get_vector_store().drop_collection(session, cid)
    # 내부 저장소의 컬렉션 스냅샷 전체 정리(best-effort — 스토리지 장애가 삭제를 막지 않게).
    # 표준 키 규칙(collections/{collection_uuid}/…) 하위만 지우므로 외부 원본은 건드리지 않는다.
    from app.storage.client import delete_paths
    try:
        await delete_paths([f"collections/{coll_uuid}/"])
    except Exception as e:  # noqa: BLE001
        logger.warning("컬렉션 스냅샷 정리 실패(고아 오브젝트 잔존): %s err=%s", coll_uuid, e)
    logger.info("컬렉션 삭제: %s (id=%d)", collection.name, cid)
    return True


async def list_collections(
    session: AsyncSession,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedCollectionResponse:
    """필터·페이지네이션을 적용한 컬렉션 목록. 각 행의 문서 수를 단일 그룹 쿼리로 합성."""
    from app.documents.models import RagDocument

    base = select(RagCollection)
    if status:
        base = base.where(RagCollection.status == status)
    if search:
        pattern = f"%{search}%"
        base = base.where(or_(
            RagCollection.name.ilike(pattern),
            RagCollection.description.ilike(pattern),
        ))

    total = (await session.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar() or 0

    query = base.order_by(RagCollection.created_at.desc())
    if page_size > 0:
        query = query.offset((page - 1) * page_size).limit(page_size)
    collections = (await session.execute(query)).scalars().all()

    # 현재 페이지 컬렉션들의 문서 수를 한 번에 집계
    ids = [c.id for c in collections]
    counts: dict[int, int] = {}
    if ids:
        rows = (await session.execute(
            select(RagDocument.collection_id, func.count())
            .where(RagDocument.collection_id.in_(ids))
            .group_by(RagDocument.collection_id)
        )).all()
        counts = {cid: cnt for cid, cnt in rows}

    items = [_to_response(c, counts.get(c.id, 0)) for c in collections]
    return PaginatedCollectionResponse(items=items, total=total, page=page, page_size=page_size)
