# SPDX-License-Identifier: Apache-2.0
"""인제스천 API.

수집 진입점을 모은다. 업로드(사용자 JWT)와 register(NiFi 등 외부 파이프라인의 서비스 토큰)는
모두 같은 비동기 처리 파이프라인으로 흘러간다.

엔드포인트:
    - POST /collections/{id}/ingest         업로드(multipart) → MinIO 적재 → 등록 → 잡 enqueue
    - POST /ingestion/register              오브젝트 스토리지 경유 등록 (NiFi, 서비스 토큰)
    - GET  /collections/{id}/ingest/jobs    컬렉션의 인제스천 잡 목록
    - GET  /ingestion/jobs/{job_id}         잡 상태(진행률 폴링)
    - POST /documents/{id}/reindex          기존 문서 재처리(청크 교체)
"""

import hashlib
import logging

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections.models import RagCollection
from app.core.auth import CurrentUser, SuperUser
from app.core.config import settings
from app.core.database import get_session
from app.documents.models import RagDocument
from app.ingestion import service
from app.ingestion.models import RagIngestionJob
from app.ingestion.schemas import (
    IngestionJobResponse,
    JobListItem,
    JobsSummaryResponse,
    PaginatedJobsResponse,
    ParsePreviewResponse,
    RegisterRequest,
    UploadResponse,
)
from app.storage.client import build_object_key, put_object

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ingestion"])


def _job_response(job: RagIngestionJob) -> IngestionJobResponse:
    return IngestionJobResponse(
        id=job.id, job_id=job.job_id, document_id=job.document_id,
        collection_id=job.collection_id, status=job.status, stage=job.stage,
        progress=job.progress, chunk_count=job.chunk_count, error=job.error,
        created_at=job.created_at, started_at=job.started_at, finished_at=job.finished_at,
    )


async def _assert_collection(session: AsyncSession, collection_id: int) -> RagCollection:
    collection = (await session.execute(
        select(RagCollection).where(RagCollection.id == collection_id)
    )).scalars().first()
    if not collection:
        raise HTTPException(status_code=404, detail="컬렉션을 찾을 수 없습니다.")
    return collection


# ---------------------------------------------------------------------------
# 업로드 (사용자 JWT)
# ---------------------------------------------------------------------------

