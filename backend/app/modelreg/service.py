# SPDX-License-Identifier: Apache-2.0
"""모델 레지스트리 서비스 — 시드·CRUD·Model Repository 보유 병합.

설계: design/model-registry.md. 배포(model_prep)·이미지 주입 콤보 등 세션 없는 호출부를
위해 자체 세션(async_session)을 여는 조회 함수(list_models/resolve_vlm_model)를 제공한다.
"""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modelreg.models import RagModelRegistry
from app.modelreg.seeds import DEFAULT_VLM_NAME, KIND_TARGETS, SEED_MODELS, seed_entry

logger = logging.getLogger(__name__)


# ── 시드 ─────────────────────────────────────────────────────────────────────

async def ensure_seeds(session: AsyncSession) -> int:
    """시드 + 구(舊) 설정 CSV(image_classification.extra_models)를 없는 것만 투입."""
    rows = (await session.execute(select(RagModelRegistry.kind, RagModelRegistry.name))).all()
    existing = {(k, n) for k, n in rows}
    added = 0

    def _insert(e: dict, builtin: bool) -> None:
        nonlocal added
        if (e["kind"], e["name"]) in existing:
            return
        session.add(RagModelRegistry(
            model_id=str(uuid.uuid4()), kind=e["kind"], name=e["name"], repo=e["repo"],
            revision=e["revision"], source=e["source"], target=e["target"],
            params_json=json.dumps(e["params"], ensure_ascii=False),
            note=e["note"], enabled=True, builtin=builtin, created_by="seed",
        ))
        existing.add((e["kind"], e["name"]))
        added += 1

    for m in SEED_MODELS:
        _insert(seed_entry(m), builtin=True)

    # 구 방식 마이그레이션 — 설정 CSV 로 추가했던 vlm 모델을 레지스트리로 흡수.
    from app.core.config import settings
    from app.servermgr.vlm_models import _parse_extra

    raw = getattr(settings, "image_classification_extra_models", "") or ""
    for entry in raw.split(","):
        m = _parse_extra(entry)
        if m:
            _insert(seed_entry({
                "kind": "vlm", "name": m["name"], "repo": m["repo"],
                "params": {"max_len": m["max_len"]}, "note": "설정 extra_models 마이그레이션",
            }), builtin=False)

    if added:
        await session.commit()
        logger.info("모델 레지스트리 시드 %d건 투입", added)
    return added


# ── 응답 변환 ─────────────────────────────────────────────────────────────────

def entry_dict(e: RagModelRegistry) -> dict:
    """ORM → dict. 기존 카탈로그 소비처(배포·프런트)와 필드 호환(max_len 등 평탄화)."""
    try:
        params = json.loads(e.params_json or "{}")
    except ValueError:
        params = {}
    return {
        "model_id": e.model_id, "kind": e.kind, "name": e.name, "repo": e.repo,
        "revision": e.revision, "source": e.source, "target": e.target,
        "note": e.note or "", "enabled": e.enabled, "builtin": e.builtin,
        "max_len": params.get("max_len") or (8192 if e.kind == "vlm" else None),
        "approx_gb": params.get("approx_gb"),
    }


# ── CRUD (세션 주입 — 라우터용) ────────────────────────────────────────────────

async def list_entries(
    session: AsyncSession, kind: str | None = None, enabled_only: bool = False
) -> list[RagModelRegistry]:
    q = select(RagModelRegistry).order_by(RagModelRegistry.kind, RagModelRegistry.id)
    if kind:
        q = q.where(RagModelRegistry.kind == kind)
    if enabled_only:
        q = q.where(RagModelRegistry.enabled.is_(True))
    return list((await session.execute(q)).scalars())


async def get_entry(session: AsyncSession, model_id: str) -> RagModelRegistry | None:
    q = select(RagModelRegistry).where(RagModelRegistry.model_id == model_id)
    return (await session.execute(q)).scalar_one_or_none()


