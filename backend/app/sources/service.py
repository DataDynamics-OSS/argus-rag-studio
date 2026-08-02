# SPDX-License-Identifier: Apache-2.0
"""스토리지 소스 서비스 — CRUD + 자격증명 암호화 + 어댑터 획득 + 정책 참조 가드.

자격증명은 Fernet 대칭 암호화로 저장한다. 키는 ``ARGUS_SOURCE_SECRET_KEY``(권장, 운영) 또는
앱 JWT 서명키에서 유도한다 — 키 교체 시 기존 secret 은 복호화 불가하므로 소스에서 재입력한다.

소스 ``name`` 은 라우팅 규칙(path_rule 의 storage 필터)이 참조하는 논리 식별자다. 활성 정책이
참조 중인 소스의 이름 변경/삭제는 409 로 거부한다(정책을 먼저 수정하도록).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import uuid

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import LOCAL_JWT_SECRET_KEY
from app.sources.adapters import (
    SOURCE_KINDS,
    SourceAdapter,
    get_source_adapter,
    normalize_source_path,
)
from app.sources.models import RagStorageSource
from app.sources.schemas import SourceResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 자격증명 암호화
# ---------------------------------------------------------------------------

def _fernet() -> Fernet:
    secret = os.environ.get("ARGUS_SOURCE_SECRET_KEY") or LOCAL_JWT_SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_secret(secret: dict) -> str:
    return _fernet().encrypt(json.dumps(secret, ensure_ascii=False).encode()).decode()


def decrypt_secret(secret_enc: str | None) -> dict | None:
    if not secret_enc:
        return None
    try:
        return json.loads(_fernet().decrypt(secret_enc.encode()))
    except (InvalidToken, ValueError):
        # 키 교체/손상 — 자격증명 재입력 필요. 소스 접근 시 인증 실패로 드러난다.
        logger.warning("소스 자격증명 복호화 실패(암호화 키 변경?) — 재입력 필요")
        return None


# ---------------------------------------------------------------------------
# 검증
# ---------------------------------------------------------------------------

def validate_source(kind: str, config: dict) -> list[str]:
    """kind/config 검증 — 오류 메시지 리스트(빈 리스트면 유효)."""
    errors: list[str] = []
    if kind not in SOURCE_KINDS:
        errors.append(f"지원하지 않는 소스 종류: {kind} (가능: {', '.join(SOURCE_KINDS)})")
        return errors
    if kind == "s3":
        if not (config.get("bucket") or "").strip():
            errors.append("s3 소스는 bucket 이 필요합니다.")
    elif kind == "nas":
        mount = (config.get("mount_path") or "").strip()
        if not mount or not os.path.isabs(mount):
            errors.append("nas 소스는 절대 경로 mount_path 가 필요합니다.")
    try:
        normalize_source_path(config.get("base_prefix") or "", allow_empty=True)
    except ValueError as e:
        errors.append(f"base_prefix 오류: {e}")
    return errors


async def referencing_active_policy(session: AsyncSession, name: str) -> bool:
    """활성 라우팅 정책의 path_rule 규칙이 이 소스 이름을 참조하는지."""
    from app.routing.models import RagRoutingPolicy, RagRoutingPolicyVersion

    policy = (await session.execute(
        select(RagRoutingPolicy).where(RagRoutingPolicy.name == "default")
    )).scalars().first()
    if not policy:
        return False
    row = (await session.execute(
        select(RagRoutingPolicyVersion).where(
            RagRoutingPolicyVersion.policy_id == policy.id,
            RagRoutingPolicyVersion.version == policy.active_version,
        )
    )).scalars().first()
    if not row:
        return False
    try:
        config = json.loads(row.config_json)
    except ValueError:
        return False
    for stage in (config.get("stages") or []):
        if not isinstance(stage, dict) or stage.get("id") != "path_rule":
            continue
        for rule in ((stage.get("config") or {}).get("rules") or []):
            if isinstance(rule, dict) and (rule.get("storage") or "").strip() == name:
                return True
    return False


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def source_response(source: RagStorageSource) -> SourceResponse:
    try:
        config = json.loads(source.config_json or "{}")
    except ValueError:
        config = {}
    return SourceResponse(
        id=source.id, source_id=source.source_id, name=source.name, kind=source.kind,
        description=source.description, config=config,
        has_secret=bool(source.secret_enc), enabled=source.enabled,
        created_by=source.created_by, created_at=source.created_at, updated_at=source.updated_at,
    )


async def list_sources(session: AsyncSession) -> list[RagStorageSource]:
    return list((await session.execute(
        select(RagStorageSource).order_by(RagStorageSource.name)
    )).scalars().all())


async def get_source(session: AsyncSession, source_id: str) -> RagStorageSource | None:
    return (await session.execute(
        select(RagStorageSource).where(RagStorageSource.source_id == source_id)
    )).scalars().first()


async def get_source_by_pk(session: AsyncSession, pk: int) -> RagStorageSource | None:
    """내부 pk 조회 — 워치(FK) 실행 경로용."""
    return (await session.execute(
        select(RagStorageSource).where(RagStorageSource.id == pk)
    )).scalar_one_or_none()


async def get_source_by_name(session: AsyncSession, name: str) -> RagStorageSource | None:
    return (await session.execute(
        select(RagStorageSource).where(RagStorageSource.name == name)
    )).scalars().first()


async def create_source(
    session: AsyncSession, *, name: str, kind: str, description: str | None,
    config: dict, secret: dict | None, enabled: bool, created_by: str | None,
) -> RagStorageSource:
    source = RagStorageSource(
        source_id=str(uuid.uuid4()), name=name.strip(), kind=kind,
        description=description, config_json=json.dumps(config, ensure_ascii=False),
        secret_enc=encrypt_secret(secret) if secret else None,
        enabled=enabled, created_by=created_by,
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


def adapter_for(source: RagStorageSource) -> SourceAdapter:
    """소스 행 → 어댑터(설정 파싱 + 자격증명 복호화)."""
    try:
        config = json.loads(source.config_json or "{}")
    except ValueError:
        config = {}
    return get_source_adapter(source.kind, config, decrypt_secret(source.secret_enc))
