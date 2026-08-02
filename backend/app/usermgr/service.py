# SPDX-License-Identifier: Apache-2.0
"""사용자 관리 서비스(비즈니스 로직 계층).

모든 public 함수는 첫 인자로 ``AsyncSession`` 을 받는다. 비밀번호 해싱은
``_hash_password()`` (SHA-256). 운영에서는 bcrypt/argon2 로 교체 여지가 있다.
"""

import hashlib
import logging

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.usermgr.models import ArgusRole, ArgusUser
from app.usermgr.schemas import (
    PaginatedUserResponse,
    RoleName,
    RoleResponse,
    UserAddRequest,
    UserChangeRoleRequest,
    UserModifyRequest,
    UserResponse,
    UserStatus,
)

logger = logging.getLogger(__name__)


async def _is_last_admin(session: AsyncSession, user_id: int) -> bool:
    """주어진 user_id 가 시스템의 유일한 관리자(admin)인지 확인(시스템 락아웃 방지)."""
    admin_role = await _get_role_by_role_id(session, RoleName.ADMIN.value)
    if not admin_role:
        return False
    admin_count = (await session.execute(
        select(func.count()).where(ArgusUser.role_id == admin_role.id)
    )).scalar() or 0
    if admin_count > 1:
        return False
    result = await session.execute(select(ArgusUser).where(ArgusUser.id == user_id))
    user = result.scalars().first()
    return user is not None and user.role_id == admin_role.id


def _hash_password(password: str) -> str:
    """SHA-256 비밀번호 해시."""
    return hashlib.sha256(password.encode()).hexdigest()


async def _get_role_by_role_id(session: AsyncSession, role_id: str) -> ArgusRole | None:
    """``role_id`` 식별자(예: ``"argus-admin"``)로 역할 조회."""
    result = await session.execute(select(ArgusRole).where(ArgusRole.role_id == role_id))
    return result.scalars().first()


async def _build_user_response(session: AsyncSession, user: ArgusUser) -> UserResponse:
    """``ArgusUser`` ORM 객체에서 역할명을 resolve 해 ``UserResponse`` 로 변환."""
    result = await session.execute(select(ArgusRole).where(ArgusRole.id == user.role_id))
    role = result.scalars().first()
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        organization=user.organization,
        department=user.department,
        phone_number=user.phone_number,
        status=UserStatus(user.status),
        role=role.role_id if role else "unknown",
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


# ---------------------------------------------------------------------------
# 사용자 처리
# ---------------------------------------------------------------------------

async def check_user_exists(
    session: AsyncSession, username: str | None = None, email: str | None = None
) -> dict[str, bool]:
    """``argus_users`` 에서 username/email 중복 여부 확인."""
    result: dict[str, bool] = {}
    if username:
        row = await session.execute(select(ArgusUser).where(ArgusUser.username == username))
        result["username_exists"] = row.scalars().first() is not None
    if email:
        row = await session.execute(select(ArgusUser).where(ArgusUser.email == email))
        result["email_exists"] = row.scalars().first() is not None
    return result


