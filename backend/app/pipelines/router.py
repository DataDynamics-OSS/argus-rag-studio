# SPDX-License-Identifier: Apache-2.0
"""파이프라인 API — 버전 가능한 RAG 설정.

CRUD + 버전 목록 + diff + 활성 버전 변경(롤백) + 버전 간 비교(실험).
권한: 조회는 로그인 사용자, 생성/수정/삭제/롤백은 슈퍼유저 이상.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections.models import RagCollection
from app.core.auth import CurrentUser, SuperUser
from app.core.database import get_session
from app.pipelines import service
from app.pipelines.schemas import (
    CompareRequest,
    CompareResponse,
    DiffResponse,
    MetaUpdateRequest,
    PipelineConfig,
    PipelineCreateRequest,
    PipelineResponse,
    PipelineUpdateRequest,
    VersionResponse,
    VersionResult,
)
from app.rerank.service import rerank
from app.retrieval import service as retrieval

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


@router.post("", response_model=PipelineResponse, status_code=201)
async def create_pipeline(req: PipelineCreateRequest, user: SuperUser, session: AsyncSession = Depends(get_session)):
    try:
        return await service.create_pipeline(session, req, created_by=user.username)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("", response_model=list[PipelineResponse])
async def list_pipelines(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    return await service.list_pipelines(session)


@router.get("/{pipeline_uuid}", response_model=PipelineResponse)
async def get_pipeline(pipeline_uuid: str, _user: CurrentUser, session: AsyncSession = Depends(get_session)):
    p = await service.get_pipeline_resp_by_uuid(session, pipeline_uuid)
    if not p:
        raise HTTPException(status_code=404, detail="파이프라인을 찾을 수 없습니다.")
    return p


@router.put("/{pipeline_id}/config", response_model=PipelineResponse)
async def update_config(pipeline_id: int, req: PipelineUpdateRequest, user: SuperUser, session: AsyncSession = Depends(get_session)):
    """설정 수정 — 새 버전을 만들고 active 로 만든다."""
    p = await service.get_pipeline(session, pipeline_id)
    if not p:
        raise HTTPException(status_code=404, detail="파이프라인을 찾을 수 없습니다.")
    return await service.update_config(session, p, req.config, req.note, created_by=user.username)


@router.put("/{pipeline_id}/meta", response_model=PipelineResponse)
async def update_meta(pipeline_id: int, req: MetaUpdateRequest, _user: SuperUser, session: AsyncSession = Depends(get_session)):
    """stage / description 등 메타데이터 수정(버전 생성 없음)."""
    p = await service.get_pipeline(session, pipeline_id)
    if not p:
        raise HTTPException(status_code=404, detail="파이프라인을 찾을 수 없습니다.")
    return await service.update_meta(session, p, req.stage, req.description)


@router.post("/{pipeline_id}/activate/{version}", response_model=PipelineResponse)
async def activate_version(pipeline_id: int, version: int, _user: SuperUser, session: AsyncSession = Depends(get_session)):
    """활성 버전을 지정 버전으로 변경(롤백)."""
    p = await service.get_pipeline(session, pipeline_id)
    if not p:
        raise HTTPException(status_code=404, detail="파이프라인을 찾을 수 없습니다.")
    try:
        return await service.set_active(session, p, version)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{pipeline_id}")
async def delete_pipeline(pipeline_id: int, _user: SuperUser, session: AsyncSession = Depends(get_session)):
    if not await service.delete_pipeline(session, pipeline_id):
        raise HTTPException(status_code=404, detail="파이프라인을 찾을 수 없습니다.")
    return {"status": "ok"}


@router.get("/{pipeline_id}/versions", response_model=list[VersionResponse])
async def list_versions(pipeline_id: int, _user: CurrentUser, session: AsyncSession = Depends(get_session)):
    return await service.list_versions(session, pipeline_id)


@router.get("/{pipeline_id}/diff", response_model=DiffResponse)
async def diff(
    pipeline_id: int, _user: CurrentUser,
    from_version: int = Query(..., alias="from"),
    to_version: int = Query(..., alias="to"),
    session: AsyncSession = Depends(get_session),
):
    """두 버전 설정의 필드별 차이를 반환한다."""
    return await service.diff(session, pipeline_id, from_version, to_version)


async def _search_with_config(session, collection, query, cfg: PipelineConfig):
    r = cfg.retrieval
    hits = await retrieval.search(
        session, collection, query, r.mode.value, r.top_k,
        vector_k=r.vector_k, lexical_k=r.lexical_k, rrf_k=r.rrf_k,
        distance_metric=r.distance_metric or None,
    )
    if cfg.rerank.enabled:
        hits = await rerank(query, hits, cfg.rerank.top_n, provider=cfg.rerank.provider)
    return hits


@router.post("/{pipeline_id}/compare", response_model=CompareResponse)
async def compare(pipeline_id: int, req: CompareRequest, _user: CurrentUser, session: AsyncSession = Depends(get_session)):
    """동일 질의를 두 버전 설정으로 검색해 결과를 나란히 반환한다(실험)."""
    p = await service.get_pipeline(session, pipeline_id)
    if not p:
        raise HTTPException(status_code=404, detail="파이프라인을 찾을 수 없습니다.")
    collection = (await session.execute(
        select(RagCollection).where(RagCollection.id == req.collection_id)
    )).scalars().first()
    if not collection:
        raise HTTPException(status_code=404, detail="컬렉션을 찾을 수 없습니다.")

    cfg_a = await service._config_of(session, p.id, req.version_a)
    cfg_b = await service._config_of(session, p.id, req.version_b)
    try:
        hits_a = await _search_with_config(session, collection, req.query, cfg_a)
        hits_b = await _search_with_config(session, collection, req.query, cfg_b)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"비교 검색 실패: {e}")
    return CompareResponse(
        query=req.query,
        a=VersionResult(version=req.version_a, hits=hits_a),
        b=VersionResult(version=req.version_b, hits=hits_b),
    )
