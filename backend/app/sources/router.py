# SPDX-License-Identifier: Apache-2.0
"""스토리지 소스 레지스트리 API.

참조 인테이크(pull)가 원본을 읽어올 소스(S3·NAS)를 등록/관리한다. 소스 내용 접근(브라우징·
테스트)과 변경은 관리자 전용, 목록/조회는 일반 사용자(정책 빌더의 소스 콤보가 사용).

엔드포인트:
    - GET    /storage-sources                  소스 목록
    - POST   /storage-sources                  소스 등록  (관리자)
    - GET    /storage-sources/{source_id}      소스 조회
    - PUT    /storage-sources/{source_id}      소스 수정  (관리자)
    - DELETE /storage-sources/{source_id}      소스 삭제  (관리자)
    - POST   /storage-sources/{source_id}/test 연결 검증(stat/list 1건)  (관리자)
    - GET    /storage-sources/{source_id}/list 경로 브라우징(인테이크 피커)  (관리자)
"""

import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, SuperUser
from app.core.database import get_session
from app.sources import service
from app.sources.adapters import SourceObjectNotFound, SourcePathError
from app.sources.models import RagStorageSource
from app.sources.schemas import (
    SourceCreateRequest,
    SourceEntryItem,
    SourceListResponse,
    SourceResponse,
    SourceTestResponse,
    SourceUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["storage-sources"])


async def _get_or_404(session: AsyncSession, source_id: str) -> RagStorageSource:
    source = await service.get_source(session, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="스토리지 소스를 찾을 수 없습니다.")
    return source


@router.get("/storage-sources", response_model=list[SourceResponse])
async def list_sources(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    """등록된 스토리지 소스 목록 — 정책 빌더 소스 콤보/인테이크 소스 선택이 사용."""
    return [service.source_response(s) for s in await service.list_sources(session)]


@router.post("/storage-sources", response_model=SourceResponse, status_code=201)
async def create_source(
    req: SourceCreateRequest, user: SuperUser, session: AsyncSession = Depends(get_session)
):
    """소스 등록. name 은 라우팅 규칙이 참조하는 논리명(unique)."""
    errors = service.validate_source(req.kind, req.config)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    try:
        source = await service.create_source(
            session, name=req.name, kind=req.kind, description=req.description,
            config=req.config, secret=req.secret, enabled=req.enabled,
            created_by=user.username,
        )
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"이미 존재하는 소스 이름입니다: {req.name}")
    return service.source_response(source)


@router.get("/storage-sources/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: str, _user: CurrentUser, session: AsyncSession = Depends(get_session)
):
    return service.source_response(await _get_or_404(session, source_id))


@router.put("/storage-sources/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: str, req: SourceUpdateRequest, _user: SuperUser,
    session: AsyncSession = Depends(get_session),
):
    """소스 수정 — 미지정 필드 유지. 활성 정책이 참조 중인 이름은 변경 불가(409)."""
    source = await _get_or_404(session, source_id)

    new_name = req.name.strip() if req.name else None
    if new_name and new_name != source.name:
        if await service.referencing_active_policy(session, source.name):
            raise HTTPException(
                status_code=409,
                detail=f"활성 라우팅 정책이 소스 '{source.name}' 을 참조합니다. 정책을 먼저 수정하세요.",
            )
        source.name = new_name
    if req.description is not None:
        source.description = req.description
    if req.config is not None:
        errors = service.validate_source(source.kind, req.config)
        if errors:
            raise HTTPException(status_code=400, detail="; ".join(errors))
        source.config_json = json.dumps(req.config, ensure_ascii=False)
    if req.clear_secret:
        source.secret_enc = None
    elif req.secret is not None:
        source.secret_enc = service.encrypt_secret(req.secret)
    if req.enabled is not None:
        source.enabled = req.enabled

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"이미 존재하는 소스 이름입니다: {new_name}")
    await session.refresh(source)
    return service.source_response(source)


@router.delete("/storage-sources/{source_id}", status_code=204)
async def delete_source(
    source_id: str, _user: SuperUser, session: AsyncSession = Depends(get_session)
):
    """소스 삭제 — 활성 정책이 참조 중이면 409. 등록 문서는 스냅샷이라 영향 없음."""
    source = await _get_or_404(session, source_id)
    if await service.referencing_active_policy(session, source.name):
        raise HTTPException(
            status_code=409,
            detail=f"활성 라우팅 정책이 소스 '{source.name}' 을 참조합니다. 정책을 먼저 수정하세요.",
        )
    from app.sourcewatch import service as watch_service

    watches = await watch_service.watches_for_source(session, source.id)
    if watches:
        raise HTTPException(
            status_code=409,
            detail=f"소스 '{source.name}' 에 자동 수집 워치 {len(watches)}개가 걸려 있습니다. 워치를 먼저 삭제하세요.",
        )
    await session.delete(source)
    await session.commit()


@router.post("/storage-sources/{source_id}/test", response_model=SourceTestResponse)
async def test_source(
    source_id: str, _user: SuperUser, session: AsyncSession = Depends(get_session)
):
    """연결 검증 — 루트 list 1회로 접근 가능/자격증명을 확인한다(등록 화면 '테스트' 버튼)."""
    source = await _get_or_404(session, source_id)
    started = time.monotonic()
    try:
        adapter = service.adapter_for(source)
        listing = await adapter.list("", recursive=False)
    except Exception as e:  # noqa: BLE001 — 원인 불문 사용자에게 메시지로 전달
        return SourceTestResponse(
            ok=False, message=f"연결 실패: {e}",
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
    return SourceTestResponse(
        ok=True, message=f"연결 성공 — 루트에서 항목 {len(listing.entries)}개 확인",
        entry_count=len(listing.entries),
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )


@router.get("/storage-sources/{source_id}/list", response_model=SourceListResponse)
async def list_source_directory(
    source_id: str,
    _user: SuperUser,
    prefix: str = Query("", description="소스 내 디렉터리 경로(빈 값=루트)"),
    recursive: bool = Query(False, description="하위 전체 파일 평탄 열거"),
    session: AsyncSession = Depends(get_session),
):
    """소스 내 경로 브라우징 — 인테이크 '소스에서 가져오기' 피커가 사용."""
    source = await _get_or_404(session, source_id)
    if not source.enabled:
        raise HTTPException(status_code=409, detail="비활성화된 소스입니다.")
    try:
        listing = await service.adapter_for(source).list(prefix, recursive=recursive)
    except SourcePathError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except SourceObjectNotFound:
        raise HTTPException(status_code=404, detail="경로를 찾을 수 없습니다.")
    return SourceListResponse(
        prefix=prefix,
        entries=[SourceEntryItem(**e.__dict__) for e in listing.entries],
        truncated=listing.truncated,
    )
