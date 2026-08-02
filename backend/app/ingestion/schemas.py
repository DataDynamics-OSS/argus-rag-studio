# SPDX-License-Identifier: Apache-2.0
"""인제스천 모듈의 Pydantic 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field


class IngestionJobResponse(BaseModel):
    """인제스천 잡 상태 응답(진행률 폴링용)."""

    id: int
    job_id: str
    document_id: int
    collection_id: int
    status: str
    stage: str | None = None
    progress: int
    chunk_count: int
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobListItem(IngestionJobResponse):
    """잡 모니터링 목록 항목 — 잡 + 문서/컬렉션 이름(조인)."""

    document_name: str | None = None
    collection_name: str | None = None
    document_uuid: str | None = None  # 재처리(reindex) 호출용


class PaginatedJobsResponse(BaseModel):
    items: list[JobListItem]
    total: int
    page: int
    page_size: int


class JobsSummaryResponse(BaseModel):
    """잡 요약 집계(대시보드 카드)."""

    queued: int
    running: int
    succeeded_24h: int
    failed_24h: int
    total: int
    running_by_stage: dict[str, int] = {}


class ParsePreviewResponse(BaseModel):
    """파싱 미리보기 응답 — 저장/임베딩 없이 파싱 텍스트만 반환(파싱 검증용)."""

    filename: str
    strategy: str          # 실제 적용된 파싱 전략(auto 해석 후)
    char_count: int        # 파싱 전문 길이(잘리기 전 기준)
    truncated: bool        # max_chars 로 잘렸는지
    elapsed_ms: int        # 파싱 소요(ms)
    text: str              # 파싱 텍스트(잘릴 수 있음)


class ChunkPreviewItem(BaseModel):
    """청킹 프리뷰 청크 1개 — 본문 내 위치(char_start/end) 포함(전문 위 하이라이트용)."""

    seq: int
    text: str
    section_path: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    char_count: int | None = None
    token_count: int | None = None


class ChunkPreviewResponse(BaseModel):
    """청킹 전/후 비교 — 청킹 전(body) + 청킹 후(chunks). 저장·임베딩 없음."""

    parse_strategy: str
    chunk_strategy: str
    chunk_size: int
    chunk_overlap: int
    chunk_unit: str
    char_count: int        # 전문 길이(자르기 전)
    truncated: bool        # body 가 max_chars 로 잘렸는지
    body: str              # 청킹 전 전문(잘릴 수 있음)
    chunk_total: int       # 전체 청크 수(자르기 전)
    chunks: list[ChunkPreviewItem]


class UploadResponse(BaseModel):
    """업로드 응답 — 등록된 문서 + 생성된 잡."""

    document_id: int
    document_uuid: str
    name: str
    status: str
    job_id: str


class RegisterRequest(BaseModel):
    """NiFi 등 외부 파이프라인의 오브젝트 스토리지 경유 등록 요청(M2b).

    파이프라인이 이미 MinIO/S3 에 원본을 올린 뒤, 그 위치(URI)와 메타데이터만 전송한다.
    워커가 ``source_uri`` 에서 바이트를 당겨와 처리한다.
    """

    collection_id: int
    name: str = Field(..., min_length=1, max_length=500)
    source_uri: str = Field(..., max_length=2000)
    source_type: str = Field("s3", max_length=50)
    content_hash: str | None = Field(None, max_length=64)
    size_bytes: int = Field(0, ge=0)
    metadata_json: str | None = None
