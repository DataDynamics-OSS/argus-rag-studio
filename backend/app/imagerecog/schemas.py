# SPDX-License-Identifier: Apache-2.0
"""이미지 추출 및 분석 응답 스키마."""

from pydantic import BaseModel, Field


class RecognizedImage(BaseModel):
    """식별·분류된 이미지 1장."""

    index: int
    page: int | None = None              # PDF/변환 기반일 때만(그 외 None)
    locator: str                          # 출처 표기(예: "page 3", "word/media/image2.png")
    type: str                             # chart | table | diagram | photo | ...
    confidence: float
    summary: str = ""                     # 내용 상세 설명(심층 분석 시 2~4문장)
    ocr_text: str = ""                    # 이미지 내 텍스트 원문(OCR, 없으면 빈 문자열)
    details: str = ""                     # 표/차트=마크다운 표, 수식=LaTeX(해당 없으면 빈 문자열)
    width: int
    height: int
    thumbnail: str                        # data:image/png;base64,… (목록 표시용 축소)
    original: str = ""                    # data:image/png;base64,… 원본(확대 보기용, 휘발성)


class AnalyzeResponse(BaseModel):
    """문서 1건 분석 결과."""

    filename: str
    source_kind: str                      # PDF | 이미지 | Word | Excel | HWP | HTML ...
    count: int                            # 분류한 이미지 수
    extracted: int                        # 추출된 이미지 수(분류 전, cap 적용 전)
    truncated: bool = False               # max_images 로 일부만 분류했는지
    counts_by_type: dict[str, int] = Field(default_factory=dict)
    items: list[RecognizedImage] = Field(default_factory=list)


# ── 실행 이력(분류 버킷에 저장된 과거 실행) ──────────────────────────────────

class RunListItem(BaseModel):
    """이력 목록의 실행 1건(메타만)."""

    run_id: str
    batch_id: str | None = None
    filename: str
    source_kind: str | None = None
    status: str                           # running | succeeded | failed
    extracted_count: int = 0
    analyzed_count: int = 0
    counts_by_type: dict[str, int] = Field(default_factory=dict)
    size_bytes: int = 0                   # 실행 폴더(prefix) 전체 저장 크기(byte)
    source_url: str | None = None         # URL 가져오기면 원본 페이지 URL(파일명은 HTML 타이틀)
    error: str | None = None
    created_by: str | None = None
    created_at: str | None = None         # ISO8601
    finished_at: str | None = None


class PaginatedRunsResponse(BaseModel):
    """실행 이력 목록(페이지)."""

    items: list[RunListItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class RunImageItem(BaseModel):
    """이력 상세의 이미지 1장 — data URL + 분석 결과."""

    index: int
    page: int | None = None
    locator: str = ""
    width: int = 0
    height: int = 0
    original_url: str = ""                # data URL(원본)
    thumb_url: str = ""                   # data URL(썸네일)
    type: str = ""
    confidence: float = 0.0
    summary: str = ""
    ocr_text: str = ""
    details: str = ""


class RunDetail(RunListItem):
    """실행 1건 상세 — 메타 + 이미지별 결과(presigned URL 포함)."""

    truncated: bool = False
    source_download_url: str = ""         # 업로드 원본 파일 presigned 다운로드 URL(없으면 빈 값)
    source_filename: str = ""             # 업로드 원본 파일명
    items: list[RunImageItem] = Field(default_factory=list)
    # (source_url 은 RunListItem 에서 상속 — URL 가져오기의 원본 페이지 URL)
