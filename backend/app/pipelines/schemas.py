# SPDX-License-Identifier: Apache-2.0
"""파이프라인 모듈의 Pydantic 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.config import settings
from app.retrieval.schemas import ChunkHit, SearchMode


class RetrievalConfig(BaseModel):
    mode: SearchMode = SearchMode.HYBRID
    top_k: int = Field(default=5, ge=1, le=50)
    vector_k: int = Field(default=20, ge=1, le=200)
    lexical_k: int = Field(default=20, ge=1, le=200)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    # 거리 메트릭 override(빈 값이면 컬렉션 메트릭 상속). cosine | l2 | inner_product
    distance_metric: str = ""


class RerankConfig(BaseModel):
    enabled: bool = False
    provider: str = "none"  # none | llm | cross_encoder
    top_n: int = Field(default=5, ge=1, le=50)


class GenerationConfig(BaseModel):
    model: str = ""  # 빈 값이면 전역 설정 모델 사용
    max_tokens: int = Field(default=2048, ge=1, le=128000)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class PipelineConfig(BaseModel):
    """파이프라인 설정 번들 — 검색 + 리랭크 + 생성."""

    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    rerank: RerankConfig = Field(default_factory=RerankConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)

    @classmethod
    def from_settings(cls) -> "PipelineConfig":
        """현재 전역 설정값으로 기본 config 를 만든다(신규 파이프라인 초기값)."""
        return cls(
            retrieval=RetrievalConfig(
                top_k=settings.retrieval_top_k, vector_k=settings.retrieval_vector_k,
                lexical_k=settings.retrieval_lexical_k, rrf_k=settings.retrieval_rrf_k,
            ),
            rerank=RerankConfig(
                enabled=settings.rerank_provider != "none",
                provider=settings.rerank_provider, top_n=settings.rerank_top_n,
            ),
            generation=GenerationConfig(
                model=settings.llm_model, max_tokens=settings.llm_max_tokens,
                temperature=settings.llm_temperature,
            ),
        )


class PipelineCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    stage: str = "dev"
    config: PipelineConfig | None = None  # 미지정 시 전역 설정 기반


class PipelineUpdateRequest(BaseModel):
    """설정을 수정한다 — 새 버전을 생성하고 active 로 만든다."""

    config: PipelineConfig
    note: str | None = None


class VersionResponse(BaseModel):
    version: int
    config: PipelineConfig
    note: str | None = None
    created_by: str | None = None
    created_at: datetime


class PipelineResponse(BaseModel):
    id: int
    pipeline_id: str
    name: str
    description: str | None = None
    stage: str
    active_version: int
    version_count: int = 0
    config: PipelineConfig
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class DiffEntry(BaseModel):
    path: str
    from_value: str | None = None
    to_value: str | None = None


class DiffResponse(BaseModel):
    from_version: int
    to_version: int
    changes: list[DiffEntry]


class MetaUpdateRequest(BaseModel):
    stage: str | None = None
    description: str | None = None


class CompareRequest(BaseModel):
    """동일 질의를 두 버전 설정으로 검색해 비교(실험)."""

    query: str = Field(..., min_length=1)
    collection_id: int
    version_a: int
    version_b: int


class VersionResult(BaseModel):
    version: int
    hits: list[ChunkHit]


class CompareResponse(BaseModel):
    query: str
    a: VersionResult
    b: VersionResult
