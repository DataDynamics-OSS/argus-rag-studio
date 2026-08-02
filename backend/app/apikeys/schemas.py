# SPDX-License-Identifier: Apache-2.0
"""API 키(서비스 계정) 스키마 (Pydantic)."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.usermgr.schemas import RoleName


class ApiKeyCreateRequest(BaseModel):
    """API 키 발급 요청 (admin 전용)."""

    name: str = Field(..., min_length=1, max_length=100, description="키 식별용 이름")
    description: str | None = Field(None, max_length=255)
    role: RoleName = Field(RoleName.USER, description="키에 부여할 역할(권한)")
    expires_in_days: int | None = Field(
        None, ge=1, le=3650, description="만료까지 일수. 미지정 시 무기한",
    )


class ApiKeyUpdateRequest(BaseModel):
    """API 키 메타데이터/활성 상태 수정 (부분 갱신)."""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=255)
    enabled: bool | None = None


class ApiKeyResponse(BaseModel):
    """API 키 메타데이터(평문 키는 포함하지 않음)."""

    id: int
    name: str
    description: str | None = None
    key_prefix: str
    role_id: str
    enabled: bool
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyCreatedResponse(ApiKeyResponse):
    """발급 직후 응답 — 평문 키(``api_key``)를 단 1회만 포함한다."""

    api_key: str = Field(..., description="평문 키. 이 응답에서만 노출되며 이후 복원 불가")
