# SPDX-License-Identifier: Apache-2.0
"""컬렉션(지식베이스) 모듈의 Pydantic 스키마."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class DistanceMetric(str, Enum):
    """벡터 거리 메트릭. pgvector 인덱스 연산자와 매핑된다(M2)."""

    COSINE = "cosine"
    L2 = "l2"
    INNER_PRODUCT = "inner_product"


class EmbeddingProviderKind(str, Enum):
    OPENAI_COMPATIBLE = "openai_compatible"
    LOCAL = "local"  # FastEmbed 자체 임베딩(서버 불필요)
    HASH = "hash"


class ParseStrategy(str, Enum):
    """문서 파싱 전략. 컬렉션별로 지정(parse 시점 — 변경 시 재인덱싱 필요)."""

    AUTO = "auto"  # 파일 유형별 자동 선택(PDF→layout, HWP→rhwp, 그 외→text)
    TEXT = "text"  # 평문 추출(기본, 의존성 가벼움)
    LAYOUT = "layout"  # 레이아웃·표 인식(pdfplumber)
    DOCAI = "docai"  # 문서 AI(Docling)
    VLM = "vlm"  # 비전 LLM(페이지 이미지→Markdown)


class ChunkStrategy(str, Enum):
    """청킹 전략. 컬렉션별로 다르게 지정 가능(생성 후 불변)."""

    AUTO = "auto"  # 내용 자동 선택(표·헤딩 있으면 markdown, 아니면 recursive)
    RECURSIVE = "recursive"
    SENTENCE = "sentence"
    PARAGRAPH = "paragraph"  # 문단(빈 줄) 경계 보존 + 그리디 묶음
    SECTION = "section"  # 섹션 헤더(헤딩·번호·장/절) 경계 보존 + 섹션 경로
    FIXED = "fixed"
    MARKDOWN = "markdown"  # 마크다운 구조 인식(표·헤딩 보존 + 헤딩 컨텍스트)
    SEMANTIC = "semantic"  # 의미 경계 분할(문장 임베딩 인접 유사도 급락 지점)


class ChunkUnit(str, Enum):
    """청크 크기/오버랩 단위. token 은 임베딩 토큰 윈도우에 맞춤(tiktoken)."""

    CHAR = "char"
    TOKEN = "token"


class RerankProviderKind(str, Enum):
    """리랭커 종류(쿼리 시점 — 재인덱싱 불필요)."""

    NONE = "none"
    LLM = "llm"
    LOCAL = "local"  # FastEmbed cross-encoder 인프로세스(서버 불필요)
    CROSS_ENCODER = "cross_encoder"


class CollectionStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class CollectionCreateRequest(BaseModel):
    """컬렉션 생성 요청. 임베딩·청킹 설정은 생성 후 불변이다(미지정 시 서버 기본값)."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    # 임베딩(벡터 공간) — 미지정 시 서버 기본값(settings.embedding_*)으로 채운다.
    embedding_provider: EmbeddingProviderKind | None = None
    embedding_model: str | None = Field(None, max_length=200)
    embedding_dim: int | None = Field(None, ge=1, le=8192)
    embedding_server_url: str | None = Field(None, max_length=500)
    distance_metric: DistanceMetric | None = None
    # 리랭커(쿼리 시점) — 미지정 시 none. cross_encoder 면 rerank_model 로 모델 지정(선택)
    rerank_provider: RerankProviderKind | None = None
    rerank_model: str | None = Field(None, max_length=200)
    # 파싱(parse 시점) — 미지정 시 text.
    parse_strategy: ParseStrategy | None = None
    # 청킹 — 미지정 시 기본 전략(recursive/1000/150).
    chunk_strategy: ChunkStrategy | None = None
    chunk_unit: ChunkUnit | None = None
    chunk_size: int | None = Field(None, ge=16, le=8000)  # token 단위는 작은 값(64~512) 허용
    chunk_overlap: int | None = Field(None, ge=0, le=2000)

    @model_validator(mode="after")
    def _check_overlap(self) -> "CollectionCreateRequest":
        size = self.chunk_size if self.chunk_size is not None else 1000
        overlap = self.chunk_overlap if self.chunk_overlap is not None else 0
        if overlap >= size:
            raise ValueError("chunk_overlap 은 chunk_size 보다 작아야 합니다.")
        return self


class CollectionUpdateRequest(BaseModel):
    """컬렉션 메타데이터 수정 요청(부분 갱신). 임베딩/청킹 설정은 변경 불가.

    리랭커(rerank_provider)는 쿼리 시점 설정이라 재인덱싱 없이 여기서 바꿀 수 있다.
    """

    description: str | None = Field(None, max_length=2000)
    status: CollectionStatus | None = None
    rerank_provider: RerankProviderKind | None = None
    rerank_model: str | None = Field(None, max_length=200)


class TransformStage(BaseModel):
    """인제스천 보강 파이프라인의 단계 — 레지스트리 transform id + 설정."""

    id: str = Field(..., max_length=50)
    config: dict = Field(default_factory=dict)


class CollectionReindexRequest(BaseModel):
    """컬렉션 색인 설정 변경 + 전체 재인덱싱 요청.

    제공된 필드만 갱신한다(부분 갱신). ``embedding_dim`` 은 물리 벡터 컬럼이 ``vector(1024)``
    로 고정되어 변경 불가하므로 포함하지 않는다. 적용 후 컬렉션의 모든 문서를 새 설정으로
    재처리(parse→chunk→embed→index)한다.
    """

    embedding_provider: EmbeddingProviderKind | None = None
    embedding_model: str | None = Field(None, max_length=200)
    embedding_server_url: str | None = Field(None, max_length=500)
    distance_metric: DistanceMetric | None = None
    parse_strategy: ParseStrategy | None = None
    chunk_strategy: ChunkStrategy | None = None
    chunk_unit: ChunkUnit | None = None
    chunk_size: int | None = Field(None, ge=16, le=8000)  # token 단위는 작은 값(64~512) 허용
    chunk_overlap: int | None = Field(None, ge=0, le=2000)
    # 인제스천 보강 파이프라인(transform 단계). 제공 시 컬렉션 ingestion_pipeline 으로 저장.
    # stage = {"id": "<transform id>", "config": {...}}. id 는 GET /ingestion/transforms 목록.
    post_parse: list["TransformStage"] | None = None
    post_chunk: list["TransformStage"] | None = None
    # server_url 을 명시적으로 비워 전역 상속으로 되돌리려면 true.
    clear_server_url: bool = False


class CollectionResponse(BaseModel):
    """컬렉션 응답. 문서 수(``document_count``)를 집계해 함께 반환한다."""

    id: int
    collection_id: str
    name: str
    description: str | None = None
    embedding_provider: str
    embedding_model: str
    embedding_dim: int
    embedding_server_url: str | None = None
    distance_metric: str
    rerank_provider: str
    rerank_model: str | None = None
    parse_strategy: str
    chunk_strategy: str
    chunk_unit: str
    chunk_size: int
    chunk_overlap: int
    ingestion_pipeline: dict | None = None   # 보강 파이프라인(없으면 기본)
    status: str
    document_count: int = 0
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class CollectionReindexResponse(BaseModel):
    """재인덱싱 트리거 결과 — 갱신된 컬렉션 + enqueue 된 잡 요약."""

    collection: CollectionResponse
    document_count: int
    job_ids: list[str]


class PaginatedCollectionResponse(BaseModel):
    items: list[CollectionResponse]
    total: int
    page: int
    page_size: int
