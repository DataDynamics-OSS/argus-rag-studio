# SPDX-License-Identifier: Apache-2.0
"""사용자 관리(User management) API.

사용자/역할 CRUD 를 제공하는 FastAPI 라우터. 모든 엔드포인트는 ``/usermgr`` prefix 를
사용한다. 비즈니스 로직은 ``service`` 모듈에 위임한다.

권한 정책:
    - 조회(GET): 로그인 사용자
    - PUT /users/{id}: 관리자 또는 본인
    - 생성/삭제/역할 변경/활성·비활성/비밀번호 재설정: 관리자 전용
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AdminUser, CurrentUser
from app.core.config import settings
from app.core.database import get_session
from app.usermgr import service
from app.usermgr.schemas import (
    PaginatedUserResponse,
    RoleResponse,
    UserAddRequest,
    UserChangeRoleRequest,
    UserModifyRequest,
    UserResponse,
    UserSetPasswordRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/usermgr", tags=["usermgr"])


@router.get("/check-user")
async def check_user_exists(
    _user: CurrentUser,
    username: str | None = Query(None, description="Username to check"),
    email: str | None = Query(None, description="Email to check"),
    session: AsyncSession = Depends(get_session),
):
    """사용자명 또는 이메일이 이미 존재하는지 확인한다."""
    if not username and not email:
        logger.warning("check-user 호출 시 username/email 누락")
        raise HTTPException(status_code=400, detail="사용자명 또는 이메일은(는) 필수입니다.")
    result = await service.check_user_exists(session, username=username, email=email)
    if result.get("username_exists") or result.get("email_exists"):
        logger.info("check-user 중복 감지: username=%s email=%s", username, email)
    return result


@router.post("/users", response_model=UserResponse)
async def add_user(req: UserAddRequest, _admin: AdminUser, session: AsyncSession = Depends(get_session)):
    """새 사용자 생성. 지정한 역할이 DB 에 없으면 400."""
    try:
        return await service.add_user(session, req)
    except ValueError as e:
        logger.warning("add_user 실패(검증): %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/users", response_model=PaginatedUserResponse)
async def list_users(
    _user: CurrentUser,
    status: str | None = Query(None, description="Filter by status (active/inactive)"),
    role: str | None = Query(None, description="Filter by role_id (argus-admin/...)"),
    search: str | None = Query(None, description="Search username, name, email, phone, org"),
    organization: str | None = Query(None, description="Filter by organization (exact)"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(10, ge=0, le=1000, description="Items per page (0 = all)"),
    session: AsyncSession = Depends(get_session),
):
    """필터·페이지네이션을 적용해 사용자 목록을 반환한다."""
    return await service.list_users(
        session, status=status, role=role, search=search, organization=organization,
        page=page, page_size=page_size,
    )


@router.get("/users/organizations", response_model=list[str])
async def list_user_organizations(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    """소속(조직) 고유 목록. ``/users/{user_id}`` 보다 먼저 선언."""
    return await service.list_organizations(session)


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, _user: CurrentUser, session: AsyncSession = Depends(get_session)):
    """ID 로 사용자 단건 조회. 없으면 404."""
    user = await service.get_user(session, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자을(를) 찾을 수 없습니다.")
    return user


@router.put("/users/{user_id}", response_model=UserResponse)
async def modify_user(
    user_id: int,
    req: UserModifyRequest,
    current: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    """사용자 프로필 부분 갱신. 권한: 관리자 또는 본인."""
    if not current.is_admin and current.sub != str(user_id):
        raise HTTPException(status_code=403, detail="본인 또는 관리자만 수정할 수 있습니다.")
    user = await service.modify_user(session, user_id, req)
    if not user:
        raise HTTPException(status_code=404, detail="사용자을(를) 찾을 수 없습니다.")
    return user


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, _admin: AdminUser, session: AsyncSession = Depends(get_session)):
    """사용자 영구 삭제(비가역). 마지막 관리자 삭제는 service 가 차단."""
    try:
        if not await service.delete_user(session, user_id):
            raise HTTPException(status_code=404, detail="사용자을(를) 찾을 수 없습니다.")
    except ValueError as e:
        logger.warning("delete_user 차단: user_id=%d reason=%s", user_id, e)
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "message": "User deleted"}


@router.put("/users/{user_id}/role", response_model=UserResponse)
async def change_role(
    user_id: int, req: UserChangeRoleRequest, _admin: AdminUser,
    session: AsyncSession = Depends(get_session),
):
    """사용자 역할 변경. 알 수 없는 역할이면 400."""
    try:
        user = await service.change_role(session, user_id, req)
    except ValueError as e:
        logger.warning("change_role 실패: user_id=%d reason=%s", user_id, e)
        raise HTTPException(status_code=400, detail=str(e))
    if not user:
        raise HTTPException(status_code=404, detail="사용자을(를) 찾을 수 없습니다.")
    return user


@router.put("/users/{user_id}/password", response_model=UserResponse)
async def set_password(
    user_id: int, req: UserSetPasswordRequest, _admin: AdminUser,
    session: AsyncSession = Depends(get_session),
):
    """관리자가 대상 사용자의 비밀번호를 재설정한다(로컬 인증 모드 전용)."""
    if settings.auth_type != "local":
        raise HTTPException(status_code=400, detail="비밀번호 변경은 로컬 인증 모드에서만 사용할 수 있습니다.")
    user = await service.set_password(session, user_id, req.password)
    if not user:
        raise HTTPException(status_code=404, detail="사용자을(를) 찾을 수 없습니다.")
    return user


@router.put("/users/{user_id}/activate", response_model=UserResponse)
async def activate_user(user_id: int, _admin: AdminUser, session: AsyncSession = Depends(get_session)):
    """계정 상태를 ``active`` 로 변경한다."""
    user = await service.activate_user(session, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자을(를) 찾을 수 없습니다.")
    return user


@router.put("/users/{user_id}/deactivate", response_model=UserResponse)
async def deactivate_user(user_id: int, _admin: AdminUser, session: AsyncSession = Depends(get_session)):
    """계정 상태를 ``inactive`` 로 변경한다."""
    try:
        user = await service.deactivate_user(session, user_id)
    except ValueError as e:
        logger.warning("deactivate_user 차단: user_id=%d reason=%s", user_id, e)
        raise HTTPException(status_code=400, detail=str(e))
    if not user:
        raise HTTPException(status_code=404, detail="사용자을(를) 찾을 수 없습니다.")
    return user


@router.get("/roles", response_model=list[RoleResponse])
async def list_roles(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    """모든 역할 목록 반환."""
    return await service.list_roles(session)