@router.post("/collections/{collection_id}/ingest", response_model=UploadResponse, status_code=202)
async def upload_and_ingest(
    collection_id: int,
    user: SuperUser,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """파일 업로드 → MinIO 적재 → 문서 등록 → 인제스천 잡 enqueue (202 Accepted).

    실제 파싱/청킹/임베딩/인덱싱은 비동기 워커가 수행한다. 응답의 ``job_id`` 로 진행률을 폴링한다.
    """
    collection = await _assert_collection(session, collection_id)

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    content_hash = hashlib.sha256(data).hexdigest()

    # 멱등성: 같은 컬렉션에 동일 content_hash 가 이미 있으면 거부(409)
    dup = await service.find_document_by_hash(session, collection_id, content_hash)
    if dup:
        raise HTTPException(
            status_code=409,
            detail=f"동일한 내용의 문서가 이미 등록되어 있습니다(id={dup.id}).",
        )

    document = await service.create_pending_document(
        session,
        collection_id=collection_id,
        name=file.filename or "untitled",
        source_type="upload",
        source_uri=None,
        content_hash=content_hash,
        size_bytes=len(data),
        metadata_json=None,
        created_by=user.username,
    )

    # MinIO 적재 후 source_uri 갱신
    key = build_object_key(collection.collection_id, document.document_id, file.filename or "file")
    source_uri = await put_object(key, data, content_type=file.content_type)
    document.source_uri = source_uri
    await session.commit()

    job = await service.enqueue_job(session, document.id, collection_id)
    return UploadResponse(
        document_id=document.id, document_uuid=document.document_id,
        name=document.name, status=document.status, job_id=job.job_id,
    )


@router.post("/collections/{collection_id}/parse-preview", response_model=ParsePreviewResponse)
async def parse_preview(
    collection_id: int,
    user: SuperUser,
    file: UploadFile = File(...),
    strategy: str | None = Query(default=None, description="파싱 전략 override(미지정 시 컬렉션 기본)"),
    max_chars: int = Query(default=200_000, ge=1000, le=2_000_000, description="반환 텍스트 최대 길이"),
    session: AsyncSession = Depends(get_session),
):
    """업로드 파일을 **파싱만** 해서 결과 텍스트를 반환한다(저장·임베딩 없음 — 파싱 검증용).

    인제스천 전에 "이 파일이 어떻게 파싱되나"를 미리 확인하는 용도. ``strategy`` 미지정 시
    컬렉션의 ``parse_strategy`` 를 쓰고, 'auto' 는 파일 유형으로 자동 선택된다.
    """
    collection = await _assert_collection(session, collection_id)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    strat = strategy or collection.parse_strategy or "text"
    try:
        result = await service.parse_preview(
            file.filename or "untitled", data, strategy=strat, max_chars=max_chars
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=f"파싱 실패: {e}")
    return ParsePreviewResponse(**result)


# ---------------------------------------------------------------------------
# Register (NiFi 등 외부 파이프라인 — 서비스 토큰)
# ---------------------------------------------------------------------------

def _verify_service_token(x_ingestion_token: str | None = Header(default=None)) -> None:
    """NiFi register 용 서비스 토큰 검증.

    ``ingestion.service_token`` 이 비어 있으면(개발 기본) 인증을 강제하지 않는다.
    설정되어 있으면 ``X-Ingestion-Token`` 헤더가 일치해야 한다.
    """
    expected = settings.ingestion_service_token
    if not expected:
        return
    if x_ingestion_token != expected:
        raise HTTPException(status_code=401, detail="유효하지 않은 인제스천 서비스 토큰입니다.")


@router.post(
    "/ingestion/register",
    response_model=UploadResponse,
    status_code=202,
    dependencies=[Depends(_verify_service_token)],
)
async def register_document(req: RegisterRequest, session: AsyncSession = Depends(get_session)):
    """오브젝트 스토리지 경유 등록(NiFi). 원본은 이미 MinIO/S3 에 있고, URI·메타만 받는다.

    워커가 ``source_uri`` 에서 바이트를 당겨와 처리한다. ``content_hash`` 가 주어지고 동일
    문서가 이미 있으면 멱등하게 기존 문서의 잡만 새로 enqueue 한다.
    """
    await _assert_collection(session, req.collection_id)

    document = None
    if req.content_hash:
        document = await service.find_document_by_hash(
            session, req.collection_id, req.content_hash
        )

    if document is None:
        document = await service.create_pending_document(
            session,
            collection_id=req.collection_id,
            name=req.name,
            source_type=req.source_type,
            source_uri=req.source_uri,
            content_hash=req.content_hash,
            size_bytes=req.size_bytes,
            metadata_json=req.metadata_json,
            created_by="(ingestion/nifi)",
        )
    else:
        # 재등록 — 위치/상태 갱신 후 재처리
        document.source_uri = req.source_uri
        document.status = "registered"
        await session.commit()

    job = await service.enqueue_job(session, document.id, req.collection_id)
    return UploadResponse(
        document_id=document.id, document_uuid=document.document_id,
        name=document.name, status=document.status, job_id=job.job_id,
    )


# ---------------------------------------------------------------------------
# 잡 상태 / 재처리
# ---------------------------------------------------------------------------

@router.get("/collections/{collection_id}/ingest/jobs", response_model=list[IngestionJobResponse])
async def list_jobs(
    collection_id: int, _user: CurrentUser, session: AsyncSession = Depends(get_session),
):
    """컬렉션의 최근 인제스천 잡 목록(최신순)."""
    await _assert_collection(session, collection_id)
    jobs = await service.list_jobs_for_collection(session, collection_id)
    return [_job_response(j) for j in jobs]


@router.get("/ingestion/jobs/summary", response_model=JobsSummaryResponse)
async def jobs_summary(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    """잡 요약 집계(대기/진행중/24h 완료·실패/총계/진행중 단계별). 모니터링 카드용."""
    return JobsSummaryResponse(**await service.jobs_summary(session))


@router.get("/ingestion/transforms")
async def ingestion_transforms(_user: CurrentUser):
    """인제스천 파이프라인에 끼울 수 있는 보강(transform) 목록 — 레지스트리 introspection.

    파이프라인 구성 UI 가 이 목록으로 단계 추가 드롭다운/설정 폼을 동적 렌더한다.
    새 transform 을 등록하면 코드 변경 없이 여기에 자동 노출된다.
    """
    from app.ingestion.transforms import list_transforms

    return {"transforms": list_transforms()}


@router.get("/ingestion/jobs", response_model=PaginatedJobsResponse)
async def list_all_jobs(
    _user: CurrentUser,
    status: str | None = Query(default=None, description="queued|running|succeeded|failed"),
    collection_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """전역 인제스천 잡 목록(필터·페이지, 최신순) — 문서/컬렉션 이름 포함. 모니터링 페이지용."""
    rows, total = await service.list_jobs(
        session, status=status, collection_id=collection_id, page=page, page_size=page_size
    )
    items = [
        JobListItem(
            **_job_response(job).model_dump(),
            document_name=doc, collection_name=col, document_uuid=doc_uuid,
        )
        for job, doc, col, doc_uuid in rows
    ]
    return PaginatedJobsResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/ingestion/jobs/{job_id}", response_model=IngestionJobResponse)
async def get_job(job_id: str, _user: CurrentUser, session: AsyncSession = Depends(get_session)):
    """잡 단건 상태(진행률 폴링용). 없으면 404."""
    job = await service.get_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="인제스천 잡을 찾을 수 없습니다.")
    return _job_response(job)


@router.post("/documents/{document_uuid}/reindex", response_model=UploadResponse, status_code=202)
async def reindex_document(
    document_uuid: str, _user: SuperUser, session: AsyncSession = Depends(get_session),
):
    """기존 문서를 재처리한다(기존 청크 교체). 원본은 그대로 두고 잡만 새로 enqueue."""
    document = (await session.execute(
        select(RagDocument).where(RagDocument.document_id == document_uuid)
    )).scalars().first()
    if not document:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    document.status = "registered"
    await session.commit()
    job = await service.enqueue_job(session, document.id, document.collection_id)
    return UploadResponse(
        document_id=document.id, document_uuid=document.document_id,
        name=document.name, status=document.status, job_id=job.job_id,
    )
