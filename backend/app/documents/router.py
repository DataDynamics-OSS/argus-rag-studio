# SPDX-License-Identifier: Apache-2.0
"""문서(Document) API.

문서는 컬렉션에 종속되므로 라우트는 ``/collections/{collection_id}/documents`` 아래에
중첩된다. 단건 작업(조회/수정/삭제)은 ``/documents/{document_id}`` 평면 경로도 제공한다.

권한 정책:
    - 조회(GET): 로그인 사용자
    - 등록/수정: 슈퍼유저 또는 관리자
    - 삭제: 생성자 본인 또는 관리자
"""

import json
import logging

import mimetypes

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections.models import RagCollection
from app.core.auth import CurrentUser, SuperUser, assert_owner_or_admin
from app.core.database import get_session
from app.documents import service
from app.documents.models import RagDocument
from app.s3browse import office_pdf as office_pdf_mod
from app.documents.schemas import (
    ChunkPreviewRequest,
    DocumentChunksResponse,
    DocumentCreateRequest,
    DocumentResponse,
    DocumentUpdateRequest,
    PaginatedDocumentResponse,
)
from app.chunks.models import RagChunk
from app.documents import evidence
from app.ingestion import service as ingestion_service
from app.ingestion.schemas import ChunkPreviewResponse, ParsePreviewResponse
from app.storage.client import get_object

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])


async def _assert_collection(session: AsyncSession, collection_id: int) -> RagCollection:
    """컬렉션 존재를 검증하고 반환한다. 없으면 404."""
    collection = (await session.execute(
        select(RagCollection).where(RagCollection.id == collection_id)
    )).scalars().first()
    if not collection:
        raise HTTPException(status_code=404, detail="컬렉션을 찾을 수 없습니다.")
    return collection


# ---------------------------------------------------------------------------
# 컬렉션 종속 경로
# ---------------------------------------------------------------------------

@router.post(
    "/collections/{collection_id}/documents",
    response_model=DocumentResponse,
    status_code=201,
)
async def create_document(
    collection_id: int, req: DocumentCreateRequest, user: SuperUser,
    session: AsyncSession = Depends(get_session),
):
    """컬렉션에 문서를 등록한다(M1: 메타데이터). 컬렉션이 없으면 404."""
    await _assert_collection(session, collection_id)
    return await service.create_document(session, collection_id, req, created_by=user.username)


@router.get(
    "/collections/{collection_id}/documents",
    response_model=PaginatedDocumentResponse,
)
async def list_documents(
    collection_id: int,
    _user: CurrentUser,
    status: str | None = Query(None, description="Filter by status"),
    search: str | None = Query(None, description="Search document name"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=0, le=200),
    session: AsyncSession = Depends(get_session),
):
    """특정 컬렉션의 문서 목록을 반환한다."""
    await _assert_collection(session, collection_id)
    return await service.list_documents(
        session, collection_id, status=status, search=search, page=page, page_size=page_size,
    )


# ---------------------------------------------------------------------------
# 단건 평면 경로
# ---------------------------------------------------------------------------

@router.get("/documents/{document_uuid}", response_model=DocumentResponse)
async def get_document(
    document_uuid: str, _user: CurrentUser, session: AsyncSession = Depends(get_session),
):
    """외부 노출 UUID(document_id)로 문서 단건 조회. 없으면 404."""
    document = await service.get_document_by_uuid(session, document_uuid)
    if not document:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    return document


@router.get("/documents/{document_uuid}/chunks", response_model=DocumentChunksResponse)
async def list_document_chunks(
    document_uuid: str,
    _user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=0, le=200),
    session: AsyncSession = Depends(get_session),
):
    """문서의 인제스천 현황(상태·단계·오류) + 청크 목록(임베딩 유무 포함)."""
    document = (await session.execute(
        select(RagDocument).where(RagDocument.document_id == document_uuid)
    )).scalars().first()
    if not document:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    return await service.list_document_chunks(session, document, page=page, page_size=page_size)


def _stored_image_classification(document: RagDocument) -> dict | None:
    """문서 metadata 의 저장된 VLM 분석 결과 — 청킹 미리보기의 image_captions 주입용."""
    try:
        meta = json.loads(document.metadata_json) if document.metadata_json else {}
        clf = meta.get("image_classification")
        return clf if isinstance(clf, dict) else None
    except (ValueError, TypeError):
        return None


