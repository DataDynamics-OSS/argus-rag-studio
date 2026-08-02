# SPDX-License-Identifier: Apache-2.0
"""문서 라우팅 API.

지식베이스(컬렉션) 미지정 문서를 자동으로 적절한 컬렉션으로 보내는 진입점과, 그 결정을 좌우하는
정책(라우터 조합)·미리보기·인트로스펙션을 제공한다.

엔드포인트:
    - GET  /routing/routers           등록된 라우터 목록(레지스트리 introspection — UI 빌더용)
    - GET  /routing/policy            활성 라우팅 정책(단일 'default')
    - PUT  /routing/policy            정책 수정(새 버전 + active)  (관리자)
    - GET  /routing/policy/versions   정책 버전 이력
    - POST /routing/policy/rollback   active 포인터를 과거 버전으로 이동  (관리자)
    - POST /routing/route-preview     파일이 "어디로 라우팅될지" + 근거(저장 없음)
    - POST /routing/route-preview-by-reference  소스 문서/경로 문자열로 라우팅 시뮬레이션  (관리자)
    - POST /routing/intake            컬렉션 미지정 업로드 → 라우팅 → 등록 → 잡 enqueue  (관리자)
    - POST /routing/intake-by-reference  등록된 소스의 문서를 경로로 가져와(pull) 라우팅·등록  (관리자)
    - POST /routing/intake-scan       소스 폴더 일괄 인테이크(드롭존, dry_run 지원)  (관리자)
    - GET  /routing/decisions         라우팅 결정 로그(review_only=true = 검토 큐)
    - POST /routing/decisions/{id}/resolve  검토 처리 — 확인 또는 재배정(재색인)  (관리자)
    - GET  /routing/feedback/suggestions    수정 내역 기반 규칙 제안(피드백 루프)
    - POST /routing/feedback/apply          제안을 활성 정책에 반영(새 버전)  (관리자)
"""

import hashlib
import logging
import mimetypes
import posixpath

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, SuperUser
from app.core.database import get_session
from app.ingestion.classify import classify_document
from app.routing import service
from app.routing.base import RouteInput
from app.routing.base import list_routers as registry_list_routers
from app.routing.profiles import profiles_status, recompute_profiles
from app.routing.schemas import ProfileRecomputeResult, RoutingProfileStatus
from app.routing.base import validate_policy
from app.routing.scan import (
    build_route_input,
    fetch_from_source,
    register_and_enqueue,
    run_scan,
    to_decision,
)
from app.routing.schemas import (
    DecisionListResponse,
    DecisionResolveRequest,
    DecisionResolveResponse,
    FeedbackApplyRequest,
    FeedbackSuggestionsResponse,
    IntakeResponse,
    PolicyResponse,
    PolicyUpdateRequest,
    PolicyVersionResponse,
    ReferenceIntakeRequest,
    ReferencePreviewRequest,
    RoutePreviewResponse,
    ScanIntakeRequest,
    ScanIntakeResponse,
)
from app.sources import service as sources_service
from app.sources.adapters import SourcePathError, normalize_source_path
from app.sources.models import RagStorageSource

logger = logging.getLogger(__name__)

router = APIRouter(tags=["routing"])

async def _get_enabled_source(session: AsyncSession, source_id: str) -> RagStorageSource:
    source = await sources_service.get_source(session, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="스토리지 소스를 찾을 수 없습니다.")
    if not source.enabled:
        raise HTTPException(status_code=409, detail=f"비활성화된 소스입니다: {source.name}")
    return source



# ---------------------------------------------------------------------------
# 인트로스펙션 / 정책 CRUD
# ---------------------------------------------------------------------------

@router.get("/routing/routers")
async def routing_routers(_user: CurrentUser):
    """라우팅 정책에 끼울 수 있는 라우터 목록 — 레지스트리 introspection.

    정책 구성 UI 가 이 목록으로 단계 추가 드롭다운/설정 폼을 동적 렌더한다. 새 라우터를 등록하면
    코드 변경 없이 여기에 자동 노출된다(인제스천 transforms 와 동형).
    """
    return {"routers": registry_list_routers()}


