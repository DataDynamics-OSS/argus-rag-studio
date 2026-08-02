# SPDX-License-Identifier: Apache-2.0
"""S3 스토리지 관리 — 오브젝트 스토리지 파일 브라우저 API (admin 전용).

버킷 선택기 지원: 모든 엔드포인트는 ``bucket`` 인자(미지정=기본 버킷)를 받는다.
"""

import logging

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile

from app.core.auth import AdminUser
from app.core.config import settings
from app.storage import client as storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/s3-storage", tags=["s3-storage"])


@router.get("/buckets")
async def list_buckets(_admin: AdminUser):
    """버킷 목록 + 기본 버킷(버킷 선택기용)."""
    return {"buckets": await storage.list_buckets(), "default": settings.os_bucket}


@router.get("/list")
async def list_directory(
    _admin: AdminUser, path: str = Query("/"), bucket: str | None = Query(None)
):
    """프리픽스(path) 하위 폴더·파일을 리스팅한다(bucket 미지정=기본 버킷)."""
    return await storage.list_directory(path, bucket=bucket)


@router.get("/download")
async def download(_admin: AdminUser, path: str = Query(...), bucket: str | None = Query(None)):
    """객체(path)의 presigned 다운로드 URL 을 발급한다."""
    return {"url": await storage.presigned_download_url(path, bucket=bucket)}


@router.get("/content")
async def content(_admin: AdminUser, path: str = Query(...), bucket: str | None = Query(None)):
    """객체(path) 바이트를 동일출처로 스트리밍한다(미리보기용 — presigned 직접 fetch 의 CORS 회피)."""
    data, content_type = await storage.read_object_by_path(path, bucket=bucket)
    return Response(content=data, media_type=content_type or "application/octet-stream")


_OFFICE_PDF_EXTS = {"doc", "docx", "ppt", "pptx", "xls", "xlsx"}


@router.get("/office-pdf")
async def office_pdf(_admin: AdminUser, path: str = Query(...), bucket: str | None = Query(None)):
    """오피스 문서를 LibreOffice 로 PDF 변환해 스트리밍(고충실도 미리보기).

    미설치면 501 → 프런트가 기존 native 미리보기로 폴백한다.
    """
    from app.s3browse import office_pdf as op

    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if ext not in _OFFICE_PDF_EXTS:
        raise HTTPException(status_code=400, detail=f"오피스 변환 대상이 아님: .{ext}")
    if not op.is_available():
        raise HTTPException(status_code=501, detail="LibreOffice 미설치 — 고충실도 변환 불가")

    data, _ = await storage.read_object_by_path(path, bucket=bucket)
    try:
        pdf = await op.convert_to_pdf(data, ext)
    except Exception as e:  # noqa: BLE001
        logger.warning("오피스 PDF 변환 실패 path=%s err=%s", path, e)
        raise HTTPException(status_code=500, detail=f"변환 실패: {e}")
    return Response(content=pdf, media_type="application/pdf")


_PREVIEW_EXTS = {"parquet", "xlsx", "xls", "docx", "pptx"}


@router.get("/preview")
async def preview(
    _admin: AdminUser,
    path: str = Query(...),
    sheet: str | None = Query(None),
    max_rows: int = Query(1000, ge=1, le=10000),
    bucket: str | None = Query(None),
):
    """오피스/데이터 파일을 서버에서 파싱해 구조화 미리보기(parquet·xlsx→테이블, docx·pptx→문서)."""
    import asyncio

    from app.s3browse import preview as pv

    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if ext not in _PREVIEW_EXTS:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 미리보기 형식: .{ext}")

    data, _ = await storage.read_object_by_path(path, bucket=bucket)
    try:
        if ext == "parquet":
            return await asyncio.to_thread(pv.preview_parquet, data, max_rows)
        if ext in ("xlsx", "xls"):
            return await asyncio.to_thread(pv.preview_xlsx, data, sheet, max_rows, ext)
        if ext == "docx":
            return await asyncio.to_thread(pv.preview_docx, data)
        return await asyncio.to_thread(pv.preview_pptx, data)
    except Exception as e:  # noqa: BLE001 — 사용자 표시용
        logger.warning("미리보기 실패 path=%s ext=%s err=%s", path, ext, e)
        raise HTTPException(status_code=500, detail=f"미리보기 실패: {e}")


@router.post("/folder")
async def create_folder(payload: dict, _admin: AdminUser):
    """가상 폴더 생성(prefix/ 빈 객체)."""
    await storage.create_folder(payload["path"], bucket=payload.get("bucket"))
    return {"ok": True}


@router.post("/upload")
async def upload(
    _admin: AdminUser,
    directory: str = Form(...),
    file: UploadFile = File(...),
    bucket: str | None = Form(None),
):
    """directory 아래 파일 업로드."""
    data = await file.read()
    await storage.upload_object(
        directory, file.filename or "file", data, file.content_type, bucket=bucket
    )
    return {"ok": True}


@router.post("/delete")
async def delete(payload: dict, _admin: AdminUser):
    """경로 목록 삭제(폴더는 프리픽스 전체)."""
    await storage.delete_paths(payload.get("paths", []), bucket=payload.get("bucket"))
    return {"ok": True}


@router.post("/rename")
async def rename(payload: dict, _admin: AdminUser):
    """이름변경/이동(copy+delete)."""
    await storage.rename_path(
        payload["source"], payload["destination"], bucket=payload.get("bucket")
    )
    return {"ok": True}
