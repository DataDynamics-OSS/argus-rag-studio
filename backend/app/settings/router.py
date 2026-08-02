# SPDX-License-Identifier: Apache-2.0
"""설정 API (admin 전용).

- GET /settings : 그룹별 유효 설정(읽기용, 민감값 마스킹)
- PUT /settings : 편집 가능 키 저장 + 런타임 즉시 적용
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AdminUser
from app.core.database import get_session
from app.settings import service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
async def get_settings(_admin: AdminUser, session: AsyncSession = Depends(get_session)):
    """그룹별 유효 설정을 반환한다(임베딩/인제스천/스토리지/인증/CORS)."""
    return await service.get_effective(session)


@router.put("")
async def update_settings(
    payload: dict, _admin: AdminUser, session: AsyncSession = Depends(get_session)
):
    """편집 가능 설정을 저장하고 런타임에 즉시 적용한다.

    편집 가능 키: embedding.provider/server_url/model/batch_size,
    ingestion.chunk_size/chunk_overlap, cors.origins, retrieval.*(검색·벡터스토어).
    """
    return await service.update_settings(session, payload)


@router.post("/vector-store/reindex")
async def reindex_vector_store(
    _admin: AdminUser, session: AsyncSession = Depends(get_session)
):
    """현재 벡터 스토어로 전체 컬렉션을 재색인(백필)한다.

    벡터DB 를 외부(qdrant/weaviate/milvus)로 전환한 뒤 한 번 실행하면, PostgreSQL 정본의
    임베딩을 대상 스토어로 적재해 기존 문서가 검색되게 한다. pgvector 면 사실상 no-op.
    """
    from app.vectorstore.backfill import reindex_all

    return await reindex_all(session)


@router.post("/object-storage/test")
async def test_object_storage(payload: dict, _admin: AdminUser):
    """오브젝트 스토리지 연결을 테스트한다(저장 전 검증). 빈 secret 은 현재 값 사용."""
    return await service.test_object_storage(payload or {})


@router.post("/object-storage/initialize")
async def initialize_object_storage(payload: dict, _admin: AdminUser):
    """버킷이 없으면 생성한다."""
    return await service.initialize_object_storage(payload or {})


@router.post("/auth/test")
async def test_auth(payload: dict, _admin: AdminUser):
    """인증 연결을 테스트한다(저장 전 검증). keycloak 은 OIDC discovery 조회."""
    return await service.test_auth(payload or {})


@router.post("/databricks/test")
async def test_databricks(payload: dict, _admin: AdminUser):
    """기반 환경 Databricks 연결(Host + PAT 토큰)을 테스트한다(저장 전 검증)."""
    return await service.test_databricks(payload or {})


@router.post("/image-classification/test")
async def test_image_classification(payload: dict, _admin: AdminUser):
    """이미지 분류 비전 엔드포인트를 작은 합성 이미지로 검증한다(저장 전, 현재 입력값 기준)."""
    return await service.test_image_classification(payload or {})
