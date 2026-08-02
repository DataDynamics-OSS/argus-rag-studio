# SPDX-License-Identifier: Apache-2.0
"""평가 모듈의 Pydantic 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.retrieval.schemas import SearchMode


# ---------------------------------------------------------------------------
# 데이터셋 / 항목
# ---------------------------------------------------------------------------

class DatasetCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    collection_id: int | None = None


class DatasetResponse(BaseModel):
    id: int
    dataset_id: str
    name: str
    description: str | None = None
    collection_id: int | None = None
    item_count: int = 0
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class ItemCreateRequest(BaseModel):
    question: str = Field(..., min_length=1)
    expected_answer: str | None = None
    expected_sources: list[str] = Field(default_factory=list)


class ItemResponse(BaseModel):
    id: int
    item_id: str
    dataset_id: int
    question: str
    expected_answer: str | None = None
    expected_sources: list[str]
    created_at: datetime


# ---------------------------------------------------------------------------
# Run / 결과
# ---------------------------------------------------------------------------

class RunCreateRequest(BaseModel):
    collection_id: int | None = None  # 미지정 시 데이터셋 기본 컬렉션
    mode: SearchMode = SearchMode.HYBRID
    rerank: bool = False
    judge: bool = False  # LLM-as-judge 생성 지표 산출 여부
    top_k: int | None = Field(None, ge=1, le=50)
    pipeline_id: int | None = None  # 지정 시 파이프라인 활성 버전 설정으로 검색·리랭크 실행(mode/rerank/top_k 무시)


class RunResponse(BaseModel):
    id: int
    run_id: str
    dataset_id: int
    collection_id: int
    pipeline_id: int | None = None
    status: str
    mode: str
    distance_metric: str | None = None
    rerank: bool
    judge: bool
    top_k: int
    total_items: int
    completed_items: int
    hit_rate: float | None = None
    mrr: float | None = None
    faithfulness: float | None = None
    answer_relevance: float | None = None
    correctness: float | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ResultResponse(BaseModel):
    id: int
    item_id: int
    question: str
    answer: str | None = None
    retrieved_docs: list[str]
    hit: bool | None = None
    reciprocal_rank: float | None = None
    faithfulness: float | None = None
    answer_relevance: float | None = None
    correctness: float | None = None


# ---------------------------------------------------------------------------
# 설정 스윕 / 리더보드
# ---------------------------------------------------------------------------

# 정렬·우승 선정에 쓰는 1차 메트릭. composite 는 코드에서 가중 합성.
PRIMARY_METRICS = ("hit_rate", "mrr", "faithfulness", "answer_relevance", "correctness", "composite")


class SweepCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    base_collection_id: int | None = None  # 미지정 시 데이터셋 기본 컬렉션
    # 탐색 공간: {"index_axis": {param: [values]}, "query_axis": {param: [values]}}
    #  - index_axis(비쌈, 재인덱싱): parse_strategy/chunk_strategy/chunk_size/chunk_overlap/chunk_unit
    #  - query_axis(쌈): mode/top_k/rerank
    search_space: dict = Field(default_factory=dict)
    primary_metric: str = "hit_rate"
    judge: bool = False
    # judge 게이팅(P3): 지정 시 검색 점수 상위 N개 조합만 judge 를 재실행(비싼 LLM judge 절감).
    judge_top_n: int | None = Field(None, ge=1, le=64)
    # 홀드아웃 비율(P3): 0~0.9. >0 이면 train 으로 베스트 선정·holdout 으로 일반화 검증.
    holdout_ratio: float = Field(0.0, ge=0.0, le=0.9)
    max_runs: int = Field(64, ge=1, le=512)


class SweepResponse(BaseModel):
    id: int
    sweep_id: str
    name: str
    dataset_id: int
    base_collection_id: int
    primary_metric: str
    judge: bool
    judge_top_n: int | None = None
    holdout_ratio: float = 0.0
    max_runs: int
    status: str
    total_runs: int
    completed_runs: int
    best_run_id: int | None = None
    error: str | None = None
    created_by: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class LeaderboardRow(BaseModel):
    run_id: str
    rank: int
    status: str
    index_config: dict
    query_config: dict
    collection_id: int
    ephemeral: bool = False
    hit_rate: float | None = None
    mrr: float | None = None
    faithfulness: float | None = None
    answer_relevance: float | None = None
    correctness: float | None = None
    score: float | None = None  # primary_metric 기준 점수(holdout 사용 시 train 점수 = 선정 기준)
    holdout_score: float | None = None  # holdout 부분집합 점수(일반화 검증, holdout_ratio>0 일 때)
    overfit: bool = False       # train 대비 holdout 격차가 큰가(과적합 의심)
    judged: bool = False        # 이 Run 에 LLM judge 지표가 산출됐는가
    is_best: bool = False


class LeaderboardResponse(BaseModel):
    sweep: SweepResponse
    primary_metric: str
    holdout_ratio: float = 0.0
    rows: list[LeaderboardRow]


class SweepApplyResponse(BaseModel):
    applied_fields: list[str]
    reindexed: bool
    recommended_runtime: dict  # mode/top_k/rerank — 컬렉션 설정이 아닌 쿼리 런타임 권장값
    collection_id: int
