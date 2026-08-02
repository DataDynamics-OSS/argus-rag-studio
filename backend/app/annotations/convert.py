# SPDX-License-Identifier: Apache-2.0
"""문서를 페이지별 이미지(PNG)로 변환한다 — 어노테이션 라벨링용.

흐름:
    PDF             → 그대로 사용
    오피스/HWP 류   → LibreOffice(soffice) 로 PDF 변환(app.s3browse.office_pdf 재사용)
    → PyMuPDF(fitz) 로 각 페이지를 PNG 로 래스터화(+축소 썸네일).

LibreOffice 미설치 환경에선 오피스/HWP 변환이 RuntimeError 로 실패한다(PDF 는 영향 없음).

HWP/HWPX 변환 엔진은 설정(image_conversion.hwp_engine)으로 선택한다:
    - rhwp(기본)   → 프론트엔드가 클라이언트(@rhwp/core, WASM)에서 렌더해 일반 이미지 업로드 경로로
                     올리므로 이 백엔드 경로를 타지 않는다(s3browse 미리보기와 동일 엔진).
    - libreoffice  → 프론트엔드가 이 백엔드로 hwp/hwpx 를 보내고, 여기서 LibreOffice 로 변환한다.
따라서 이 모듈은 hwp/hwpx 도 지원 목록에 둔다(libreoffice 엔진 선택 시 사용).
"""

from __future__ import annotations

import logging
import os

from app.s3browse import office_pdf

logger = logging.getLogger(__name__)

# soffice(LibreOffice)로 PDF 변환할 확장자. HWP/HWPX 는 libreoffice 엔진 선택 시에만 이 경로를 탄다.
_OFFICE_EXTS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".hwp", ".hwpx"}
# 이 백엔드가 변환하는 전체 확장자
SUPPORTED_DOC_EXTS = sorted(_OFFICE_EXTS | {".pdf"})

# 래스터화 해상도(DPI) 기본값 — 설정 미지정 시 폴백. 실제 값은 settings.image_conversion_dpi.
DEFAULT_DPI = 150


def ext_of(filename: str | None) -> str:
    return os.path.splitext(filename or "")[1].lower()


def is_supported(filename: str | None) -> bool:
    return ext_of(filename) in SUPPORTED_DOC_EXTS


async def to_pdf(filename: str, data: bytes) -> bytes:
    """문서 바이트를 PDF 바이트로 만든다. PDF 는 그대로, 그 외는 LibreOffice 로 변환."""
    ext = ext_of(filename)
    if ext == ".pdf":
        return data
    if ext in _OFFICE_EXTS:
        # office_pdf 는 확장자 문자열(점 제외)을 받는다.
        return await office_pdf.convert_to_pdf(data, ext.lstrip("."))
    raise ValueError(f"지원하지 않는 문서 형식입니다: {ext or '(없음)'}")


class RenderedPage:
    """래스터화된 한 페이지 — 원본 PNG + 크기 + 축소 썸네일 PNG."""

    __slots__ = ("png", "width", "height", "thumb")

    def __init__(self, png: bytes, width: int, height: int, thumb: bytes):
        self.png = png
        self.width = width
        self.height = height
        self.thumb = thumb


def render_pdf(pdf: bytes, dpi: int = DEFAULT_DPI) -> list[RenderedPage]:
    """PDF 바이트의 모든 페이지를 PNG 로 래스터화(동기 — 호출부에서 to_thread 권장)."""
    import fitz  # PyMuPDF — 지연 임포트(미설치 시 호출 시점에만 영향)

    from app.core.config import settings

    thumb_max = settings.image_conversion_thumbnail_max
    pages: list[RenderedPage] = []
    base_zoom = dpi / 72.0  # fitz 기본 72dpi 기준 확대율
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(base_zoom, base_zoom))
            png = pix.tobytes("png")
            # 썸네일 — 긴 변이 thumb_max 이하가 되도록 추가 축소(원본보다 키우지 않음).
            longest = max(pix.width, pix.height) or 1
            tscale = min(1.0, thumb_max / longest)
            tzoom = base_zoom * tscale
            tpix = page.get_pixmap(matrix=fitz.Matrix(tzoom, tzoom))
            pages.append(RenderedPage(png, pix.width, pix.height, tpix.tobytes("png")))
    logger.info("문서 래스터화: pages=%d dpi=%d", len(pages), dpi)
    return pages
