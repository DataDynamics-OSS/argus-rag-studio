# SPDX-License-Identifier: Apache-2.0
"""PII 규칙 CRUD + 적용/테스트 서비스."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.pii import redact, sandbox
from app.pii.models import RagPiiFunction, RagPiiRule
from app.pii.schemas import (
    PiiFunctionCreateRequest,
    PiiFunctionResponse,
    PiiFunctionTestResponse,
    PiiFunctionUpdateRequest,
    PiiRuleCreateRequest,
    PiiRuleResponse,
    PiiRuleUpdateRequest,
    PiiTestMatch,
    PiiTestResponse,
)

logger = logging.getLogger(__name__)


def _resp(r: RagPiiRule) -> PiiRuleResponse:
    return PiiRuleResponse(
        id=r.id, rule_id=r.rule_id, name=r.name, category=r.category, pattern=r.pattern,
        flags=r.flags, mask=r.mask, enabled=r.enabled, description=r.description,
        created_by=r.created_by, created_at=r.created_at, updated_at=r.updated_at,
    )


def _rule_dict(r: RagPiiRule) -> dict:
    """transform/테스트가 쓰는 plain dict(세션 분리 후에도 안전)."""
    return {
        "rule_id": r.rule_id, "name": r.name, "category": r.category,
        "pattern": r.pattern, "flags": r.flags, "mask": r.mask,
    }


async def list_rules(session: AsyncSession) -> list[PiiRuleResponse]:
    rows = (await session.execute(
        select(RagPiiRule).order_by(RagPiiRule.category, RagPiiRule.name)
    )).scalars().all()
    return [_resp(r) for r in rows]


async def list_enabled_dicts(session: AsyncSession, categories: list[str] | None = None) -> list[dict]:
    """enabled 규칙을 plain dict 로(ctx 주입·테스트). categories 주면 해당 분류만."""
    stmt = select(RagPiiRule).where(RagPiiRule.enabled.is_(True)).order_by(RagPiiRule.category, RagPiiRule.name)
    if categories:
        stmt = stmt.where(RagPiiRule.category.in_(categories))
    rows = (await session.execute(stmt)).scalars().all()
    return [_rule_dict(r) for r in rows]


async def get_rule(session: AsyncSession, rule_uuid: str) -> RagPiiRule | None:
    return (await session.execute(
        select(RagPiiRule).where(RagPiiRule.rule_id == rule_uuid)
    )).scalars().first()


async def create_rule(session: AsyncSession, req: PiiRuleCreateRequest, created_by: str | None) -> PiiRuleResponse:
    err = redact.validate_pattern(req.pattern, req.flags)
    if err:
        raise ValueError(f"정규식이 올바르지 않습니다: {err}")
    rule = RagPiiRule(
        rule_id=str(uuid.uuid4()), name=req.name, category=req.category, pattern=req.pattern,
        flags=req.flags, mask=req.mask, enabled=req.enabled, description=req.description,
        created_by=created_by,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    logger.info("PII 규칙 생성: %s (%s)", rule.name, rule.category)
    return _resp(rule)


async def update_rule(session: AsyncSession, rule: RagPiiRule, req: PiiRuleUpdateRequest) -> PiiRuleResponse:
    data = req.model_dump(exclude_unset=True)
    new_pattern = data.get("pattern", rule.pattern)
    new_flags = data.get("flags", rule.flags)
    if "pattern" in data or "flags" in data:
        err = redact.validate_pattern(new_pattern, new_flags)
        if err:
            raise ValueError(f"정규식이 올바르지 않습니다: {err}")
    for k, v in data.items():
        setattr(rule, k, v)
    await session.commit()
    await session.refresh(rule)
    return _resp(rule)


async def delete_rule(session: AsyncSession, rule: RagPiiRule) -> None:
    await session.delete(rule)
    await session.commit()


async def test_rules(session: AsyncSession, text: str, categories: list[str] | None) -> PiiTestResponse:
    rules = await list_enabled_dicts(session, categories)
    masked, matches, invalid = redact.apply_rules_with_stats(text, rules)
    return PiiTestResponse(
        masked=masked,
        matches=[PiiTestMatch(**m) for m in matches],
        invalid=invalid,
    )


# ── 사용자 정의 함수 ──────────────────────────────────────────────────────────


def _fn_resp(f: RagPiiFunction) -> PiiFunctionResponse:
    return PiiFunctionResponse(
        id=f.id, function_id=f.function_id, name=f.name, code=f.code, timeout_ms=f.timeout_ms,
        enabled=f.enabled, description=f.description, created_by=f.created_by,
        created_at=f.created_at, updated_at=f.updated_at,
    )


async def list_functions(session: AsyncSession) -> list[PiiFunctionResponse]:
    rows = (await session.execute(
        select(RagPiiFunction).order_by(RagPiiFunction.name)
    )).scalars().all()
    return [_fn_resp(f) for f in rows]


async def list_enabled_functions(session: AsyncSession) -> list[dict]:
    """enabled 함수를 plain dict 로(ctx 주입). transform 이 샌드박스로 실행."""
    rows = (await session.execute(
        select(RagPiiFunction).where(RagPiiFunction.enabled.is_(True)).order_by(RagPiiFunction.name)
    )).scalars().all()
    return [{"function_id": f.function_id, "name": f.name, "code": f.code, "timeout_ms": f.timeout_ms} for f in rows]


async def get_function(session: AsyncSession, function_uuid: str) -> RagPiiFunction | None:
    return (await session.execute(
        select(RagPiiFunction).where(RagPiiFunction.function_id == function_uuid)
    )).scalars().first()


async def create_function(session: AsyncSession, req: PiiFunctionCreateRequest, created_by: str | None) -> PiiFunctionResponse:
    err = sandbox.validate_code(req.code)
    if err:
        raise ValueError(err)
    fn = RagPiiFunction(
        function_id=str(uuid.uuid4()), name=req.name, code=req.code, timeout_ms=req.timeout_ms,
        enabled=req.enabled, description=req.description, created_by=created_by,
    )
    session.add(fn)
    await session.commit()
    await session.refresh(fn)
    logger.info("PII 함수 생성: %s", fn.name)
    return _fn_resp(fn)


async def update_function(session: AsyncSession, fn: RagPiiFunction, req: PiiFunctionUpdateRequest) -> PiiFunctionResponse:
    data = req.model_dump(exclude_unset=True)
    if "code" in data:
        err = sandbox.validate_code(data["code"])
        if err:
            raise ValueError(err)
    for k, v in data.items():
        setattr(fn, k, v)
    await session.commit()
    await session.refresh(fn)
    return _fn_resp(fn)


async def delete_function(session: AsyncSession, fn: RagPiiFunction) -> None:
    await session.delete(fn)
    await session.commit()


async def test_function(code: str, text: str, timeout_ms: int) -> PiiFunctionTestResponse:
    import asyncio
    result, error = await asyncio.to_thread(sandbox.run_function, code, text, timeout_ms)
    return PiiFunctionTestResponse(result=result, error=error)
