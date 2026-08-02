# SPDX-License-Identifier: Apache-2.0
"""컬렉션(지식베이스) API.

CRUD 를 제공하는 FastAPI 라우터(prefix ``/collections``). 비즈니스 로직은 ``service`` 에
위임하고 라우터는 HTTP 변환·권한·예외 매핑만 담당한다.

권한 정책:
    - 조회(GET): 로그인 사용자
    - 생성/수정: 슈퍼유저 또는 관리자
    - 삭제: 생성자 본인 또는 관리자(``assert_owner_or_admin``)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections import service
from app.collections.models import RagCollection
from app.collections.schemas import (
    CollectionCreateRequest,
    CollectionReindexRequest,
    CollectionReindexResponse,
    CollectionResponse,
    CollectionUpdateRequest,
    PaginatedCollectionResponse,
)
from app.core.auth import CurrentUser, SuperUser, assert_owner_or_admin
from app.core.database import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/collections", tags=["collections"])


@router.post("", response_model=CollectionResponse, status_code=201)
async def create_collection(
    req: CollectionCreateRequest, user: SuperUser, session: AsyncSession = Depends(get_session),
):
    """컬렉션 생성. 이름 중복은 409, 설정 검증 실패(차원/모델 등)는 400."""
    try:
        return await service.create_collection(session, req, created_by=user.username)
    except service.DuplicateCollectionError as e:
        logger.warning("create_collection 이름 중복: %s", e)
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        logger.warning("create_collection 검증 실패: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=PaginatedCollectionResponse)
async def list_collections(
    _user: CurrentUser,
    status: str | None = Query(None, description="Filter by status (active/archived)"),
    search: str | None = Query(None, description="Search name/description"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=0, le=200),
    session: AsyncSession = Depends(get_session),
):
    """필터·페이지네이션을 적용해 컬렉션 목록을 반환한다."""
    return await service.list_collections(
        session, status=status, search=search, page=page, page_size=page_size,
    )


@router.get("/{collection_uuid}", response_model=CollectionResponse)
async def get_collection(
    collection_uuid: str, _user: CurrentUser, session: AsyncSession = Depends(get_session),
):
    """외부 노출 UUID(collection_id)로 컬렉션 단건 조회. 없으면 404."""
    collection = await service.get_collection_by_uuid(session, collection_uuid)
    if not collection:
        raise HTTPException(status_code=404, detail="컬렉션을 찾을 수 없습니다.")
    return collection


@router.put("/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: int, req: CollectionUpdateRequest, _user: SuperUser,
    session: AsyncSession = Depends(get_session),
):
    """컬렉션 메타데이터 부분 갱신(임베딩 설정은 변경 불가)."""
    collection = await service.update_collection(session, collection_id, req)
    if not collection:
        raise HTTPException(status_code=404, detail="컬렉션을 찾을 수 없습니다.")
    return collection


@router.post("/{collection_id}/reindex", response_model=CollectionReindexResponse, status_code=202)
async def reindex_collection(
    collection_id: int, req: CollectionReindexRequest, _user: SuperUser,
    session: AsyncSession = Depends(get_session),
):
    """색인 설정(임베딩/청킹) 변경 + 전체 문서 재인덱싱(슈퍼유저). 설정 오류는 400."""
    try:
        result = await service.reindex_collection(session, collection_id, req)
    except ValueError as e:
        logger.warning("reindex_collection 실패: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    if not result:
        raise HTTPException(status_code=404, detail="컬렉션을 찾을 수 없습니다.")
    return result


@router.delete("/{collection_id}")
async def delete_collection(
    collection_id: int, user: CurrentUser, session: AsyncSession = Depends(get_session),
):
    """컬렉션 삭제(하위 문서 CASCADE). 생성자 본인 또는 관리자만 허용."""
    row = (await session.execute(
        select(RagCollection).where(RagCollection.id == collection_id)
    )).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="컬렉션을 찾을 수 없습니다.")
    assert_owner_or_admin(user, row.created_by, "이 컬렉션")
    await service.delete_collection(session, collection_id)
    return {"status": "ok", "message": "Collection deleted"}