@router.get("/documents/{document_uuid}/parse-preview", response_model=ParsePreviewResponse)
async def parse_preview_document(
    document_uuid: str,
    _user: CurrentUser,
    strategy: str | None = Query(default=None, description="파싱 전략 override(미지정 시 컬렉션 기본)"),
    max_chars: int = Query(default=200_000, ge=1000, le=2_000_000, description="반환 텍스트 최대 길이"),
    session: AsyncSession = Depends(get_session),
):
    """이미 등록된 문서의 원본을 **다시 파싱만** 해서 결과 텍스트를 반환한다(저장·임베딩 없음).

    인제스천된 문서가 실제로 어떻게 파싱됐는지 사후 검증하는 용도. ``strategy`` 미지정 시
    컬렉션의 ``parse_strategy`` 를 쓴다(다른 전략과 결과 비교에도 사용).
    """
    document = (await session.execute(
        select(RagDocument).where(RagDocument.document_id == document_uuid)
    )).scalars().first()
    if not document:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    if not document.source_uri:
        raise HTTPException(status_code=404, detail="원본이 없어 파싱할 수 없습니다(source_uri 없음).")
    collection = await _assert_collection(session, document.collection_id)
    data = await get_object(document.source_uri)
    strat = strategy or collection.parse_strategy or "text"
    try:
        result = await ingestion_service.parse_preview(
            document.name, data, strategy=strat, max_chars=max_chars
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=f"파싱 실패: {e}")
    return ParsePreviewResponse(**result)


@router.get("/documents/{document_uuid}/chunk-preview", response_model=ChunkPreviewResponse)
async def chunk_preview_document(
    document_uuid: str,
    _user: CurrentUser,
    parse_strategy: str | None = Query(default=None, description="파싱 전략(미지정 시 컬렉션 기본)"),
    strategy: str | None = Query(default=None, description="청킹 전략 override"),
    chunk_size: int | None = Query(default=None, ge=1, description="청크 크기 override"),
    chunk_overlap: int | None = Query(default=None, ge=0, description="오버랩 override"),
    chunk_unit: str | None = Query(default=None, description="char | token"),
    max_chars: int = Query(default=200_000, ge=1000, le=2_000_000),
    session: AsyncSession = Depends(get_session),
):
    """청킹 전(전문) / 청킹 후(청크) 를 함께 반환한다(저장·임베딩 없이 재파싱+재청킹).

    전략·크기·오버랩을 override 하면 라이브로 다른 청킹 결과를 비교할 수 있다. 각 청크는
    본문 내 위치(char_start/char_end)를 담아 전문 위 구간 하이라이트가 가능하다.
    """
    document = await _require_document(session, document_uuid)
    if not document.source_uri:
        raise HTTPException(status_code=404, detail="원본이 없어 청킹할 수 없습니다(source_uri 없음).")
    collection = await _assert_collection(session, document.collection_id)
    data = await get_object(document.source_uri)
    try:
        result = await ingestion_service.chunk_preview(
            document.name, data, collection,
            parse_strategy=parse_strategy, strategy=strategy,
            chunk_size=chunk_size, chunk_overlap=chunk_overlap, chunk_unit=chunk_unit,
            image_classification=_stored_image_classification(document),
            max_chars=max_chars,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=f"청킹 실패: {e}")
    return ChunkPreviewResponse(**result)


@router.get("/documents/by-chunk/{chunk_id}/evidence")
async def chunk_evidence_page(
    chunk_id: str, _user: CurrentUser, session: AsyncSession = Depends(get_session),
):
    """검색 결과(청크)의 근거 — 원본 HWP/HWPX 의 해당 페이지 번호를 추정해 반환한다.

    청크 텍스트를 렌더 서비스의 페이지별 텍스트와 매칭해 페이지를 찾는다. 페이지 이미지는
    ``GET /documents/{uuid}/page/{n}`` 로 가져온다. HWP/HWPX 외/렌더 서비스 미설정이면 available=false.
    """
    chunk = (await session.execute(
        select(RagChunk).where(RagChunk.chunk_id == chunk_id)
    )).scalars().first()
    if not chunk:
        raise HTTPException(status_code=404, detail="청크를 찾을 수 없습니다.")
    document = (await session.execute(
        select(RagDocument).where(RagDocument.id == chunk.document_id)
    )).scalars().first()
    if not document:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")

    base = {"document_uuid": document.document_id, "document_name": document.name}
    if not evidence.is_hwp(document.name):
        return {**base, "available": False, "reason": "HWP/HWPX 문서만 지원합니다."}
    if not evidence.available() or not document.source_uri:
        return {**base, "available": False, "reason": "렌더 서비스 미설정 또는 원본 없음."}
    try:
        data = await get_object(document.source_uri)
        info = await evidence.pages_text(document.content_hash or document.document_id, data)
        page = evidence.best_page(chunk.text, info.get("page_texts") or [])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"근거 페이지 조회 실패: {e}")
    return {**base, "available": True, "page": page, "total_pages": info.get("page_count")}


@router.get("/documents/{document_uuid}/page/{page_no}")
async def document_page_image(
    document_uuid: str, page_no: int, _user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    """HWP/HWPX 원본의 page_no(1-base) 페이지를 PNG 로 렌더해 반환한다(렌더 서비스 경유)."""
    document = await _require_document(session, document_uuid)
    if not evidence.is_hwp(document.name):
        raise HTTPException(status_code=400, detail="HWP/HWPX 문서만 지원합니다.")
    if not evidence.available() or not document.source_uri:
        raise HTTPException(status_code=503, detail="렌더 서비스 미설정 또는 원본 없음.")
    try:
        data = await get_object(document.source_uri)
        png = await evidence.render_page(data, max(1, page_no))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"페이지 렌더 실패: {e}")
    return Response(content=png, media_type="image/png")


