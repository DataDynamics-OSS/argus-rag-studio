# SPDX-License-Identifier: Apache-2.0
"""소스 워치 API 스키마."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class WatchCreateRequest(BaseModel):
    source_id: str = Field(..., min_length=1, max_length=36)  # RagStorageSource.source_id(UUID)
    name: str = Field(..., min_length=1, max_length=200)
    prefix: str = Field("", max_length=2000)
    recursive: bool = True
    interval_seconds: int = Field(300, ge=1)  # 하한은 설정(watch_min_interval_seconds)로 검증
    enabled: bool = True


class WatchUpdateRequest(BaseModel):
    """부분 수정 — None 필드는 유지. 소스는 변경 불가(워치 삭제 후 재생성)."""

    name: str | None = Field(None, min_length=1, max_length=200)
    prefix: str | None = Field(None, max_length=2000)
    recursive: bool | None = None
    interval_seconds: int | None = Field(None, ge=1)
    enabled: bool | None = None


class WatchResponse(BaseModel):
    watch_id: str
    source_id: str            # RagStorageSource.source_id(UUID)
    source_name: str
    name: str
    prefix: str
    recursive: bool
    interval_seconds: int
    enabled: bool
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_status: str | None = None      # ok | error | None(미실행)
    last_error: str | None = None
    last_counts: dict = Field(default_factory=dict)
    consecutive_failures: int = 0
    created_by: str | None = None
    created_at: datetime | None = None


class WatchRunResponse(BaseModel):
    started_at: datetime
    finished_at: datetime | None = None
    scanned: int
    skipped: int
    counts: dict = Field(default_factory=dict)
    truncated: bool
    error: str | None = None
