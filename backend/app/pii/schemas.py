# SPDX-License-Identifier: Apache-2.0
"""PII 규칙 API 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field


class PiiRuleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    category: str = Field("custom", max_length=40)
    pattern: str = Field(..., min_length=1)
    flags: str = Field("", max_length=20)
    mask: str = Field("[REDACTED]", max_length=200)
    enabled: bool = True
    description: str | None = None


class PiiRuleUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    category: str | None = Field(None, max_length=40)
    pattern: str | None = Field(None, min_length=1)
    flags: str | None = Field(None, max_length=20)
    mask: str | None = Field(None, max_length=200)
    enabled: bool | None = None
    description: str | None = None


class PiiRuleResponse(BaseModel):
    id: int
    rule_id: str
    name: str
    category: str
    pattern: str
    flags: str
    mask: str
    enabled: bool
    description: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class PiiTestRequest(BaseModel):
    text: str = Field(..., max_length=20000)
    categories: list[str] | None = None  # 비우면 전체 enabled


class PiiTestMatch(BaseModel):
    rule_id: str
    name: str
    category: str
    count: int


class PiiTestResponse(BaseModel):
    masked: str
    matches: list[PiiTestMatch]
    invalid: list[str] = []  # 컴파일 실패한 rule_id 목록


# ── 사용자 정의 함수 ──────────────────────────────────────────────────────────


class PiiFunctionCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    code: str = Field(..., min_length=1, max_length=20000)
    timeout_ms: int = Field(2000, ge=200, le=15000)
    enabled: bool = True
    description: str | None = None


class PiiFunctionUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    code: str | None = Field(None, min_length=1, max_length=20000)
    timeout_ms: int | None = Field(None, ge=200, le=15000)
    enabled: bool | None = None
    description: str | None = None


class PiiFunctionResponse(BaseModel):
    id: int
    function_id: str
    name: str
    code: str
    timeout_ms: int
    enabled: bool
    description: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class PiiFunctionTestRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=20000)
    text: str = Field(..., max_length=20000)
    timeout_ms: int = Field(2000, ge=200, le=15000)


class PiiFunctionTestResponse(BaseModel):
    result: str | None = None
    error: str | None = None