@router.get("/routing/policy", response_model=PolicyResponse)
async def get_policy(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    """활성 라우팅 정책(단일 'default'). 없으면 기본값으로 생성해 반환."""
    policy = await service.get_default_policy(session)
    return await service.policy_response(session, policy)


@router.put("/routing/policy", response_model=PolicyResponse)
async def update_policy(
    req: PolicyUpdateRequest, user: SuperUser, session: AsyncSession = Depends(get_session)
):
    """정책을 수정한다 — 새 버전을 생성하고 active 로 만든다(append-only). 라우터 id 검증."""
    errors = validate_policy(req.config.model_dump())
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    policy = await service.get_default_policy(session)
    return await service.update_config(session, policy, req.config, req.note, user.username)


@router.get("/routing/policy/versions", response_model=list[PolicyVersionResponse])
async def policy_versions(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    """정책 버전 이력(최신순)."""
    policy = await service.get_default_policy(session)
    return await service.list_versions(session, policy.id)


@router.post("/routing/policy/rollback", response_model=PolicyResponse)
async def rollback_policy(
    user: SuperUser,
    version: int = Query(..., ge=1, description="active 로 만들 과거 버전 번호"),
    session: AsyncSession = Depends(get_session),
):
    """active 포인터를 지정 버전으로 이동(롤백)."""
    policy = await service.get_default_policy(session)
    try:
        return await service.set_active(session, policy, version)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# 미리보기 / 인테이크
# ---------------------------------------------------------------------------

@router.post("/routing/route-preview", response_model=RoutePreviewResponse)
async def route_preview(
    _user: SuperUser,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """업로드 파일이 **어느 컬렉션으로 라우팅될지** + 라우터별 점수 trace 를 반환한다(저장 없음).

    실제 인테이크 전에 정책이 의도대로 동작하는지 검증/디버깅하는 용도.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    filename = file.filename or "untitled"
    route_input = await build_route_input(
        filename, data, hashlib.sha256(data).hexdigest(),
        with_lead=await service.policy_needs_content(session),
    )
    result = await service.decide(session, route_input)
    return RoutePreviewResponse(
        filename=filename, metadata=route_input.metadata, decision=to_decision(result)
    )


@router.post("/routing/intake", response_model=IntakeResponse, status_code=202)
async def intake(
    user: SuperUser,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """컬렉션 미지정 업로드 → 라우팅 결정 → 선택 컬렉션에 등록 → 인제스천 잡 enqueue (202).

    매칭 규칙도 폴백 컬렉션도 없으면 422. 선택 컬렉션에 동일 내용(content_hash)이 이미 있으면 409.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    filename = file.filename or "untitled"
    content_hash = hashlib.sha256(data).hexdigest()

    # 라우팅 결정(저장 전) — 메타추출+분류 후 활성 정책 적용. 이후는 공통 등록 경로.
    route_input = await build_route_input(
        filename, data, content_hash,
        with_lead=await service.policy_needs_content(session),
    )
    result = await service.decide(session, route_input)
    return await register_and_enqueue(session, user.username, route_input, result, data, file.content_type)


@router.post("/routing/intake-by-reference", response_model=IntakeResponse, status_code=202)
async def intake_by_reference(
    req: ReferenceIntakeRequest,
    user: SuperUser,
    session: AsyncSession = Depends(get_session),
):
    """등록된 스토리지 소스의 문서를 경로로 가져와(pull) → 라우팅 → 등록 → 잡 enqueue (202).

    원본은 내부 저장소로 **스냅샷 복사**된다(소스가 이후 변경·삭제돼도 재인덱스 안전) —
    출처는 메타데이터(origin_source/origin_path)에 보존. 소스·경로는 path_rule 라우팅 신호가 된다.
    """
    source = await _get_enabled_source(session, req.source_id)
    norm, data = await fetch_from_source(source, req.path)
    filename = posixpath.basename(norm)

    route_input = await build_route_input(
        filename, data, hashlib.sha256(data).hexdigest(),
        source_type="storage_ref", source_path=norm, storage=source.name,
        with_lead=await service.policy_needs_content(session),
    )
    result = await service.decide(session, route_input)
    content_type = mimetypes.guess_type(filename)[0]
    return await register_and_enqueue(session, user.username, route_input, result, data, content_type)


@router.post("/routing/intake-scan", response_model=ScanIntakeResponse)
async def intake_scan(
    req: ScanIntakeRequest,
    user: SuperUser,
    session: AsyncSession = Depends(get_session),
):
    """소스 폴더(prefix) 하위 파일들을 일괄 인테이크(드롭존) — 파일별 배분 리포트 반환.

    ``dry_run=True`` 면 등록·적재 없이 파일별 라우팅 결과만 시뮬레이션한다(실행 전 미리보기 권장).
    파일 수 상한(limit, 최대 500)을 넘거나 열거가 잘리면 ``truncated=True`` 로 알린다 —
    남은 파일은 같은 요청을 반복 실행하면 처리된다(중복은 duplicate 로 스킵되므로 멱등).
    """
    source = await _get_enabled_source(session, req.source_id)
    # 코어(run_scan) 위임 — 워처(app/sourcewatch)와 동일 경로. 수동 실행도 seen 증분
    # 캐시를 읽고 쓴다(dry_run 은 캐시 미사용 — 시뮬레이션은 항상 전량 평가).
    return await run_scan(
        session, source,
        prefix=req.prefix, recursive=req.recursive, dry_run=req.dry_run,
        limit=req.limit, username=user.username,
    )


@router.post("/routing/route-preview-by-reference", response_model=RoutePreviewResponse)
async def route_preview_by_reference(
    req: ReferencePreviewRequest,
    _user: SuperUser,
    session: AsyncSession = Depends(get_session),
):
    """소스 문서(또는 경로 문자열만)로 라우팅 시뮬레이션 — 저장 없음.

    ``path_only=True`` 면 소스 접근 없이 경로·파일명 신호만으로 정책을 검증한다(정책 빌더의
    "이 경로면 어디로 가는가" 즉시 확인용). 아니면 소스에서 실제 바이트를 읽어 메타추출까지
    포함해 인테이크와 동일한 신호로 시뮬레이션한다.
    """
    if req.path_only:
        storage = (req.storage or "").strip()
        if req.source_id:
            source = await sources_service.get_source(session, req.source_id)
            if source:
                storage = source.name
        try:
            norm = normalize_source_path(req.path)
        except SourcePathError as e:
            raise HTTPException(status_code=400, detail=str(e))
        filename = posixpath.basename(norm)
        meta: dict = {}
        try:
            classified = classify_document(filename, source_meta={})
            if isinstance(classified, dict):
                meta.update(classified)
        except Exception as e:  # noqa: BLE001
            logger.warning("경로 시뮬레이션 분류 건너뜀: %s err=%s", filename, e)
        if storage:
            meta["origin_source"] = storage
        meta["origin_path"] = norm
        route_input = RouteInput(
            filename=filename, metadata=meta, source_type="storage_ref",
            source_path=norm, storage=storage,
        )
    else:
        if not req.source_id:
            raise HTTPException(status_code=400, detail="source_id 가 필요합니다(path_only=false).")
        source = await _get_enabled_source(session, req.source_id)
        norm, data = await fetch_from_source(source, req.path)
        route_input = await build_route_input(
            posixpath.basename(norm), data, hashlib.sha256(data).hexdigest(),
            source_type="storage_ref", source_path=norm, storage=source.name,
            with_lead=await service.policy_needs_content(session),
        )

    result = await service.decide(session, route_input)
    return RoutePreviewResponse(
        filename=route_input.filename, metadata=route_input.metadata,
        decision=to_decision(result),
        source_path=route_input.source_path, storage=route_input.storage or None,
    )


# ---------------------------------------------------------------------------
# 검토 큐(Phase 3) — 결정 로그 조회 + 확인/재배정
# ---------------------------------------------------------------------------

@router.get("/routing/decisions", response_model=DecisionListResponse)
async def routing_decisions(
    _user: CurrentUser,
    review_only: bool = Query(True, description="true = 검토 대기(review)만, false = 전체 이력"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """라우팅 결정 로그(최신순) — 저신뢰/폴백(review=true) 결정을 모으면 검토 큐가 된다."""
    return await service.list_decisions(session, review_only, page, page_size)


@router.post("/routing/decisions/{decision_id}/resolve", response_model=DecisionResolveResponse)
async def routing_decision_resolve(
    decision_id: str,
    req: DecisionResolveRequest,
    user: SuperUser,
    session: AsyncSession = Depends(get_session),
):
    """검토 처리 — ``collection_id`` 지정 시 재배정(문서 이동 + 재색인 잡), 미지정 시 확인만.

    확인/재배정 모두 review 를 해제하고 검토자·시각을 남긴다(수정 내역 = 규칙 튜닝 피드백 원천).
    잘못된 대상은 400, 대상 컬렉션의 동일 내용(content_hash) 중복은 409.
    """
    try:
        result = await service.resolve_decision(
            session, decision_id, req.collection_id, user.username
        )
    except service.ReassignConflictError as e:
        logger.warning("검토 처리 충돌(409): decision=%s — %s", decision_id, e)
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        logger.warning("검토 처리 검증 실패(400): decision=%s — %s", decision_id, e)
        raise HTTPException(status_code=400, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="라우팅 결정을 찾을 수 없습니다.")
    item, reassigned, job_id = result
    return DecisionResolveResponse(decision=item, reassigned=reassigned, job_id=job_id)


# ---------------------------------------------------------------------------
# 수정 피드백 루프 — 재배정 내역에서 규칙 제안 + 1클릭 정책 반영
# ---------------------------------------------------------------------------

@router.get("/routing/feedback/suggestions", response_model=FeedbackSuggestionsResponse)
async def routing_feedback_suggestions(
    _user: CurrentUser,
    min_support: int = Query(2, ge=1, le=100, description="같은 신호의 최소 수정 횟수"),
    min_purity: float = Query(0.75, ge=0.5, le=1.0, description="같은 컬렉션 비율 임계"),
    session: AsyncSession = Depends(get_session),
):
    """검토 큐의 수동 재배정 내역을 신호별로 집계해 정책 규칙을 제안한다.

    활성 정책에 이미 있는 매핑은 제외 — 남는 것이 '반복 수정되는데 규칙이 없는' 구멍이다.
    """
    from app.routing.feedback import build_suggestions

    return FeedbackSuggestionsResponse(**await build_suggestions(session, min_support, min_purity))


@router.post("/routing/feedback/apply", response_model=PolicyResponse)
async def routing_feedback_apply(
    req: FeedbackApplyRequest,
    user: SuperUser,
    session: AsyncSession = Depends(get_session),
):
    """제안 1건을 활성 정책에 병합해 새 버전을 만든다(append-only — 언제든 롤백 가능).

    같은 라우터 단계가 있으면 규칙에 병합, 없으면 내용/LLM 단계 앞에 새 단계로 삽입.
    """
    from app.routing.feedback import FEEDBACK_ROUTERS, apply_suggestion

    if req.router not in FEEDBACK_ROUTERS:
        logger.warning("피드백 반영 거부(미지원 라우터): %s", req.router)
        raise HTTPException(status_code=400, detail=f"제안 반영을 지원하지 않는 라우터입니다: {req.router}")
    try:
        return await apply_suggestion(session, req.model_dump(), user.username)
    except ValueError as e:
        logger.warning("피드백 반영 실패(400): %s '%s' — %s", req.router, req.value, e)
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# 라우팅 디스크립터(Phase 2) — 내용 임베딩 라우터의 컬렉션 centroid 관리
# ---------------------------------------------------------------------------

@router.get("/routing/profiles", response_model=list[RoutingProfileStatus])
async def routing_profiles(_user: CurrentUser, session: AsyncSession = Depends(get_session)):
    """활성 컬렉션별 디스크립터 상태 — 미계산/유효/stale(전역 임베딩 설정 변경)."""
    return [RoutingProfileStatus(**row) for row in await profiles_status(session)]


@router.post("/routing/profiles/recompute", response_model=list[ProfileRecomputeResult])
async def routing_profiles_recompute(
    _user: SuperUser,
    collection_id: int | None = Query(default=None, description="지정 시 해당 컬렉션만"),
    session: AsyncSession = Depends(get_session),
):
    """디스크립터 재계산 — 최근 청크 샘플(없으면 설명)을 전역 임베딩으로 centroid 화.

    컬렉션 수 × 샘플 임베딩(기본 64건) 비용 — 동기 실행(수 초~수십 초).
    새 문서가 충분히 쌓였거나 전역 임베딩 설정을 바꿨을 때 다시 실행한다.
    """
    return [ProfileRecomputeResult(**row) for row in await recompute_profiles(session, collection_id)]
