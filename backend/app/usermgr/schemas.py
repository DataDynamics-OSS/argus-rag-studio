# SPDX-License-Identifier: Apache-2.0
"""사용자 관리(User management) 스키마 (Pydantic)."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, EmailStr, Field


class UserStatus(str, Enum):
    """사용자 계정 상태."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class RoleName(str, Enum):
    """사용 가능한 역할 식별자. ``argus_roles.role_id`` / Keycloak realm role 과 매칭."""

    ADMIN = "argus-admin"
    SUPERUSER = "argus-superuser"
    USER = "argus-user"


# ---------------------------------------------------------------------------
# 역할 스키마
# ---------------------------------------------------------------------------

class RoleResponse(BaseModel):
    """클라이언트에 반환하는 역할 정보. ORM 객체에서 바로 변환 가능."""

    id: int
    role_id: str
    name: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# 사용자 요청 스키마
# ---------------------------------------------------------------------------

class UserAddRequest(BaseModel):
    """신규 사용자 생성 요청."""

    username: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    organization: str | None = Field(None, max_length=100)
    department: str | None = Field(None, max_length=100)
    phone_number: str | None = Field(None, max_length=30)
    password: str = Field(..., min_length=4, max_length=128)
    role: RoleName = Field(RoleName.USER, description="역할 이름 (Admin/Superuser/User)")
    must_change_password: bool = Field(False, description="최초 로그인 시 비밀번호 강제 변경 여부")


class UserModifyRequest(BaseModel):
    """사용자 프로필 필드 수정 요청 (부분 갱신)."""

    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    email: EmailStr | None = None
    organization: str | None = Field(None, max_length=100)
    department: str | None = Field(None, max_length=100)
    phone_number: str | None = Field(None, max_length=30)


class UserChangeRoleRequest(BaseModel):
    """역할 변경 요청."""

    role: RoleName


class UserSetPasswordRequest(BaseModel):
    """관리자에 의한 비밀번호 재설정 요청 (로컬 인증 모드 전용)."""

    password: str = Field(..., min_length=8, max_length=128)


# ---------------------------------------------------------------------------
# 사용자 응답 스키마
# ---------------------------------------------------------------------------

class UserResponse(BaseModel):
    """클라이언트에 반환하는 사용자 정보."""

    id: int
    username: str
    email: str
    first_name: str
    last_name: str
    organization: str | None = None
    department: str | None = None
    phone_number: str | None = None
    status: UserStatus
    role: str
    created_at: datetime
    updated_at: datetime


class PaginatedUserResponse(BaseModel):
    """사용자 목록의 페이지네이션 응답."""

    items: list[UserResponse]
    total: int
    page: int
    page_size: int
