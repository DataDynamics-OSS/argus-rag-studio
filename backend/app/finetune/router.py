# SPDX-License-Identifier: Apache-2.0
"""파인튜닝 API — 학습 데이터셋/예시 CRUD + JSONL 내보내기.

권한: 조회는 로그인 사용자, 생성/삭제는 슈퍼유저 이상(평가 모듈과 동일 정책).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, OptionalUser, SuperUser, _extract_bearer_token
from app.core.database import get_session
from app.finetune import service
from app.finetune.schemas import (
    BuilderResultResponse,
    BuildFromEvalRequest,
    DatasetCreateRequest,
    DatasetResponse,
    ExampleCreateRequest,
    ExampleResponse,
    GlossaryTermCreateRequest,
    GlossaryTermResponse,
    GlossaryTermUpdateRequest,
    JobCreateRequest,
    JobResponse,
    JobUpdateRequest,
    ManifestResponse,
    MineNegativesRequest,
    ModelCreateRequest,
    ModelResponse,
    ModelUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/finetune", tags=["finetune"])


# ---------------------------------------------------------------------------
# 데이터셋
# ---------------------------------------------------------------------------

@router.post("/datasets", response_model=DatasetResponse, status_code=201)
async def create_dataset(
    req: DatasetCreateRequest, user: SuperUser, session: AsyncSession = Depends(get_session)
):
    try:
        return await service.create_dataset(session, req, created_by=user.username)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/datasets", response_model=list[DatasetResponse])
async def list_datasets(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    return await service.list_datasets(session)


@router.get("/datasets/{dataset_uuid}", response_model=DatasetResponse)
async def get_dataset(
    dataset_uuid: str, _user: CurrentUser, session: AsyncSession = Depends(get_session)
):
    found = await service.get_dataset_by_uuid(session, dataset_uuid)
    ds = await service.get_dataset_resp(session, found.id) if found else None
    if not ds:
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다.")
    return ds


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(
    dataset_id: int, _user: SuperUser, session: AsyncSession = Depends(get_session)
):
    if not await service.delete_dataset(session, dataset_id):
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다.")


# ---------------------------------------------------------------------------
# 예시(Example)
# ---------------------------------------------------------------------------

@router.post("/datasets/{dataset_id}/examples", response_model=ExampleResponse, status_code=201)
async def add_example(
    dataset_id: int, req: ExampleCreateRequest, _user: SuperUser,
    session: AsyncSession = Depends(get_session),
):
    if not await service.get_dataset(session, dataset_id):
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다.")
    return await service.add_example(session, dataset_id, req)


@router.get("/datasets/{dataset_id}/examples", response_model=list[ExampleResponse])
async def list_examples(
    dataset_id: int, _user: CurrentUser,
    split: str | None = Query(None, pattern="^(train|valid|test)$"),
    session: AsyncSession = Depends(get_session),
):
    return await service.list_examples(session, dataset_id, split=split)


@router.delete("/examples/{example_uuid}", status_code=204)
async def delete_example(
    example_uuid: str, _user: SuperUser, session: AsyncSession = Depends(get_session)
):
    if not await service.delete_example(session, example_uuid):
        raise HTTPException(status_code=404, detail="예시를 찾을 수 없습니다.")


# ---------------------------------------------------------------------------
# 내보내기
# ---------------------------------------------------------------------------

@router.get("/datasets/{dataset_id}/manifest", response_model=ManifestResponse)
async def get_manifest(
    dataset_id: int, _user: CurrentUser, session: AsyncSession = Depends(get_session)
):
    ds = await service.get_dataset(session, dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다.")
    return await service.build_manifest(session, ds)


@router.get("/datasets/{dataset_id}/export/{split}", response_class=PlainTextResponse)
async def export_split(
    dataset_id: int, split: str, request: Request, user: OptionalUser,
    session: AsyncSession = Depends(get_session),
):
    """train|valid 를 JSONL 로 내보낸다(test 는 홀드아웃이라 제외).

    인증: 로그인 사용자, 또는 이 데이터셋을 쓰는 잡의 콜백 토큰(외부 트레이너).
    """
    if user is None:
        token = _extract_bearer_token(request)
        if not await service.authorize_by_job_token(session, token, dataset_id=dataset_id):
            raise HTTPException(status_code=401, detail="인증이 필요합니다.")
    if not await service.get_dataset(session, dataset_id):
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다.")
    try:
        body = await service.export_jsonl(session, dataset_id, split)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return PlainTextResponse(
        body, media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{split}.jsonl"'},
    )


# ---------------------------------------------------------------------------
# 학습 작업(Job)
# ---------------------------------------------------------------------------

@router.post("/jobs", response_model=JobResponse, status_code=201)
async def create_job(
    req: JobCreateRequest, user: SuperUser, session: AsyncSession = Depends(get_session)
):
    try:
        return await service.create_job(session, req, created_by=user.username)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/jobs", response_model=list[JobResponse])
async def list_jobs(
    _user: CurrentUser,
    dataset_id: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    return await service.list_jobs(session, dataset_id=dataset_id)


@router.get("/jobs/{job_uuid}", response_model=JobResponse)
async def get_job(job_uuid: str, user: CurrentUser, session: AsyncSession = Depends(get_session)):
    # 콜백 토큰은 superuser 에게만 노출(외부 트레이너에 전달할 시크릿).
    found = await service.get_job_by_uuid(session, job_uuid)
    job = (
        await service.get_job_resp(
            session, found.id, include_token=(user.is_admin or user.is_superuser)
        )
        if found
        else None
    )
    if not job:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
    return job


@router.patch("/jobs/{job_id}", response_model=JobResponse)
async def update_job(
    job_id: int, req: JobUpdateRequest, request: Request, user: OptionalUser,
    session: AsyncSession = Depends(get_session),
):
    """외부 트레이너/운영자가 잡 상태(진행·지표·아티팩트·오류)를 콜백으로 갱신한다.

    인증: superuser, 또는 이 잡의 콜백 토큰(외부 트레이너 M2M).
    """
    if not (user and (user.is_admin or user.is_superuser)):
        token = _extract_bearer_token(request)
        if not await service.authorize_by_job_token(session, token, job_id=job_id):
            raise HTTPException(status_code=401, detail="인증이 필요합니다.")
    job = await service.update_job(session, job_id, req)
    if not job:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
    return job


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(job_id: int, _user: SuperUser, session: AsyncSession = Depends(get_session)):
    job = await service.cancel_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
    return job


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(job_id: int, _user: SuperUser, session: AsyncSession = Depends(get_session)):
    if not await service.delete_job(session, job_id):
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")


# ---------------------------------------------------------------------------
# 모델 레지스트리(Model)
# ---------------------------------------------------------------------------

@router.post("/models", response_model=ModelResponse, status_code=201)
async def register_model(
    req: ModelCreateRequest, user: SuperUser, session: AsyncSession = Depends(get_session)
):
    try:
        return await service.register_model(session, req, created_by=user.username)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/jobs/{job_id}/register", response_model=ModelResponse, status_code=201)
async def register_from_job(
    job_id: int, user: SuperUser,
    name: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    """성공한 학습 작업의 아티팩트를 등록 모델로 승격한다."""
    try:
        return await service.register_from_job(session, job_id, name, created_by=user.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/models", response_model=list[ModelResponse])
async def list_models(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    return await service.list_models(session)


@router.get("/models/{model_uuid}", response_model=ModelResponse)
async def get_model(model_uuid: str, _user: CurrentUser, session: AsyncSession = Depends(get_session)):
    found = await service.get_model_by_uuid(session, model_uuid)
    m = await service.get_model_resp(session, found.id) if found else None
    if not m:
        raise HTTPException(status_code=404, detail="모델을 찾을 수 없습니다.")
    return m


@router.patch("/models/{model_id}", response_model=ModelResponse)
async def update_model(
    model_id: int, req: ModelUpdateRequest, _user: SuperUser,
    session: AsyncSession = Depends(get_session),
):
    m = await service.update_model(session, model_id, req)
    if not m:
        raise HTTPException(status_code=404, detail="모델을 찾을 수 없습니다.")
    return m


@router.delete("/models/{model_id}", status_code=204)
async def delete_model(model_id: int, _user: SuperUser, session: AsyncSession = Depends(get_session)):
    if not await service.delete_model(session, model_id):
        raise HTTPException(status_code=404, detail="모델을 찾을 수 없습니다.")


# ---------------------------------------------------------------------------
# 용어 사전(Glossary)
# ---------------------------------------------------------------------------

@router.get("/glossary", response_model=list[GlossaryTermResponse])
async def list_terms(
    _user: CurrentUser, domain: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    return await service.list_terms(session, domain=domain)


@router.post("/glossary", response_model=GlossaryTermResponse, status_code=201)
async def create_term(
    req: GlossaryTermCreateRequest, user: SuperUser, session: AsyncSession = Depends(get_session)
):
    return await service.create_term(session, req, created_by=user.username)


@router.patch("/glossary/{term_id}", response_model=GlossaryTermResponse)
async def update_term(
    term_id: int, req: GlossaryTermUpdateRequest, _user: SuperUser,
    session: AsyncSession = Depends(get_session),
):
    t = await service.update_term(session, term_id, req)
    if not t:
        raise HTTPException(status_code=404, detail="용어를 찾을 수 없습니다.")
    return t


@router.delete("/glossary/{term_id}", status_code=204)
async def delete_term(term_id: int, _user: SuperUser, session: AsyncSession = Depends(get_session)):
    if not await service.delete_term(session, term_id):
        raise HTTPException(status_code=404, detail="용어를 찾을 수 없습니다.")


# ---------------------------------------------------------------------------
# 빌더 / 마이닝
# ---------------------------------------------------------------------------

@router.post("/datasets/{dataset_id}/build-from-eval", response_model=BuilderResultResponse)
async def build_from_eval(
    dataset_id: int, req: BuildFromEvalRequest, _user: SuperUser,
    session: AsyncSession = Depends(get_session),
):
    """평가 골든셋에서 검색으로 (질의·정답·오답) 트리플을 생성한다."""
    try:
        return await service.build_from_eval(session, dataset_id, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/datasets/{dataset_id}/mine-negatives", response_model=BuilderResultResponse)
async def mine_negatives(
    dataset_id: int, req: MineNegativesRequest, _user: SuperUser,
    session: AsyncSession = Depends(get_session),
):
    """기준 컬렉션에서 검색으로 하드네거티브를 보강한다."""
    try:
        return await service.mine_negatives(session, dataset_id, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
