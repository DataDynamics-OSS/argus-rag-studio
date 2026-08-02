# SPDX-License-Identifier: Apache-2.0
"""문서(Document) 모듈의 Pydantic 스키마."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ChunkPreviewRequest(BaseModel):
    """드래프트 인제스천 파이프라인 미리보기 요청 — 저장·재인덱싱 없이 효과 확인.

    post_parse/post_chunk 를 주면 컬렉션 저장값 대신 그 draft 로 파싱+청킹한다(보강 transform 적용).
    """

    post_parse: list[dict] | None = None
    post_chunk: list[dict] | None = None
    parse_strategy: str | None = None
    strategy: str | None = None
    chunk_size: int | None = Field(None, ge=1)
    chunk_overlap: int | None = Field(None, ge=0)
    chunk_unit: str | None = None
    max_chars: int = Field(200_000, ge=1000, le=2_000_000)


class SourceType(str, Enum):
    UPLOAD = "upload"
    S3 = "s3"
    WEB = "web"
    CONFLUENCE = "confluence"
    NOTION = "notion"
    DATABASE = "database"
    API = "api"


class DocumentStatus(str, Enum):
    REGISTERED = "registered"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


class DocumentCreateRequest(BaseModel):
    """문서 등록 요청(M1: 메타데이터 등록). 실제 인제스천은 M2 에서 트리거."""

    name: str = Field(..., min_length=1, max_length=500)
    source_type: SourceType = SourceType.UPLOAD
    source_uri: str | None = Field(None, max_length=2000)
    content_hash: str | None = Field(None, max_length=64)
    size_bytes: int = Field(0, ge=0)
    metadata_json: str | None = None


class DocumentUpdateRequest(BaseModel):
    """문서 메타데이터/상태 부분 갱신."""

    name: str | None = Field(None, min_length=1, max_length=500)
    status: DocumentStatus | None = None
    metadata_json: str | None = None


class DocumentResponse(BaseModel):
    id: int
    document_id: str
    collection_id: int
    name: str
    source_type: str
    source_uri: str | None = None
    content_hash: str | None = None
    size_bytes: int
    status: str
    chunk_count: int
    metadata_json: str | None = None
    indexed_at: datetime | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class PaginatedDocumentResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    page: int
    page_size: int


class ChunkInspectItem(BaseModel):
    """청크 인스펙터용 단건(임베딩 벡터 자체는 제외, 존재 여부만)."""

    chunk_id: str
    seq: int
    section_path: str | None = None
    char_count: int | None = None
    token_count: int | None = None
    has_embedding: bool
    text: str


class DocumentChunksResponse(BaseModel):
    """문서별 인제스천 현황 + 청크 목록(페이지)."""

    items: list[ChunkInspectItem]
    total: int
    page: int
    page_size: int
    embedded: int                 # 임베딩이 채워진 청크 수
    status: str                   # 문서 상태(indexed/processing/failed/registered)
    last_stage: str | None = None  # 마지막 잡 단계(parse/chunk/embed/index)
    last_error: str | None = None  # 실패 사유(있으면)
