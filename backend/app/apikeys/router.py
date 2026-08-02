# SPDX-License-Identifier: Apache-2.0
"""API 키(서비스 계정) 관리 API — admin 전용.

- GET    /api-keys        : 발급된 키 목록(메타데이터, 평문 미포함)
- POST   /api-keys        : 키 발급(응답에 평문 키 1회 노출)
- PUT    /api-keys/{id}   : 이름·설명·활성 상태 수정
- DELETE /api-keys/{id}   : 키 폐기(영구 삭제)

발급된 키는 ``X-API-Key: <key>`` 또는 ``Authorization: Bearer <key>`` 헤더로 RAG
백엔드(search/query/chat 등)를 인증 호출하는 데 사용한다.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.apikeys import service
from app.apikeys.schemas import (
    ApiKeyCreatedResponse,
    ApiKeyCreateRequest,
    ApiKeyResponse,
    ApiKeyUpdateRequest,
)
from app.core.auth import AdminUser
from app.core.database import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(_admin: AdminUser, session: AsyncSession = Depends(get_session)):
    """발급된 API 키 목록(평문은 포함하지 않음)."""
    return await service.list_keys(session)


@router.post("", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_api_key(
    req: ApiKeyCreateRequest, admin: AdminUser, session: AsyncSession = Depends(get_session),
):
    """API 키를 발급한다. 평문 키는 이 응답에서만 노출되니 안전하게 보관하세요."""
    api_key, raw_key = await service.create_key(session, req, created_by=admin.username)
    return ApiKeyCreatedResponse(api_key=raw_key, **ApiKeyResponse.model_validate(api_key).model_dump())


@router.put("/{key_id}", response_model=ApiKeyResponse)
async def update_api_key(
    key_id: int, req: ApiKeyUpdateRequest, _admin: AdminUser,
    session: AsyncSession = Depends(get_session),
):
    """API 키 메타데이터/활성 상태를 수정한다."""
    api_key = await service.update_key(session, key_id, req)
    if not api_key:
        raise HTTPException(status_code=404, detail="API 키를 찾을 수 없습니다.")
    return api_key


@router.delete("/{key_id}")
async def delete_api_key(
    key_id: int, _admin: AdminUser, session: AsyncSession = Depends(get_session),
):
    """API 키를 폐기(영구 삭제)한다."""
    deleted = await service.delete_key(session, key_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="API 키를 찾을 수 없습니다.")
    return {"detail": "API 키가 폐기되었습니다."}
