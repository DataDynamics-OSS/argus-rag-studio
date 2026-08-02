# SPDX-License-Identifier: Apache-2.0
"""API 키(서비스 계정) 서비스 계층.

키 발급 시 ``argus_sk_<랜덤>`` 평문을 생성해 호출자에게 1회만 반환하고, DB 에는
SHA-256 해시만 저장한다(비밀번호와 동일한 원칙). 검증(``authenticate``)은 들어온 평문을
같은 방식으로 해시해 일치하는 활성·미만료 키를 찾는다.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apikeys.models import ApiKey
from app.apikeys.schemas import ApiKeyCreateRequest, ApiKeyUpdateRequest

logger = logging.getLogger(__name__)

# 평문 키 접두사 — Authorization: Bearer 로 와도 JWT 와 구분하는 식별자이기도 하다.
KEY_PREFIX = "argus_sk_"
# 표시용으로 저장할 앞부분 길이(접두사 + 랜덤 일부)
_DISPLAY_PREFIX_LEN = 16


def _hash_key(raw_key: str) -> str:
    """평문 키의 SHA-256 16진 해시(64자)."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _generate_key() -> tuple[str, str, str]:
    """새 평문 키를 생성해 (평문, 표시용 접두사, 해시) 를 반환한다."""
    raw_key = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return raw_key, raw_key[:_DISPLAY_PREFIX_LEN], _hash_key(raw_key)


async def list_keys(session: AsyncSession) -> list[ApiKey]:
    """모든 API 키 메타데이터를 최신순으로 반환한다."""
    result = await session.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
    return list(result.scalars().all())


async def get_key(session: AsyncSession, key_id: int) -> ApiKey | None:
    result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
    return result.scalars().first()


async def create_key(
    session: AsyncSession, req: ApiKeyCreateRequest, created_by: str | None,
) -> tuple[ApiKey, str]:
    """API 키를 발급한다. (ORM 행, 평문 키) 를 반환 — 평문은 호출자가 1회만 노출."""
    raw_key, key_prefix, key_hash = _generate_key()
    expires_at = None
    if req.expires_in_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=req.expires_in_days)

    api_key = ApiKey(
        name=req.name,
        description=req.description,
        key_prefix=key_prefix,
        key_hash=key_hash,
        role_id=req.role.value,
        enabled=True,
        expires_at=expires_at,
        created_by=created_by,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)
    logger.info("API 키 발급: id=%s name=%s role=%s by=%s", api_key.id, api_key.name,
                api_key.role_id, created_by)
    return api_key, raw_key


async def update_key(
    session: AsyncSession, key_id: int, req: ApiKeyUpdateRequest,
) -> ApiKey | None:
    """API 키 메타데이터/활성 상태를 부분 갱신한다."""
    api_key = await get_key(session, key_id)
    if not api_key:
        return None
    if req.name is not None:
        api_key.name = req.name
    if req.description is not None:
        api_key.description = req.description
    if req.enabled is not None:
        api_key.enabled = req.enabled
    await session.commit()
    await session.refresh(api_key)
    return api_key


async def delete_key(session: AsyncSession, key_id: int) -> bool:
    """API 키를 영구 삭제(폐기)한다."""
    api_key = await get_key(session, key_id)
    if not api_key:
        return False
    await session.delete(api_key)
    await session.commit()
    logger.info("API 키 폐기: id=%s name=%s", key_id, api_key.name)
    return True


async def authenticate(session: AsyncSession, raw_key: str) -> ApiKey | None:
    """평문 키로 활성·미만료 API 키를 찾고, 마지막 사용 시각을 갱신해 반환한다.

    유효하지 않으면(미존재/비활성/만료) ``None`` 을 반환한다.
    """
    if not raw_key or not raw_key.startswith(KEY_PREFIX):
        return None
    key_hash = _hash_key(raw_key)
    result = await session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    api_key = result.scalars().first()
    if not api_key or not api_key.enabled:
        return None
    if api_key.expires_at is not None:
        expires = api_key.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            return None

    api_key.last_used_at = datetime.now(timezone.utc)
    await session.commit()
    return api_key
