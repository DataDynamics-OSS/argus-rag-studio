# SPDX-License-Identifier: Apache-2.0
"""어노테이션 API.

이미지 업로드 → 웹 UI 에서 bbox/텍스트 라벨링 → AI-Hub 손글씨 OCR 포맷으로 내보내기.

엔드포인트:
    - POST   /annotations/images                  이미지 업로드(multipart) → MinIO 적재 → 등록
    - GET    /annotations/images                  목록(상태/컬렉션/검색 필터, 페이지네이션)
    - GET    /annotations/images/{image_id}       단건 상세(메타 + 박스)
    - GET    /annotations/images/{image_id}/file  원본 이미지 바이트(동일출처 프록시)
    - PUT    /annotations/images/{image_id}       메타/상태/컬렉션 갱신
    - PUT    /annotations/images/{image_id}/boxes 박스 일괄 교체(자동저장)
    - POST   /annotations/images/{image_id}/detect 자동 bbox 인식(검출 서버 호출 → 후보 반환)
    - DELETE /annotations/images/{image_id}       삭제
    - GET    /annotations/images/{image_id}/export  AI-Hub JSON 다운로드
    - POST   /annotations/import                  기존 AI-Hub JSON 가져오기
"""

import asyncio
import hashlib
import json
import logging
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel

from app.annotations import aihub, convert, crops, detect, service, storage
from app.annotations.schemas import (
    AnnotationDetailResponse,
    BoxesUpdateRequest,
    DetectedBoxItem,
    DetectResponse,
    ImageUpdateRequest,
    PaginatedImagesResponse,
    UploadImageResponse,
)
from app.core.auth import CurrentUser, assert_owner_or_admin
from app.core.config import settings
from app.core.database import get_session
from app.storage.client import get_object

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/annotations", tags=["annotations"])

_ALLOWED_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/bmp", "image/tiff"}


