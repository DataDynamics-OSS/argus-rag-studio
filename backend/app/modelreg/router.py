# SPDX-License-Identifier: Apache-2.0
"""모델 레지스트리 API — 모델 관리 화면(등록/수정/삭제)과 배포 모델 콤보가 사용.

엔드포인트:
    - GET    /models                  전체 목록 + Model Repository 보유 병합(+unlisted)
    - POST   /models                  등록  (관리자)
    - PUT    /models/{model_id}       수정  (관리자)
    - DELETE /models/{model_id}       삭제  (관리자, builtin 은 비활성화 권장 — 삭제 거부)
    - GET    /models/online           HF 도달성(서버 팩 버튼 노출 조건)
    - GET    /models/pack-jobs        서버 팩 잡 목록(진행/완료/실패)
    - POST   /models/{model_id}/pack  서버에서 팩 시작  (관리자, 온라인 개발망 전용)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, SuperUser
from app.core.database import get_session
from app.modelreg import service
from app.modelreg.models import RagModelRegistry
from app.modelreg.schemas import ModelCreateRequest, ModelResponse, ModelUpdateRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["models"])


async def _get_or_404(session: AsyncSession, model_id: str) -> RagModelRegistry:
    e = await service.get_entry(session, model_id)
    if not e:
        raise HTTPException(status_code=404, detail="모델을 찾을 수 없습니다.")
    return e


@router.get("/models")
async def list_models(
    _user: CurrentUser,
    kind: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    """레지스트리 + Model Repository 보유 현황 — 모델 관리 화면·배포 콤보가 사용."""
    catalog = await service.catalog_with_holdings(session)
    if kind:
        catalog["models"] = [m for m in catalog["models"] if m["kind"] == kind]
    return catalog


@router.post("/models", response_model=ModelResponse, status_code=201)
async def create_model(
    req: ModelCreateRequest, user: SuperUser, session: AsyncSession = Depends(get_session)
):
    try:
        e = await service.create_entry(session, req.model_dump(), user.username)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail=f"같은 종류에 '{req.name}' 이름의 모델이 이미 있습니다."
        ) from None
    logger.info("모델 등록: %s/%s (%s) by %s", e.kind, e.name, e.repo, user.username)
    return ModelResponse(**service.entry_dict(e))


@router.put("/models/{model_id}", response_model=ModelResponse)
async def update_model(
    model_id: str,
    req: ModelUpdateRequest,
    user: SuperUser,
    session: AsyncSession = Depends(get_session),
):
    e = await _get_or_404(session, model_id)
    data = req.model_dump(exclude_unset=True)
    # name/repo 변경은 Repo 키·hf-cache 디렉터리명과 결합 — 보유 여부가 끊길 수 있음(화면 경고).
    try:
        e = await service.update_entry(session, e, data)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="같은 종류에 동일 이름의 모델이 이미 있습니다."
        ) from None
    return ModelResponse(**service.entry_dict(e))


@router.delete("/models/{model_id}")
async def delete_model(
    model_id: str, user: SuperUser, session: AsyncSession = Depends(get_session)
):
    e = await _get_or_404(session, model_id)
    if e.builtin:
        raise HTTPException(
            status_code=400,
            detail="기본 제공 모델은 삭제할 수 없습니다 — 대신 비활성화하세요.",
        )
    await service.delete_entry(session, e)
    logger.info("모델 삭제: %s/%s by %s", e.kind, e.name, user.username)
    return {"removed": True}


# ── 서버에서 팩(온라인 개발망 편의 — design/model-registry.md §3.4) ─────────────

@router.get("/models/online")
async def models_online(_user: CurrentUser):
    """HF 도달성 — 화면이 '서버에서 팩' 버튼 노출 여부를 정한다(에어갭=false)."""
    from app.modelreg.pack import check_online

    return {"online": await check_online()}


@router.get("/models/pack-jobs")
async def pack_jobs(_user: CurrentUser):
    """서버 팩 잡 목록(모델당 최근 1개) — 화면이 진행 상태를 폴링한다."""
    from app.modelreg.pack import list_jobs

    return {"jobs": list_jobs()}


@router.post("/models/{model_id}/pack", status_code=202)
async def pack_model(
    model_id: str, user: SuperUser, session: AsyncSession = Depends(get_session)
):
    """서버에서 팩 시작 — HF 다운로드 → 아카이브 → 모델 저장소 업로드(백그라운드).

    온라인 개발망 전용(에어갭은 외부망 pack_model 로 반입). 동시 1개 제한."""
    from app.modelreg.pack import check_online, start_pack

    e = await _get_or_404(session, model_id)
    if e.source != "hf":
        raise HTTPException(status_code=400, detail="HF 모델만 서버에서 팩할 수 있습니다(수동 반입 대상).")
    if not await check_online():
        raise HTTPException(
            status_code=409,
            detail="이 서버는 HF(huggingface.co)에 접근할 수 없습니다 — 외부망에서 pack_model 로 팩해 반입하세요.",
        )
    try:
        job = await start_pack(service.entry_dict(e))
    except RuntimeError as err:
        raise HTTPException(status_code=409, detail=str(err)) from None
    logger.info("서버 팩 시작: %s/%s by %s", e.kind, e.name, user.username)
    return {"job": job.as_dict()}
