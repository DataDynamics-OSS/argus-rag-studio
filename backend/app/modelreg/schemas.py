# SPDX-License-Identifier: Apache-2.0
"""모델 레지스트리 API 스키마."""

from pydantic import BaseModel, Field, field_validator

MODEL_KINDS = ("embedding", "reranker", "vlm", "detection")


def _valid_name(v: str) -> str:
    v = v.strip()
    if not v or "/" in v or v.startswith("."):
        raise ValueError("모델 이름은 비어있지 않고 '/' 없이 지정해야 합니다(버킷 키에 사용).")
    return v


class ModelCreateRequest(BaseModel):
    kind: str = Field(..., max_length=20)
    name: str = Field(..., max_length=200)   # 미지정 UI 에서 repo 뒷부분으로 자동 제안
    repo: str = Field(..., max_length=300)
    revision: str = Field("main", max_length=100)
    note: str = Field("", max_length=2000)
    max_len: int | None = Field(None, ge=512, le=262144)  # vlm 전용(서빙 인자)
    enabled: bool = True

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in MODEL_KINDS:
            raise ValueError(f"kind 는 {MODEL_KINDS} 중 하나여야 합니다.")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _valid_name(v)

    @field_validator("repo")
    @classmethod
    def _repo(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("repo 는 필수입니다(HF org/name).")
        return v


class ModelUpdateRequest(BaseModel):
    """부분 수정 — None 필드는 유지. kind 는 변경 불가(Repo 키·배포 연동과 결합)."""

    name: str | None = Field(None, max_length=200)
    repo: str | None = Field(None, max_length=300)
    revision: str | None = Field(None, max_length=100)
    note: str | None = Field(None, max_length=2000)
    max_len: int | None = Field(None, ge=512, le=262144)
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return _valid_name(v) if v is not None else None


class ModelResponse(BaseModel):
    model_id: str
    kind: str
    name: str
    repo: str
    revision: str
    source: str
    target: str
    note: str = ""
    enabled: bool
    builtin: bool
    max_len: int | None = None
    approx_gb: float | None = None
    # Model Repository(argus-models) 보유 현황 — 목록 API 가 병합
    available: bool = False
    revisions: list[str] = []