@router.post("/documents/{document_uuid}/chunk-preview", response_model=ChunkPreviewResponse)
async def chunk_preview_draft(
    document_uuid: str,
    req: ChunkPreviewRequest,
    _user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    """드래프트 인제스천 파이프라인으로 미리보기(저장·재인덱싱 없이). 파이프라인 구성 UI 가 사용.

    ``post_parse``/``post_chunk`` 를 주면 컬렉션 저장값 대신 그 draft 보강을 적용해 청크를 보여준다.
    """
    document = await _require_document(session, document_uuid)
    if not document.source_uri:
        raise HTTPException(status_code=404, detail="원본이 없어 청킹할 수 없습니다(source_uri 없음).")
    collection = await _assert_collection(session, document.collection_id)
    data = await get_object(document.source_uri)
    pipeline = None
    if req.post_parse is not None or req.post_chunk is not None:
        pipeline = {"post_parse": req.post_parse or [], "post_chunk": req.post_chunk or []}
    try:
        result = await ingestion_service.chunk_preview(
            document.name, data, collection,
            parse_strategy=req.parse_strategy, strategy=req.strategy,
            chunk_size=req.chunk_size, chunk_overlap=req.chunk_overlap, chunk_unit=req.chunk_unit,
            pipeline=pipeline, image_classification=_stored_image_classification(document),
            max_chars=req.max_chars,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=f"청킹 실패: {e}")
    return ChunkPreviewResponse(**result)


_OFFICE_PDF_EXTS = {"doc", "docx", "ppt", "pptx", "xls", "xlsx"}


async def _require_document(session: AsyncSession, document_uuid: str) -> RagDocument:
    document = (await session.execute(
        select(RagDocument).where(RagDocument.document_id == document_uuid)
    )).scalars().first()
    if not document:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    return document


@router.get("/documents/{document_uuid}/file")
async def get_document_file(
    document_uuid: str, _user: CurrentUser, session: AsyncSession = Depends(get_session),
):
    """원본 파일 바이트를 동일출처로 반환한다(파일 보기 — 로그인 사용자 누구나)."""
    document = await _require_document(session, document_uuid)
    if not document.source_uri:
        raise HTTPException(status_code=404, detail="원본이 없습니다(source_uri 없음).")
    data = await get_object(document.source_uri)
    mime, _ = mimetypes.guess_type(document.name)
    return Response(content=data, media_type=mime or "application/octet-stream")


@router.get("/documents/{document_uuid}/office-pdf")
async def get_document_office_pdf(
    document_uuid: str, _user: CurrentUser, session: AsyncSession = Depends(get_session),
):
    """오피스 원본을 PDF 로 변환해 반환(고충실도 파일 보기). 미설치면 501 → 프런트가 폴백."""
    document = await _require_document(session, document_uuid)
    if not document.source_uri:
        raise HTTPException(status_code=404, detail="원본이 없습니다(source_uri 없음).")
    ext = document.name.rsplit(".", 1)[-1].lower() if "." in document.name else ""
    if ext not in _OFFICE_PDF_EXTS:
        raise HTTPException(status_code=400, detail=f"오피스 변환 대상이 아님: .{ext}")
    if not office_pdf_mod.is_available():
        raise HTTPException(status_code=501, detail="LibreOffice 미설치 — 고충실도 변환 불가")
    data = await get_object(document.source_uri)
    try:
        pdf = await office_pdf_mod.convert_to_pdf(data, ext)
    except Exception as e:  # noqa: BLE001
        logger.warning("문서 오피스 PDF 변환 실패 uuid=%s err=%s", document_uuid, e)
        raise HTTPException(status_code=500, detail=f"변환 실패: {e}")
    return Response(content=pdf, media_type="application/pdf")


@router.put("/documents/{document_uuid}", response_model=DocumentResponse)
async def update_document(
    document_uuid: str, req: DocumentUpdateRequest, _user: SuperUser,
    session: AsyncSession = Depends(get_session),
):
    """문서 메타데이터/상태 부분 갱신."""
    found = (await session.execute(
        select(RagDocument).where(RagDocument.document_id == document_uuid)
    )).scalars().first()
    document = await service.update_document(session, found.id, req) if found else None
    if not document:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    return document


@router.delete("/documents/{document_uuid}")
async def delete_document(
    document_uuid: str, user: CurrentUser, session: AsyncSession = Depends(get_session),
):
    """문서 삭제. 생성자 본인 또는 관리자만 허용."""
    row = (await session.execute(
        select(RagDocument).where(RagDocument.document_id == document_uuid)
    )).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    assert_owner_or_admin(user, row.created_by, "이 문서")
    await service.delete_document(session, row.id)
    return {"status": "ok", "message": "Document deleted"}
