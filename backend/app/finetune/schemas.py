# SPDX-License-Identifier: Apache-2.0
"""파인튜닝 학습 데이터셋 모듈의 Pydantic 스키마."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Task = Literal["embedding", "reranker"]
Split = Literal["train", "valid", "test"]
ExampleSource = Literal["manual", "goldenset", "feedback", "mined"]


# ---------------------------------------------------------------------------
# 데이터셋
# ---------------------------------------------------------------------------

class DatasetCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    base_collection_id: int | None = None
    base_model: str | None = Field(None, max_length=200)
    task: Task = "embedding"
    prompt_format: Literal["e5", "none"] = "e5"


class DatasetResponse(BaseModel):
    id: int
    dataset_id: str
    name: str
    description: str | None = None
    base_collection_id: int | None = None
    base_model: str | None = None
    task: str
    prompt_format: str
    split_strategy: str
    status: str
    # split 별 예시 수
    counts: dict[str, int] = Field(default_factory=dict)
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# 예시(Example)
# ---------------------------------------------------------------------------

class ExampleCreateRequest(BaseModel):
    query: str = Field(..., min_length=1)
    positive: str = Field(..., min_length=1)
    negatives: list[str] = Field(default_factory=list)
    split: Split = "train"
    positive_chunk_id: int | None = None
    source: ExampleSource = "manual"
    meta: dict | None = None


class ExampleResponse(BaseModel):
    id: int
    example_id: str
    dataset_id: int
    split: str
    query: str
    positive: str
    negatives: list[str]
    positive_chunk_id: int | None = None
    source: str
    meta: dict | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# 내보내기(매니페스트)
# ---------------------------------------------------------------------------

class ManifestResponse(BaseModel):
    """외부 트레이너 입력 계약과 동일한 매니페스트(내보내기 미리보기)."""

    dataset_id: str
    name: str
    base_model: str | None = None
    task: str
    prompt_format: str
    split_strategy: str
    counts: dict[str, int]
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# 학습 작업(Job)
# ---------------------------------------------------------------------------

JobStatus = Literal["queued", "running", "succeeded", "failed", "canceled"]
JobStage = Literal["export", "training", "importing"]


class JobCreateRequest(BaseModel):
    dataset_id: int
    # 미지정 시 데이터셋의 task/base_model 을 스냅샷한다.
    task: Task | None = None
    base_model: str | None = Field(None, max_length=200)
    epochs: int = Field(3, ge=1, le=100)
    batch_size: int = Field(32, ge=1, le=1024)
    lr: float = Field(2e-5, gt=0, le=1)
    max_negatives: int = Field(1, ge=0, le=32)


class JobUpdateRequest(BaseModel):
    """외부 트레이너/운영자가 잡 상태를 콜백으로 갱신한다(부분 갱신)."""

    status: JobStatus | None = None
    stage: JobStage | None = None
    progress: int | None = Field(None, ge=0, le=100)
    metrics: dict | None = None
    artifact_uri: str | None = Field(None, max_length=2000)
    error: str | None = None


class JobResponse(BaseModel):
    id: int
    job_id: str
    dataset_id: int
    dataset_name: str | None = None
    task: str
    base_model: str | None = None
    config: dict
    status: str
    stage: str | None = None
    progress: int
    metrics: dict | None = None
    artifact_uri: str | None = None
    error: str | None = None
    callback_token: str | None = None  # 잡 전용 콜백 토큰(superuser 응답에서만 노출)
    created_by: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


# ---------------------------------------------------------------------------
# 모델 레지스트리(Model)
# ---------------------------------------------------------------------------

ModelStatus = Literal["registered", "serving", "archived"]


class ModelCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    task: Task = "embedding"
    base_model: str | None = Field(None, max_length=200)
    embedding_dim: int | None = Field(None, ge=1, le=8192)
    format: str | None = Field(None, max_length=40)
    prompt_format: Literal["e5", "none"] = "e5"
    dataset_id: int | None = None
    job_id: int | None = None
    artifact_uri: str | None = Field(None, max_length=2000)
    metrics: dict | None = None
    serving_url: str | None = Field(None, max_length=500)


class ModelUpdateRequest(BaseModel):
    """서빙 연결·상태·발행 위치 갱신(부분 갱신)."""

    serving_url: str | None = Field(None, max_length=500)
    status: ModelStatus | None = None
    published_uri: str | None = Field(None, max_length=2000)


class ModelResponse(BaseModel):
    id: int
    model_id: str
    name: str
    task: str
    base_model: str | None = None
    embedding_dim: int | None = None
    format: str | None = None
    prompt_format: str
    dataset_id: int | None = None
    job_id: int | None = None
    artifact_uri: str | None = None
    metrics: dict | None = None
    serving_url: str | None = None
    status: str
    published_uri: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# 용어 사전(Glossary)
# ---------------------------------------------------------------------------

class GlossaryTermCreateRequest(BaseModel):
    term: str = Field(..., min_length=1, max_length=200)
    definition: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    domain: str | None = Field(None, max_length=100)


class GlossaryTermUpdateRequest(BaseModel):
    term: str | None = Field(None, min_length=1, max_length=200)
    definition: str | None = None
    synonyms: list[str] | None = None
    domain: str | None = Field(None, max_length=100)


class GlossaryTermResponse(BaseModel):
    id: int
    term_id: str
    term: str
    definition: str | None = None
    synonyms: list[str]
    domain: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# 빌더 / 마이닝
# ---------------------------------------------------------------------------

class BuildFromEvalRequest(BaseModel):
    eval_dataset_id: int
    split: Split = "train"
    top_k: int = Field(10, ge=2, le=50)
    max_negatives: int = Field(3, ge=0, le=10)


class MineNegativesRequest(BaseModel):
    per_example: int = Field(3, ge=1, le=10)
    top_k: int = Field(10, ge=2, le=50)
    only_missing: bool = True  # 네거티브가 없는 예시만 대상


class BuilderResultResponse(BaseModel):
    built: int = 0
    updated: int = 0
    skipped: int = 0
    message: str | None = None