async def _require_image(session: AsyncSession, image_id: str):
    img = await service.get_image(session, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")
    return img


@router.post("/images", response_model=UploadImageResponse, status_code=201)
async def upload_image(
    user: CurrentUser,
    file: UploadFile = File(...),
    width: int = Form(...),
    height: int = Form(...),
    collection_id: int | None = Form(default=None),
    folder: str = Form(default=""),
    relative_path: str | None = Form(default=None),
    overwrite: bool = Form(default=False),
    session: AsyncSession = Depends(get_session),
):
    """이미지 업로드 → 어노테이션 버킷 적재 → 어노테이션 작업(draft) 생성.

    width/height 는 클라이언트가 로드한 원본 픽셀 크기(naturalWidth/Height)다.
    folder 는 업로드 대상 폴더(루트=''). relative_path 가 있으면(폴더 구조 업로드)
    그 하위 경로를 folder 에 합쳐 폴더 트리를 그대로 재현한다.
    overwrite=true 면 같은 폴더의 동일 파일명을 먼저 삭제하고 새로 만든다(재변환 덮어쓰기).
    """
    if file.content_type and file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 이미지 형식입니다: {file.content_type}")
    if width <= 0 or height <= 0:
        raise HTTPException(status_code=400, detail="유효한 이미지 크기(width/height)가 필요합니다.")

    # folder 결정 — relative_path("sub/dir/img.png")의 디렉터리를 base folder 에 합친다.
    base = storage.norm_folder(folder)
    filename = file.filename or "image.png"
    if relative_path:
        rel = relative_path.replace("\\", "/").strip("/")
        sub = os.path.dirname(rel)
        filename = os.path.basename(rel) or filename
        target_folder = storage.norm_folder(f"{base}/{sub}" if sub else base)
    else:
        target_folder = base

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    content_hash = hashlib.sha256(data).hexdigest()

    dup = await service.find_image_by_folder_name(session, target_folder, filename)
    overwritten = False
    if dup:
        if not overwrite:
            raise HTTPException(
                status_code=409,
                detail=f"같은 폴더에 동일한 파일명이 이미 있습니다: {filename}",
            )
        # 덮어쓰기 — 기존 레코드/객체(원본·썸네일·라벨 사이드카)를 제거하고 새로 만든다.
        await service.delete_image(session, dup)
        overwritten = True

    img = await service.create_image(
        session,
        filename=filename,
        source_uri=None,
        content_type=file.content_type,
        content_hash=content_hash,
        width=width,
        height=height,
        size_bytes=len(data),
        collection_id=collection_id,
        created_by=user.username,
        folder=target_folder,
    )

    key = service.build_object_key(target_folder, filename)
    img.source_uri = await storage.put_image(key, data, content_type=file.content_type)
    await session.commit()

    return UploadImageResponse(
        id=img.id, image_id=img.image_id, filename=img.filename,
        width=img.width, height=img.height, status=img.status,
        overwritten=overwritten,
    )


class ConvertConfigResponse(BaseModel):
    hwp_engine: str          # "rhwp"(클라이언트) | "libreoffice"(서버)
    hwp_scale: float         # rhwp 클라이언트 렌더 배율
    dpi: int                 # 서버 변환 해상도(참고용)


@router.get("/convert-config", response_model=ConvertConfigResponse)
async def convert_config(user: CurrentUser):
    """문서 변환 클라이언트 설정 — HWP 엔진/배율 등. 인증된 사용자 누구나 조회 가능.

    (전역 설정은 admin 전용 /settings 에서 변경하지만, 라벨링 사용자도 변환 동작을
    결정하려면 이 값이 필요하므로 어노테이션 범위에서 읽기 전용으로 노출한다.)"""
    return ConvertConfigResponse(
        hwp_engine=settings.image_conversion_hwp_engine,
        hwp_scale=settings.image_conversion_hwp_scale,
        dpi=settings.image_conversion_dpi,
    )


class ConvertedImage(BaseModel):
    image_id: str
    filename: str
    width: int
    height: int


class ConvertDocumentResponse(BaseModel):
    filename: str            # 원본 문서명
    pages: int               # 변환된 총 페이지 수
    created: int             # 등록된 페이지 이미지 수(신규+덮어쓰기)
    overwritten: int         # 동일 파일명을 덮어쓴 수(재변환)
    images: list[ConvertedImage]


@router.post("/convert-document", response_model=ConvertDocumentResponse, status_code=201)
async def convert_document(
    user: CurrentUser,
    file: UploadFile = File(...),
    collection_id: int | None = Form(default=None),
    folder: str = Form(default=""),
    dpi: int | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
):
    """문서(PDF·오피스·HWP)를 페이지별 이미지(PNG)로 변환해 현재 폴더에 업로드한다.

    PDF 는 그대로, 오피스/HWP 류는 LibreOffice 로 PDF 변환 후 PyMuPDF 로 페이지를
    래스터화한다. 각 페이지는 ``{문서명}_p001.png`` 식으로 어노테이션 작업(draft)으로 등록되며,
    같은 폴더에 동일 파일명이 이미 있으면 덮어쓴다(재변환 — 기존 페이지 교체)."""
    filename = file.filename or "document"
    if not convert.is_supported(filename):
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 문서 형식입니다. 지원: {', '.join(convert.SUPPORTED_DOC_EXTS)}",
        )
    if dpi is None:
        dpi = settings.image_conversion_dpi
    if dpi < 36 or dpi > 600:
        raise HTTPException(status_code=400, detail="dpi 는 36~600 범위여야 합니다.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")

    # 1) 문서 → PDF (오피스/HWP 는 LibreOffice). soffice 미설치/미지원 포맷은 여기서 실패.
    try:
        pdf = await convert.to_pdf(filename, data)
    except Exception as e:  # noqa: BLE001 — 변환 도구 부재/포맷 미지원 등
        logger.warning("문서→PDF 변환 실패: %s (%s)", filename, e)
        raise HTTPException(status_code=502, detail=f"문서를 PDF 로 변환하지 못했습니다: {e}")

    # 2) PDF → 페이지 이미지(블로킹 작업이라 스레드로)
    try:
        pages = await asyncio.to_thread(convert.render_pdf, pdf, dpi)
    except Exception as e:  # noqa: BLE001 — 렌더링 실패(손상 PDF 등)
        logger.warning("PDF 래스터화 실패: %s (%s)", filename, e)
        raise HTTPException(status_code=500, detail=f"페이지 이미지 변환에 실패했습니다: {e}")
    if not pages:
        raise HTTPException(status_code=422, detail="변환된 페이지가 없습니다.")

    # 3) 각 페이지를 어노테이션 이미지로 등록 + 썸네일 생성
    base = storage.norm_folder(folder)
    stem = os.path.splitext(os.path.basename(filename))[0] or "document"
    width = max(3, len(str(len(pages))))  # 페이지 번호 자리수(최소 3)
    created: list[ConvertedImage] = []
    overwritten = 0
    for i, page in enumerate(pages, start=1):
        page_name = f"{stem}_p{str(i).zfill(width)}.png"
        # 재변환 덮어쓰기 — 동일 파일명이 있으면 기존 레코드/객체를 먼저 제거한다.
        dup = await service.find_image_by_folder_name(session, base, page_name)
        if dup:
            await service.delete_image(session, dup)
            overwritten += 1
        content_hash = hashlib.sha256(page.png).hexdigest()
        img = await service.create_image(
            session,
            filename=page_name,
            source_uri=None,
            content_type="image/png",
            content_hash=content_hash,
            width=page.width,
            height=page.height,
            size_bytes=len(page.png),
            collection_id=collection_id,
            created_by=user.username,
            folder=base,
        )
        key = service.build_object_key(base, page_name)
        img.source_uri = await storage.put_image(key, page.png, content_type="image/png")
        await session.commit()
        # 썸네일 — 실패해도 등록은 유지(편집기 진입 시 백필 가능).
        try:
            await service.set_thumbnail(session, img, page.thumb, "image/png")
        except Exception as e:  # noqa: BLE001
            logger.warning("변환 썸네일 생성 실패(무시): %s (%s)", page_name, e)
        created.append(ConvertedImage(
            image_id=img.image_id, filename=page_name,
            width=page.width, height=page.height,
        ))

    logger.info(
        "문서 변환 완료: %s pages=%d created=%d overwritten=%d folder=%s",
        filename, len(pages), len(created), overwritten, base or "(루트)",
    )
    return ConvertDocumentResponse(
        filename=filename, pages=len(pages),
        created=len(created), overwritten=overwritten, images=created,
    )


