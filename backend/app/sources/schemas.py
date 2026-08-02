# SPDX-License-Identifier: Apache-2.0
"""스토리지 소스 레지스트리 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field


class SourceCreateRequest(BaseModel):
    """소스 등록. config 는 kind 별(s3: endpoint/bucket/base_prefix/region, nas: mount_path/base_prefix)."""

    name: str = Field(..., min_length=1, max_length=200)
    kind: str = Field(..., max_length=20)          # s3 | nas
    description: str | None = None
    config: dict = Field(default_factory=dict)
    secret: dict | None = None                     # s3: {access_key, secret_key} — 응답 미노출
    enabled: bool = True


class SourceUpdateRequest(BaseModel):
    """소스 수정 — 미지정 필드는 유지. secret=None 유지, clear_secret=True 면 제거."""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    config: dict | None = None
    secret: dict | None = None
    clear_secret: bool = False
    enabled: bool | None = None


class SourceResponse(BaseModel):
    id: int
    source_id: str
    name: str
    kind: str
    description: str | None = None
    config: dict = Field(default_factory=dict)
    has_secret: bool = False                       # 자격증명 존재 여부만 노출
    enabled: bool = True
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class SourceTestResponse(BaseModel):
    """연결 검증 결과 — 등록 화면 '테스트' 버튼용."""

    ok: bool
    message: str
    entry_count: int | None = None
    elapsed_ms: int | None = None


class SourceEntryItem(BaseModel):
    path: str
    name: str
    is_dir: bool
    size: int = 0
    mtime: datetime | None = None


class SourceListResponse(BaseModel):
    """소스 내 경로 브라우징(인테이크 피커용)."""

    prefix: str
    entries: list[SourceEntryItem] = Field(default_factory=list)
    truncated: bool = False