async def add_user(session: AsyncSession, req: UserAddRequest) -> UserResponse:
    """새 사용자 계정 생성. 역할 이름을 ``role_id`` 로 변환하고 비밀번호를 해싱."""
    role = await _get_role_by_role_id(session, req.role.value)
    if not role:
        logger.warning("add_user: 알 수 없는 역할 '%s'", req.role.value)
        raise ValueError(f"Role '{req.role.value}' not found")

    user = ArgusUser(
        username=req.username,
        email=req.email,
        first_name=req.first_name,
        last_name=req.last_name,
        organization=req.organization,
        department=req.department,
        phone_number=req.phone_number,
        password_hash=_hash_password(req.password),
        status=UserStatus.ACTIVE.value,
        must_change_password=req.must_change_password,
        role_id=role.id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    logger.info("사용자 생성: %s (id=%d)", user.username, user.id)
    return await _build_user_response(session, user)


async def delete_user(session: AsyncSession, user_id: int) -> bool:
    """ID 로 사용자를 영구 삭제. 마지막 관리자 삭제는 ``ValueError`` 로 차단."""
    if await _is_last_admin(session, user_id):
        logger.warning("delete_user 차단(마지막 관리자): user_id=%d", user_id)
        raise ValueError("Cannot delete the only admin. At least one admin must remain.")

    result = await session.execute(select(ArgusUser).where(ArgusUser.id == user_id))
    user = result.scalars().first()
    if not user:
        return False
    await session.delete(user)
    await session.commit()
    logger.info("사용자 삭제: %s (id=%d)", user.username, user.id)
    return True


async def modify_user(
    session: AsyncSession, user_id: int, req: UserModifyRequest
) -> UserResponse | None:
    """사용자 프로필 부분 갱신 (None 아닌 필드만)."""
    result = await session.execute(select(ArgusUser).where(ArgusUser.id == user_id))
    user = result.scalars().first()
    if not user:
        return None

    if req.first_name is not None:
        user.first_name = req.first_name
    if req.last_name is not None:
        user.last_name = req.last_name
    if req.email is not None:
        user.email = req.email
    if req.organization is not None:
        user.organization = req.organization
    if req.department is not None:
        user.department = req.department
    if req.phone_number is not None:
        user.phone_number = req.phone_number

    await session.commit()
    await session.refresh(user)
    logger.info("사용자 수정: %s (id=%d)", user.username, user.id)
    return await _build_user_response(session, user)


async def change_role(
    session: AsyncSession, user_id: int, req: UserChangeRoleRequest
) -> UserResponse | None:
    """사용자 역할 변경. 마지막 admin 강등은 차단."""
    result = await session.execute(select(ArgusUser).where(ArgusUser.id == user_id))
    user = result.scalars().first()
    if not user:
        return None

    admin_role = await _get_role_by_role_id(session, RoleName.ADMIN.value)
    if admin_role and user.role_id == admin_role.id and req.role.value != RoleName.ADMIN.value:
        if await _is_last_admin(session, user_id):
            logger.warning("change_role 차단(마지막 관리자 강등): user_id=%d", user_id)
            raise ValueError("Cannot change the role of the only admin.")

    role = await _get_role_by_role_id(session, req.role.value)
    if not role:
        logger.warning("change_role: 알 수 없는 역할 '%s' user_id=%d", req.role.value, user_id)
        raise ValueError(f"Role '{req.role.value}' not found")

    user.role_id = role.id
    await session.commit()
    await session.refresh(user)
    logger.info("사용자 역할 변경: %s -> %s (id=%d)", user.username, req.role.value, user.id)
    return await _build_user_response(session, user)


async def activate_user(session: AsyncSession, user_id: int) -> UserResponse | None:
    """계정 상태를 ``active`` 로 변경."""
    result = await session.execute(select(ArgusUser).where(ArgusUser.id == user_id))
    user = result.scalars().first()
    if not user:
        return None
    user.status = UserStatus.ACTIVE.value
    await session.commit()
    await session.refresh(user)
    logger.info("사용자 활성화: %s (id=%d)", user.username, user.id)
    return await _build_user_response(session, user)


async def deactivate_user(session: AsyncSession, user_id: int) -> UserResponse | None:
    """계정 상태를 ``inactive`` 로 변경. 마지막 관리자는 차단."""
    if await _is_last_admin(session, user_id):
        logger.warning("deactivate_user 차단(마지막 관리자): user_id=%d", user_id)
        raise ValueError("Cannot deactivate the only admin.")

    result = await session.execute(select(ArgusUser).where(ArgusUser.id == user_id))
    user = result.scalars().first()
    if not user:
        return None
    user.status = UserStatus.INACTIVE.value
    await session.commit()
    await session.refresh(user)
    logger.info("사용자 비활성화: %s (id=%d)", user.username, user.id)
    return await _build_user_response(session, user)


async def set_password(
    session: AsyncSession, user_id: int, new_password: str,
) -> UserResponse | None:
    """관리자가 대상 사용자의 비밀번호를 직접 재설정한다(현재 비밀번호 불요)."""
    result = await session.execute(select(ArgusUser).where(ArgusUser.id == user_id))
    user = result.scalars().first()
    if not user:
        return None
    user.password_hash = _hash_password(new_password)
    await session.commit()
    await session.refresh(user)
    logger.info("관리자에 의한 비밀번호 재설정: %s (id=%d)", user.username, user.id)
    return await _build_user_response(session, user)


async def get_user(session: AsyncSession, user_id: int) -> UserResponse | None:
    """ID 로 단건 조회. 없으면 ``None`` 반환."""
    result = await session.execute(select(ArgusUser).where(ArgusUser.id == user_id))
    user = result.scalars().first()
    if not user:
        return None
    return await _build_user_response(session, user)


async def list_users(
    session: AsyncSession,
    status: str | None = None,
    role: str | None = None,
    search: str | None = None,
    organization: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> PaginatedUserResponse:
    """필터·페이지네이션을 적용한 사용자 목록 조회."""
    base = (
        select(ArgusUser, ArgusRole.role_id.label("role_code"))
        .join(ArgusRole, ArgusUser.role_id == ArgusRole.id)
    )

    if status:
        base = base.where(ArgusUser.status.in_([status]))
    if role:
        base = base.where(ArgusRole.role_id.in_([role]))
    if organization:
        base = base.where(ArgusUser.organization == organization)
    if search:
        pattern = f"%{search}%"
        base = base.where(
            or_(
                ArgusUser.username.ilike(pattern),
                ArgusUser.first_name.ilike(pattern),
                ArgusUser.last_name.ilike(pattern),
                func.concat(ArgusUser.last_name, ArgusUser.first_name).ilike(pattern),
                ArgusUser.email.ilike(pattern),
                ArgusUser.phone_number.ilike(pattern),
                ArgusUser.organization.ilike(pattern),
                ArgusUser.department.ilike(pattern),
            )
        )

    count_query = select(func.count()).select_from(base.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    query = base.order_by(ArgusUser.created_at.desc())
    if page_size > 0:
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
    result = await session.execute(query)
    rows = result.all()

    items = [
        UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            organization=user.organization,
            department=user.department,
            phone_number=user.phone_number,
            status=UserStatus(user.status),
            role=role_code or "unknown",
            created_at=user.created_at,
            updated_at=user.updated_at,
        )
        for user, role_code in rows
    ]

    return PaginatedUserResponse(items=items, total=total, page=page, page_size=page_size)


async def upsert_external_user(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    first_name: str,
    last_name: str,
    organization: str | None,
    department: str | None,
    role_code: str,
) -> None:
    """Keycloak/LDAP 로그인 사용자를 ``argus_users`` 에 JIT upsert."""
    role = (await session.execute(
        select(ArgusRole).where(ArgusRole.role_id == role_code)
    )).scalars().first()
    if role is None:
        logger.warning("JIT upsert 건너뜀: 역할 '%s' 없음", role_code)
        return

    org = organization or None
    dept = department or None
    safe_email = email or f"{username}@keycloak.local"

    existing = (await session.execute(
        select(ArgusUser).where(ArgusUser.username == username)
    )).scalars().first()

    if existing:
        existing.email = safe_email
        existing.first_name = first_name or existing.first_name or username
        existing.last_name = last_name or existing.last_name or ""
        existing.organization = org
        existing.department = dept
        existing.role_id = role.id
        existing.status = "active"
    else:
        session.add(ArgusUser(
            username=username,
            email=safe_email,
            first_name=first_name or username,
            last_name=last_name or "",
            organization=org,
            department=dept,
            phone_number=None,
            password_hash="(external/keycloak)",  # 로컬 인증 미사용
            status="active",
            role_id=role.id,
        ))
    await session.commit()
    logger.info("외부 사용자 JIT upsert 완료: %s (role=%s)", username, role_code)


async def list_organizations(session: AsyncSession) -> list[str]:
    """등록된 소속(조직) 고유 목록 — 소속 드롭다운 필터용."""
    rows = (await session.execute(
        select(ArgusUser.organization)
        .where(ArgusUser.organization.isnot(None), ArgusUser.organization != "")
        .distinct()
        .order_by(ArgusUser.organization)
    )).scalars().all()
    return [o for o in rows if o]


# ---------------------------------------------------------------------------
# 역할 처리
# ---------------------------------------------------------------------------

async def list_roles(session: AsyncSession) -> list[RoleResponse]:
    """모든 역할 목록 반환. ID 오름차순."""
    result = await session.execute(select(ArgusRole).order_by(ArgusRole.id))
    roles = result.scalars().all()
    return [RoleResponse.model_validate(r) for r in roles]


async def seed_roles(session: AsyncSession) -> None:
    """기본 역할(Admin/Superuser/User) 이 없으면 삽입한다(멱등)."""
    default_roles = [
        (RoleName.ADMIN.value, "Admin", "Administrator with full access"),
        (RoleName.SUPERUSER.value, "Superuser", "Superuser with elevated access"),
        (RoleName.USER.value, "User", "Standard user with limited access"),
    ]
    for rid, display_name, desc in default_roles:
        existing = await _get_role_by_role_id(session, rid)
        if not existing:
            session.add(ArgusRole(role_id=rid, name=display_name, description=desc))
            logger.info("역할 시드 생성: %s (%s)", rid, display_name)
    await session.commit()


async def seed_admin_user(session: AsyncSession) -> None:
    """로컬 인증 모드에서 사용자가 한 명도 없으면 기본 관리자(admin/admin)를 생성.

    최초 로그인 후 반드시 비밀번호를 변경해야 한다(must_change_password=True).
    """
    from app.core.config import settings
    if settings.auth_type != "local":
        return

    count = (await session.execute(select(func.count()).select_from(ArgusUser))).scalar() or 0
    if count > 0:
        return

    admin_role = await _get_role_by_role_id(session, RoleName.ADMIN.value)
    if not admin_role:
        return

    user = ArgusUser(
        username="admin",
        # 유효한 도메인을 사용한다. ``.local`` 등 특수목적/예약 도메인은 EmailStr 검증에서
        # 거부되어, 시드 계정의 프로필 수정(PUT, EmailStr) 시 422 가 발생한다.
        email="admin@argus.io",
        first_name="Admin",
        last_name="User",
        password_hash=_hash_password("admin"),
        status="active",
        must_change_password=True,
        role_id=admin_role.id,
    )
    session.add(user)
    await session.commit()
    logger.info("기본 관리자 계정 시드 생성: admin/admin (최초 로그인 후 비밀번호 변경 필요)")
