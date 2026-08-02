# SPDX-License-Identifier: Apache-2.0
"""검색(retrieval) 모듈의 Pydantic 스키마."""

from enum import Enum

from pydantic import BaseModel, Field


class SearchMode(str, Enum):
    """검색 방식. hybrid 가 기본(벡터 + 렉시컬 RRF 융합)."""

    HYBRID = "hybrid"
    VECTOR = "vector"
    LEXICAL = "lexical"


class FilterOp(str, Enum):
    """메타데이터 필터 연산자(작고 닫힌 집합). 표현력 폭발을 막기 위해 이 3개만."""

    EQ = "eq"        # 정확히 일치
    IN = "in"        # 값 목록 중 하나
    RANGE = "range"  # 날짜/숫자 구간(gte/lte)


class FilterCond(BaseModel):
    """비-보안 메타데이터 필터 조건 1건. 조건 목록은 AND 로 결합한다.

    ``field`` 는 ``filterspec.FILTERABLE_FIELDS`` 화이트리스트로 제한(미등록 → 400). 보안등급/DRM
    은 이 경로로 거르지 않는다 — 격리는 컬렉션 경계가 담당(knowledge-base-design.md §5).
    """

    field: str
    op: FilterOp = FilterOp.EQ
    value: str | int | float | list[str] | None = None
    gte: str | float | None = None  # op=range 일 때 하한
    lte: str | float | None = None  # op=range 일 때 상한


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    mode: SearchMode = SearchMode.HYBRID
    top_k: int | None = Field(None, ge=1, le=50)
    rerank: bool = False
    # 지정 시 해당 파이프라인의 활성 버전 설정을 적용(요청 필드보다 우선)
    pipeline_id: int | None = None
    # 비-보안 메타데이터 필터(AND). 빈/None = 필터 없음.
    filters: list[FilterCond] | None = None


class ChunkHit(BaseModel):
    """검색된 청크 1건 + 점수/출처."""

    chunk_id: str
    document_id: int
    document_uuid: str = ""  # 문서 UUID(rag_documents.document_id) — 프런트에서 문서 전체 열기용
    document_name: str
    collection_id: int
    seq: int
    text: str
    score: float
    section_path: str | None = None
    # 문서 단위 이미지 분류 요약(유형→개수). 인제스천 시 image_classification 옵션이 켜져 있던
    # 문서만 채워진다(예: {"chart": 2, "table": 1}). 비어 있으면 분류 정보 없음.
    document_image_types: dict[str, int] = Field(default_factory=dict)
    # 이 청크에 연결된 이미지 참조([{index, page, type, summary}]). 페이지 기준으로 매칭된
    # 청크만 채워진다(같은 페이지의 도표/차트 등). 비어 있으면 연결된 이미지 없음.
    image_refs: list[dict] = Field(default_factory=list)


class SearchResponse(BaseModel):
    query: str
    mode: str
    reranked: bool
    distance_metric: str  # 벡터 검색에 사용된 거리 메트릭(렉시컬 모드면 미사용)
    hits: list[ChunkHit]
    # 실제 적용된 필터 에코(없으면 빈 목록). 사용자가 "걸린 줄" 오인하지 않게 명시.
    filters_applied: list[FilterCond] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 페더레이션 검색 — 여러 컬렉션(이종 임베딩 공간)을 동시에 검색해 RRF 로 병합.
# ---------------------------------------------------------------------------

class FederatedSearchRequest(BaseModel):
    """여러 지식베이스를 한 번에 검색한다.

    각 컬렉션은 자기 임베딩 모델로 따로 검색하고(이종 벡터 공간 허용), 결과를 순위 기반
    RRF 로 병합한다. ``rerank=true`` 면 병합 후보를 cross-encoder 로 한 번 더 재정렬한다
    (cross-encoder 는 임베딩 공간과 무관한 텍스트 쌍 채점이라 컬렉션 경계를 넘어 비교 가능).
    """

    query: str = Field(..., min_length=1)
    collection_ids: list[int] = Field(..., min_length=1, description="검색 대상 컬렉션 id 목록")
    mode: SearchMode = SearchMode.HYBRID
    per_collection_k: int = Field(20, ge=1, le=200, description="컬렉션별로 끌어올 후보 수")
    top_k: int = Field(10, ge=1, le=100, description="병합 후 최종 결과 수")
    rerank: bool = Field(False, description="병합 후보를 글로벌 cross-encoder 로 재정렬")
    rrf_k: int = Field(60, ge=1, le=1000)
    # 지정 시 모든 컬렉션에 해당 파이프라인의 검색 설정을 동일 적용
    pipeline_id: int | None = None
    # 비-보안 메타데이터 필터(AND) — 모든 대상 컬렉션에 동일 적용. 빈/None = 필터 없음.
    filters: list[FilterCond] | None = None


class CollectionContribution(BaseModel):
    """컬렉션별 기여 요약 — 어디서 몇 건이 후보로 나왔고 최종에 몇 건 살아남았는지, 장애 여부."""

    collection_id: int
    name: str
    embedding_model: str
    candidates: int          # 이 컬렉션이 후보로 낸 수
    in_final: int            # 최종 결과에 포함된 수
    status: str              # ok | error
    error: str | None = None


class FederatedSearchResponse(BaseModel):
    query: str
    mode: str
    reranked: bool
    top_k: int
    hits: list[ChunkHit]                       # collection_id 로 출처 컬렉션 식별
    contributions: list[CollectionContribution]
