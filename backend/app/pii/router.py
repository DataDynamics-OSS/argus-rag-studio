# SPDX-License-Identifier: Apache-2.0
"""PII 규칙 관리 API (/api/v1/pii/rules) + 테스트."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, SuperUser
from app.core.database import get_session
from app.pii import service
from app.pii.schemas import (
    PiiFunctionCreateRequest,
    PiiFunctionResponse,
    PiiFunctionTestRequest,
    PiiFunctionTestResponse,
    PiiFunctionUpdateRequest,
    PiiRuleCreateRequest,
    PiiRuleResponse,
    PiiRuleUpdateRequest,
    PiiTestRequest,
    PiiTestResponse,
)

router = APIRouter(prefix="/pii", tags=["pii"])


@router.get("/rules", response_model=list[PiiRuleResponse])
async def list_rules(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    return await service.list_rules(session)


@router.post("/rules", response_model=PiiRuleResponse, status_code=201)
async def create_rule(req: PiiRuleCreateRequest, user: SuperUser, session: AsyncSession = Depends(get_session)):
    try:
        return await service.create_rule(session, req, created_by=user.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/rules/{rule_id}", response_model=PiiRuleResponse)
async def update_rule(
    rule_id: str, req: PiiRuleUpdateRequest, _user: SuperUser, session: AsyncSession = Depends(get_session)
):
    rule = await service.get_rule(session, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="규칙을 찾을 수 없습니다.")
    try:
        return await service.update_rule(session, rule, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: str, _user: SuperUser, session: AsyncSession = Depends(get_session)):
    rule = await service.get_rule(session, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="규칙을 찾을 수 없습니다.")
    await service.delete_rule(session, rule)


@router.post("/test", response_model=PiiTestResponse)
async def test_rules(req: PiiTestRequest, _user: CurrentUser, session: AsyncSession = Depends(get_session)):
    """샘플 텍스트에 enabled 규칙을 적용한 마스킹 결과·매치 수를 반환(실제 인제스천과 동일 로직)."""
    return await service.test_rules(session, req.text, req.categories)


# ── 사용자 정의 함수 ──────────────────────────────────────────────────────────


@router.get("/functions", response_model=list[PiiFunctionResponse])
async def list_functions(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    return await service.list_functions(session)


@router.post("/functions", response_model=PiiFunctionResponse, status_code=201)
async def create_function(req: PiiFunctionCreateRequest, user: SuperUser, session: AsyncSession = Depends(get_session)):
    try:
        return await service.create_function(session, req, created_by=user.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/functions/{function_id}", response_model=PiiFunctionResponse)
async def update_function(
    function_id: str, req: PiiFunctionUpdateRequest, _user: SuperUser, session: AsyncSession = Depends(get_session)
):
    fn = await service.get_function(session, function_id)
    if not fn:
        raise HTTPException(status_code=404, detail="함수를 찾을 수 없습니다.")
    try:
        return await service.update_function(session, fn, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/functions/{function_id}", status_code=204)
async def delete_function(function_id: str, _user: SuperUser, session: AsyncSession = Depends(get_session)):
    fn = await service.get_function(session, function_id)
    if not fn:
        raise HTTPException(status_code=404, detail="함수를 찾을 수 없습니다.")
    await service.delete_function(session, fn)


@router.post("/functions/test", response_model=PiiFunctionTestResponse)
async def test_function(req: PiiFunctionTestRequest, _user: SuperUser):
    """샌드박스에서 코드의 redact(text) 를 샘플에 실행한 결과/오류를 반환."""
    return await service.test_function(req.code, req.text, req.timeout_ms)
