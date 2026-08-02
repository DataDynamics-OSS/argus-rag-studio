# SPDX-License-Identifier: Apache-2.0
"""생성(generation)/챗 모듈의 Pydantic 스키마."""

from pydantic import BaseModel, Field

from app.retrieval.schemas import ChunkHit, CollectionContribution, FilterCond, SearchMode


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    mode: SearchMode = SearchMode.HYBRID
    top_k: int | None = Field(None, ge=1, le=50)
    rerank: bool = False
    pipeline_id: int | None = None
    # 비-보안 메타데이터 필터(AND). 빈/None = 필터 없음.
    filters: list[FilterCond] | None = None


class Citation(BaseModel):
    """답변 본문의 [n] 마커에 대응하는 출처 청크."""

    marker: int
    chunk_id: str
    document_id: int
    document_name: str
    seq: int
    text: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    hits: list[ChunkHit]
    trace_id: str | None = None  # 피드백 연결용


class FederatedQueryResponse(BaseModel):
    """여러 컬렉션 페더레이션 질의의 답변 — 인용 + 병합 hits + 컬렉션별 기여."""

    answer: str
    citations: list[Citation]
    hits: list[ChunkHit]
    contributions: list[CollectionContribution]
    reranked: bool


class ChatMessage(BaseModel):
    role: str  # user | assistant
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1)
    mode: SearchMode = SearchMode.HYBRID
    top_k: int | None = Field(None, ge=1, le=50)
    rerank: bool = False
    pipeline_id: int | None = None
