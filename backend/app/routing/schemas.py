# SPDX-License-Identifier: Apache-2.0
"""문서 라우팅 모듈의 Pydantic 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field


class RoutingStage(BaseModel):
    """정책의 라우터 단계 하나."""

    id: str = Field(..., min_length=1)
    config: dict = Field(default_factory=dict)
    weight: float = Field(default=1.0, ge=0.0)        # weighted_vote 모드 가중치
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)  # first_match 채택 임계


class RoutingPolicyConfig(BaseModel):
    """라우팅 정책 — 라우터 조합 + 폴백/검토 임계."""

    mode: str = Field(default="first_match")  # first_match | weighted_vote
    stages: list[RoutingStage] = Field(default_factory=list)
    fallback_collection_id: int | None = None
    review_below: float = Field(default=0.5, ge=0.0, le=1.0)


class PolicyUpdateRequest(BaseModel):
    """정책 수정 — 새 버전을 생성하고 active 로 만든다."""

    config: RoutingPolicyConfig
    note: str | None = None


class PolicyVersionResponse(BaseModel):
    version: int
    config: RoutingPolicyConfig
    note: str | None = None
    created_by: str | None = None
    created_at: datetime


class PolicyResponse(BaseModel):
    id: int
    policy_id: str
    name: str
    description: str | None = None
    active_version: int
    version_count: int = 0
    config: RoutingPolicyConfig
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


# --- 라우팅 결정(미리보기/인테이크 공통) -------------------------------------

class RouteCandidate(BaseModel):
    collection_id: int
    score: float
    reason: str = ""


class RouteTraceEntry(BaseModel):
    router: str
    candidates: list[RouteCandidate] = Field(default_factory=list)


class RouteDecision(BaseModel):
    """정책 실행 결과 — 최종 컬렉션 + 근거."""

    collection_id: int | None = None
    collection_name: str | None = None  # 선택된 컬렉션 표시명(조회되면)
    confidence: float = 0.0
    mode: str = "first_match"
    matched_router: str | None = None
    fallback_used: bool = False
    review: bool = False
    policy_version: int | None = None
    trace: list[RouteTraceEntry] = Field(default_factory=list)


class RoutePreviewResponse(BaseModel):
    """route-preview — 저장 없이 "어디로 라우팅될지" + 근거."""

    filename: str
    metadata: dict = Field(default_factory=dict)
    decision: RouteDecision
    source_path: str | None = None  # 참조/경로 시뮬레이션일 때 소스 내 경로
    storage: str | None = None      # 참조/경로 시뮬레이션일 때 소스 논리명


class ReferenceIntakeRequest(BaseModel):
    """참조 인테이크 — 등록된 스토리지 소스의 문서를 경로로 가져와(pull) 라우팅·등록."""

    source_id: str = Field(..., min_length=1, max_length=36)  # rag_storage_sources.source_id
    path: str = Field(..., min_length=1, max_length=2000)     # 소스 내 상대 경로


class ReferencePreviewRequest(BaseModel):
    """참조/경로 미리보기 — 소스 문서 또는 경로 문자열만으로 라우팅 시뮬레이션(저장 없음).

    ``path_only=True`` 면 소스 접근 없이 경로·파일명 신호만으로 시뮬레이션한다(파일 불필요) —
    이때 ``source_id`` 대신 ``storage``(소스 논리명 문자열)만 줘도 된다.
    """

    path: str = Field(..., min_length=1, max_length=2000)
    source_id: str | None = Field(None, max_length=36)
    storage: str | None = Field(None, max_length=200)  # path_only 시 소스명 직접 지정
    path_only: bool = False


# --- 폴더 일괄 인테이크(드롭존) ------------------------------------------------

SCAN_MAX_FILES = 500  # 한 번의 scan 이 처리하는 파일 수 상한(동기 처리 보호)


class ScanIntakeRequest(BaseModel):
    """소스 폴더(prefix) 하위 파일들을 일괄 인테이크 — 드롭존 운영의 실행 단위.

    ``dry_run=True`` 면 등록·적재 없이 파일별 라우팅 결과만 시뮬레이션한다(실행 전 미리보기).
    """

    source_id: str = Field(..., min_length=1, max_length=36)
    prefix: str = Field("", max_length=2000)   # 빈 값 = 소스 루트
    recursive: bool = True
    dry_run: bool = False
    limit: int = Field(SCAN_MAX_FILES, ge=1, le=SCAN_MAX_FILES)


class ScanItemResult(BaseModel):
    """scan 파일 1개의 처리 결과."""

    path: str
    status: str                          # routed | duplicate | no_route | failed
    collection_id: int | None = None
    collection_name: str | None = None
    confidence: float | None = None
    review: bool = False
    fallback_used: bool = False
    matched_router: str | None = None
    document_id: int | None = None       # 실행(비 dry_run) 성공 시
    job_id: str | None = None            # 실행(비 dry_run) 성공 시
    detail: str | None = None            # duplicate/failed 사유 등


class ScanIntakeResponse(BaseModel):
    """scan 결과 리포트 — 파일별 배분 결과 + 상태별 집계."""

    source_name: str
    prefix: str
    recursive: bool
    dry_run: bool
    scanned: int                          # 처리한 파일 수(상한·seen 스킵 적용 후)
    skipped: int = 0                      # seen 지문 동일로 읽지 않고 건너뛴 수(증분 스캔)
    truncated: bool                       # 열거/상한으로 잘렸는지(누락 있음)
    counts: dict[str, int] = Field(default_factory=dict)
    items: list[ScanItemResult] = Field(default_factory=list)


class IntakeResponse(BaseModel):
    """intake — 라우팅 후 실제 등록·잡 enqueue 결과."""

    document_id: int
    document_uuid: str
    name: str
    status: str
    job_id: str
    decision: RouteDecision


# --- 검토 큐(라우팅 결정 조회·처리) ---------------------------------------------

class DecisionItem(BaseModel):
    """라우팅 결정 로그 1건 — 검토 큐 목록의 행."""

    id: int
    decision_id: str
    document_id: int
    document_uuid: str | None = None      # 문서 삭제 후에도 행이 남을 수 있어 옵셔널
    document_name: str | None = None
    document_status: str | None = None
    collection_id: int | None = None
    collection_name: str | None = None
    confidence: float = 0.0
    mode: str | None = None
    matched_router: str | None = None
    fallback_used: bool = False
    review: bool = False
    policy_version: int | None = None
    trace: list[RouteTraceEntry] = Field(default_factory=list)
    created_by: str | None = None
    created_at: datetime
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    corrected_collection_id: int | None = None
    corrected_collection_name: str | None = None


class DecisionListResponse(BaseModel):
    """결정 로그 목록 — review_only=true 가 검토 큐."""

    total: int
    pending_review: int                    # review=true 전체 건수(탭 배지용)
    page: int
    page_size: int
    items: list[DecisionItem] = Field(default_factory=list)


class DecisionResolveRequest(BaseModel):
    """검토 처리 — collection_id 를 주면 재배정(문서 이동+재색인), 없으면 확인만."""

    collection_id: int | None = None


class DecisionResolveResponse(BaseModel):
    """검토 처리 결과 — 재배정 시 재색인 잡 id 포함."""

    decision: DecisionItem
    reassigned: bool = False
    job_id: str | None = None


# --- 수정 피드백 루프(수동 재배정 내역 → 규칙 제안) ------------------------------

class FeedbackSuggestion(BaseModel):
    """수정 내역에서 도출된 규칙 제안 1건."""

    router: str                        # extension_rule | filename_rule | metadata_match | path_rule
    kind: str                          # extension | filename_token | doc_type | source_path
    value: str                         # 규칙 값(확장자/키워드/doc_type/경로 프리픽스)
    field: str | None = None           # metadata_match 의 필드(doc_type)
    storage: str | None = None         # path_rule 의 소스 논리명(있으면 한정)
    collection_id: int
    collection_name: str | None = None
    support: int                       # 이 값이 해당 컬렉션으로 수정된 횟수
    total: int                         # 이 값이 등장한 전체 수정 횟수
    purity: float                      # support / total
    samples: list[str] = Field(default_factory=list)  # 근거 문서명(최대 3)


class FeedbackSuggestionsResponse(BaseModel):
    total_corrections: int             # 분석한 수동 재배정 건수
    already_covered: int               # 정책에 이미 반영돼 제외된 제안 수
    suggestions: list[FeedbackSuggestion] = Field(default_factory=list)


class FeedbackApplyRequest(BaseModel):
    """제안 1건을 활성 정책에 반영(새 버전 생성) — 제안 응답 항목을 그대로 보낸다."""

    router: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)
    collection_id: int
    field: str | None = None
    storage: str | None = None
    support: int | None = None         # 버전 note 표기용


class RoutingProfileStatus(BaseModel):
    """컬렉션 라우팅 디스크립터 상태(Phase 2 — 내용 임베딩 라우터 기준 벡터)."""

    collection_id: int
    name: str
    built: bool                       # 프로파일 존재 여부
    stale: bool                       # 존재하나 현 라우팅 공간(전역 임베딩 설정)과 불일치
    source: str | None = None         # chunks | description
    sample_count: int = 0
    built_at: str | None = None
    space_model: str | None = None
    dim: int = 0                      # centroid 차원(라우팅 공간)
    centroid_preview: list[float] = []  # 계산된 벡터 앞 16개(표시용 — 전체는 저장소에만)


class ProfileRecomputeResult(BaseModel):
    """프로파일 재계산 결과 1건."""

    collection_id: int
    name: str
    status: str                       # built | empty | error
    source: str | None = None
    sample_count: int = 0
    error: str | None = None