@router.get("/images", response_model=PaginatedImagesResponse)
async def list_images(
    user: CurrentUser,
    status: str | None = Query(default=None),
    collection_id: int | None = Query(default=None),
    search: str | None = Query(default=None),
    folder: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    """이미지 목록. ``folder`` 가 주어지면 그 폴더의 이미지만(루트='')."""
    return await service.list_images(
        session, status=status, collection_id=collection_id,
        search=search, folder=folder, page=page, page_size=page_size,
    )


class FolderCreateRequest(BaseModel):
    path: str


@router.get("/folders")
async def list_folders(user: CurrentUser, parent: str | None = Query(default=None)):
    """parent 바로 아래 자식 폴더 경로 목록(탐색기 좌측 트리)."""
    return {"folders": await service.list_child_folders(parent)}


@router.post("/folders", status_code=201)
async def create_folder(req: FolderCreateRequest, user: CurrentUser):
    path = storage.norm_folder(req.path)
    if not path:
        raise HTTPException(status_code=400, detail="폴더 경로가 비어 있습니다.")
    await service.create_folder(path)
    return {"path": path}


@router.delete("/folders")
async def delete_folder(
    user: CurrentUser,
    path: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    """폴더(하위 포함) 삭제 — 폴더 내 이미지·박스도 함께 제거."""
    norm = storage.norm_folder(path)
    if not norm:
        raise HTTPException(status_code=400, detail="루트 폴더는 삭제할 수 없습니다.")
    count = await service.delete_folder(session, norm)
    return {"path": norm, "deleted_images": count}


@router.get("/images/{image_id}", response_model=AnnotationDetailResponse)
async def get_image_detail(
    image_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    img = await _require_image(session, image_id)
    return await service.get_detail(session, img)


@router.get("/images/{image_id}/file")
async def get_image_file(
    image_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    """원본 이미지 바이트를 반환한다(캔버스 배경용 동일출처 프록시)."""
    img = await _require_image(session, image_id)
    if not img.source_uri:
        raise HTTPException(status_code=404, detail="이미지 원본이 없습니다.")
    data = await get_object(img.source_uri)
    return Response(content=data, media_type=img.content_type or "application/octet-stream")


_OBJECT_MEDIA = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff",
}


@router.get("/object")
async def get_object_bytes(
    user: CurrentUser,
    key: str = Query(..., description="어노테이션 버킷 내 이미지 오브젝트 키"),
):
    """DB 미등록 이미지 오브젝트(예: 분할 크롭) 바이트를 키로 직접 반환한다(읽기전용 미리보기)."""
    ext = os.path.splitext(key)[1].lower()
    media = _OBJECT_MEDIA.get(ext)
    if not media:
        raise HTTPException(status_code=400, detail="이미지 오브젝트만 조회할 수 있습니다.")
    try:
        data = await get_object(storage.build_source_uri(key))
    except Exception:
        raise HTTPException(status_code=404, detail="오브젝트를 찾을 수 없습니다.")
    return Response(content=data, media_type=media)


@router.get("/images/{image_id}/thumbnail")
async def get_image_thumbnail(
    image_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    """썸네일 바이트를 반환한다. 없으면 404(프론트는 원본으로 폴백)."""
    img = await _require_image(session, image_id)
    if not img.thumb_uri:
        raise HTTPException(status_code=404, detail="썸네일이 없습니다.")
    data = await get_object(img.thumb_uri)
    return Response(content=data, media_type="image/jpeg")


@router.post("/images/{image_id}/thumbnail", status_code=201)
async def upload_image_thumbnail(
    image_id: str,
    user: CurrentUser,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """클라이언트가 생성한 썸네일을 저장한다(업로드 시·편집기 진입 시)."""
    img = await _require_image(session, image_id)
    assert_owner_or_admin(user, img.created_by, "이 이미지")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 썸네일입니다.")
    await service.set_thumbnail(session, img, data, file.content_type or "image/jpeg")
    return {"image_id": image_id, "has_thumbnail": True}


@router.put("/images/{image_id}", response_model=AnnotationDetailResponse)
async def update_image(
    image_id: str,
    req: ImageUpdateRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    img = await _require_image(session, image_id)
    assert_owner_or_admin(user, img.created_by, "이 이미지")
    await service.update_image(
        session, img,
        status=req.status,
        collection_id=req.collection_id,
        meta=req.meta,
        set_collection="collection_id" in req.model_fields_set,
    )
    return await service.get_detail(session, img)


@router.put("/images/{image_id}/boxes", response_model=AnnotationDetailResponse)
async def update_boxes(
    image_id: str,
    req: BoxesUpdateRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    img = await _require_image(session, image_id)
    assert_owner_or_admin(user, img.created_by, "이 이미지")

    # seq 유니크 검증 — 일괄 교체 전 빠른 실패
    seqs = [b.seq for b in req.boxes]
    if len(set(seqs)) != len(seqs):
        raise HTTPException(status_code=400, detail="박스 seq 가 중복되었습니다.")
    # 좌표가 이미지 경계를 벗어나지 않도록 clamp
    for b in req.boxes:
        b.x1 = max(0, min(b.x1, img.width))
        b.x2 = max(0, min(b.x2, img.width))
        b.y1 = max(0, min(b.y1, img.height))
        b.y2 = max(0, min(b.y2, img.height))

    await service.replace_boxes(session, img, req.boxes)
    return await service.get_detail(session, img)


@router.post("/images/{image_id}/detect", response_model=DetectResponse)
async def detect_boxes(
    image_id: str,
    user: CurrentUser,
    with_text: bool = Query(default=True),
    min_score: float | None = Query(default=None, ge=0, le=1),
    session: AsyncSession = Depends(get_session),
):
    """자동 bbox 인식 — 원본 이미지를 검출 서버(PaddleOCR)로 보내 텍스트 박스를 받는다.

    결과는 **저장하지 않고 후보로만 반환**한다(seq 는 1부터 임시 부여). 프론트가 화면에서
    검수한 뒤 기존 ``PUT .../boxes`` 로 확정 저장한다. ``with_text=false`` 면 좌표만 검출."""
    img = await _require_image(session, image_id)
    if not img.source_uri:
        raise HTTPException(status_code=404, detail="이미지 원본이 없습니다.")
    data = await get_object(img.source_uri)

    try:
        raw = await detect.detect_boxes(
            data, img.content_type, min_score=min_score, with_text=with_text
        )
    except detect.DetectionError as e:
        # 비활성/연결 실패/서버 오류 → 503(프론트는 안내 토스트)
        raise HTTPException(status_code=503, detail=str(e))

    # 좌표를 이미지 경계로 clamp 하고, 면적이 없는 박스는 버린다. seq 는 1부터 임시 부여.
    out: list[DetectedBoxItem] = []
    seq = 1
    for b in raw:
        try:
            x1 = max(0, min(int(b["x1"]), img.width))
            x2 = max(0, min(int(b["x2"]), img.width))
            y1 = max(0, min(int(b["y1"]), img.height))
            y2 = max(0, min(int(b["y2"]), img.height))
        except (KeyError, TypeError, ValueError):
            continue
        if x2 - x1 < 1 or y2 - y1 < 1:
            continue
        out.append(DetectedBoxItem(
            seq=seq, data=str(b.get("text", "")),
            x1=x1, y1=y1, x2=x2, y2=y2, score=float(b.get("score", 0.0)),
        ))
        seq += 1
    return DetectResponse(boxes=out)


@router.delete("/images/{image_id}", status_code=204)
async def delete_image(
    image_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    img = await _require_image(session, image_id)
    assert_owner_or_admin(user, img.created_by, "이 이미지")
    await service.delete_image(session, img)
    return Response(status_code=204)


@router.get("/images/{image_id}/export")
async def export_image(
    image_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    """AI-Hub 손글씨 OCR 포맷 JSON 으로 내보낸다(다운로드)."""
    img = await _require_image(session, image_id)
    boxes = await service.get_boxes(session, img.id)
    payload = aihub.build_export(
        filename=img.filename, width=img.width, height=img.height,
        meta=img.meta_json, boxes=boxes,
    )
    stem = os.path.splitext(img.filename)[0] or "annotation"
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        content=body,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}.json"'},
    )


class CropExportResponse(BaseModel):
    images: int
    crops: int
    skipped_boxes: int
    location: str  # 크롭이 저장된 오브젝트 스토리지 위치(s3://bucket/{folder}/{stem}/)


@router.post("/images/{image_id}/crops", response_model=CropExportResponse)
async def export_image_crops(
    image_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    """이미지 분할 — 각 bbox 를 원본에서 잘라 학습용 크롭 PNG + manifest/SFT JSONL 을
    **원본 이미지와 같은 버킷의 ``{이미지폴더}/{파일명}/`` 디렉터리**에 저장한다.

    bbox 가 하나도 없으면 400. 같은 이미지를 다시 분할하면 그 디렉터리를 최신 박스로
    갱신하고(크롭 덮어쓰기 + JSONL 재작성), 삭제된 박스의 고아 크롭은 제거한다.
    """
    img = await _require_image(session, image_id)
    boxes = await service.get_boxes(session, img.id)
    if not boxes:
        raise HTTPException(status_code=400, detail="분할할 bbox 가 없습니다. 먼저 박스를 추가하세요.")
    if not img.source_uri:
        raise HTTPException(status_code=404, detail="이미지 원본이 없습니다.")

    data = await get_object(img.source_uri)
    stem = os.path.splitext(img.filename)[0] or "image"
    # 크롭 디렉터리 — 원본 이미지가 있는 폴더 아래 파일명(stem) 디렉터리.
    img_folder = storage.norm_folder(img.folder)
    crop_folder = f"{img_folder}/{stem}" if img_folder else stem

    # ORM 박스를 평범한 값 객체로 복사(스레드에서 ORM 속성 접근 → MissingGreenlet 방지).
    crop_boxes = [crops.CropBox.from_orm(b) for b in boxes]
    rendered, skipped = await asyncio.to_thread(crops.render_crops, data, crop_boxes, stem)

    # 1) 크롭 PNG 업로드
    new_names = set()
    for c in rendered:
        await storage.put_image(storage.build_key(crop_folder, c.filename), c.png, content_type="image/png")
        new_names.add(c.filename)

    # 2) manifest/SFT JSONL 재작성(현재 박스 기준 전체 덮어쓰기)
    await storage.put_json(
        storage.build_key(crop_folder, crops.MANIFEST_NAME), crops.build_jsonl(rendered, sft=False)
    )
    await storage.put_json(
        storage.build_key(crop_folder, crops.SFT_NAME), crops.build_jsonl(rendered, sft=True)
    )

    # 3) 삭제된 박스의 고아 크롭(`{stem}_<숫자>.png`) 정리 — 현재 세트에 없는 것만 삭제.
    for key in await storage.list_object_keys(crop_folder):
        base = key.rsplit("/", 1)[-1]
        if crops.is_crop_filename(base, stem) and base not in new_names:
            await storage.delete_object(key)

    location = storage.build_source_uri(f"{storage.norm_folder(crop_folder)}/")
    return CropExportResponse(images=1, crops=len(rendered), skipped_boxes=skipped, location=location)


@router.post("/import", response_model=UploadImageResponse, status_code=201)
async def import_annotation(
    user: CurrentUser,
    json_file: UploadFile = File(...),
    image_file: UploadFile | None = File(default=None),
    collection_id: int | None = Form(default=None),
    folder: str = Form(default=""),
    session: AsyncSession = Depends(get_session),
):
    """기존 AI-Hub JSON(+선택 이미지)을 가져와 어노테이션 작업으로 등록한다."""
    try:
        payload = json.loads(await json_file.read())
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"JSON 파싱 실패: {e}")

    meta, raw_boxes, width, height = aihub.parse_import(payload)
    target_folder = storage.norm_folder(folder)

    image_bytes = await image_file.read() if image_file else b""
    content_hash = hashlib.sha256(image_bytes).hexdigest() if image_bytes else None

    images_block = meta.get("Images", {})
    filename = (
        (image_file.filename if image_file else None)
        or (str(images_block.get("identifier")) + "." + str(images_block.get("type", "png")))
    )

    dup = await service.find_image_by_folder_name(session, target_folder, filename)
    if dup:
        raise HTTPException(
            status_code=409,
            detail=f"같은 폴더에 동일한 파일명이 이미 있습니다: {filename}",
        )

    img = await service.create_image(
        session,
        filename=filename,
        source_uri=None,
        content_type=(image_file.content_type if image_file else None),
        content_hash=content_hash,
        width=width,
        height=height,
        size_bytes=len(image_bytes),
        collection_id=collection_id,
        created_by=user.username,
        folder=target_folder,
    )
    img.meta_json = meta
    if image_bytes:
        key = service.build_object_key(target_folder, filename)
        img.source_uri = await storage.put_image(key, image_bytes, content_type=img.content_type)
    await session.commit()

    if raw_boxes:
        from app.annotations.schemas import BoxItem
        await service.replace_boxes(
            session, img, [BoxItem(**b) for b in raw_boxes]
        )

    return UploadImageResponse(
        id=img.id, image_id=img.image_id, filename=img.filename,
        width=img.width, height=img.height, status=img.status,
    )