async def create_entry(session: AsyncSession, data: dict, username: str) -> RagModelRegistry:
    params: dict = {}
    if data.get("max_len"):
        params["max_len"] = data["max_len"]
    e = RagModelRegistry(
        model_id=str(uuid.uuid4()), kind=data["kind"], name=data["name"], repo=data["repo"],
        revision=data.get("revision") or "main", source="hf",
        target=KIND_TARGETS.get(data["kind"], "hf-cache"),
        params_json=json.dumps(params, ensure_ascii=False),
        note=data.get("note") or "", enabled=data.get("enabled", True),
        builtin=False, created_by=username,
    )
    session.add(e)
    await session.commit()
    await session.refresh(e)
    return e


async def update_entry(session: AsyncSession, e: RagModelRegistry, data: dict) -> RagModelRegistry:
    for field in ("name", "repo", "revision", "note", "enabled"):
        if data.get(field) is not None:
            setattr(e, field, data[field])
    if data.get("max_len") is not None:
        try:
            params = json.loads(e.params_json or "{}")
        except ValueError:
            params = {}
        params["max_len"] = data["max_len"]
        e.params_json = json.dumps(params, ensure_ascii=False)
    await session.commit()
    await session.refresh(e)
    return e


async def delete_entry(session: AsyncSession, e: RagModelRegistry) -> None:
    await session.delete(e)
    await session.commit()


# ── 세션 없는 조회 (배포 플로우·콤보 API 용) ───────────────────────────────────

async def list_models(kind: str | None = None, enabled_only: bool = True) -> list[dict]:
    """레지스트리 조회(자체 세션) — 배포 플로우가 사용. dict 는 기존 카탈로그 필드 호환."""
    from app.core.database import async_session

    async with async_session() as session:
        return [entry_dict(e) for e in await list_entries(session, kind, enabled_only)]


async def resolve_vlm_model(key: str | None) -> dict | None:
    """vlm 모델을 name(served-model-name) 또는 repo 로 조회. 미지정=기본(없으면 첫 항목)."""
    models = await list_models("vlm")
    if not key or not str(key).strip():
        return next((m for m in models if m["name"] == DEFAULT_VLM_NAME),
                    models[0] if models else None)
    k = str(key).strip()
    return next((m for m in models if m["name"] == k or m["repo"] == k), None)


# ── Model Repository(argus-models) 보유 병합 ──────────────────────────────────

def list_model_holdings() -> dict[str, list[str]]:
    """모델 저장소의 보유 현황 — {kind/name: [revision…]}(manifest.json 존재 기준).

    버킷이 없거나 S3 미가용이면 빈 dict(보유 미확인)."""
    from botocore.exceptions import ClientError

    from app.core.config import settings
    from app.storage.client import _get_client

    holdings: dict[str, list[str]] = {}
    try:
        client = _get_client()
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.os_models_bucket):
            for obj in page.get("Contents", []):
                parts = obj["Key"].split("/")
                # {kind}/{name}/{revision}/manifest.json
                if len(parts) == 4 and parts[3] == "manifest.json":
                    holdings.setdefault(f"{parts[0]}/{parts[1]}", []).append(parts[2])
    except ClientError:
        return {}
    return holdings


async def catalog_with_holdings(session: AsyncSession) -> dict:
    """레지스트리 전체 + 보유 여부·리비전 병합 + 매니페스트 외 반입분(unlisted)."""
    import asyncio

    from app.core.config import settings

    models = [entry_dict(e) for e in await list_entries(session)]
    holdings = await asyncio.to_thread(list_model_holdings)
    listed = set()
    for m in models:
        key = f"{m['kind']}/{m['name']}"
        listed.add(key)
        m["available"] = key in holdings
        m["revisions"] = sorted(holdings.get(key, []))
    unlisted = [
        {"key": k, "revisions": sorted(v)} for k, v in sorted(holdings.items())
        if k not in listed
    ]
    return {"models": models, "unlisted": unlisted, "bucket": settings.os_models_bucket}
