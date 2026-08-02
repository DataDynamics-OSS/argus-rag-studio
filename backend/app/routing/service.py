# SPDX-License-Identifier: Apache-2.0
"""라우팅 서비스 — 정책 버전 관리(append-only) + 라우팅 결정 실행 + 결정 로깅.

정책은 단일(singleton) 'default' 자산이다(Phase 1). 인테이크는 항상 활성 버전을 사용한다.
정책 수정은 ``RagPipeline`` 과 동형으로 append-only: 새 버전 생성 후 ``active_version`` 이동(롤백 가능).
"""

import json
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections.models import RagCollection
from app.routing import DEFAULT_POLICY
from app.routing.base import RouteContext, RouteInput, run_policy
from app.routing.models import (
    RagRoutingDecision,
    RagRoutingPolicy,
    RagRoutingPolicyVersion,
)
from app.routing.schemas import (
    DecisionItem,
    DecisionListResponse,
    PolicyResponse,
    PolicyVersionResponse,
    RoutingPolicyConfig,
)

logger = logging.getLogger(__name__)

_DEFAULT_NAME = "default"


# ---------------------------------------------------------------------------
# 정책 버전 관리(singleton 'default')
# ---------------------------------------------------------------------------

async def _version_row(
    session: AsyncSession, policy_id: int, version: int
) -> RagRoutingPolicyVersion | None:
    return (await session.execute(
        select(RagRoutingPolicyVersion).where(
            RagRoutingPolicyVersion.policy_id == policy_id,
            RagRoutingPolicyVersion.version == version,
        )
    )).scalars().first()


async def _config_of(session: AsyncSession, policy_id: int, version: int) -> RoutingPolicyConfig:
    row = await _version_row(session, policy_id, version)
    if not row:
        return RoutingPolicyConfig(**DEFAULT_POLICY)
    return RoutingPolicyConfig.model_validate_json(row.config_json)


async def get_default_policy(session: AsyncSession) -> RagRoutingPolicy:
    """단일 'default' 정책을 반환(없으면 기본값으로 생성). 인테이크/조회 공용 진입점."""
    policy = (await session.execute(
        select(RagRoutingPolicy).where(RagRoutingPolicy.name == _DEFAULT_NAME)
    )).scalars().first()
    if policy:
        return policy
    policy = RagRoutingPolicy(
        policy_id=str(uuid.uuid4()), name=_DEFAULT_NAME,
        description="기본 라우팅 정책", active_version=1, created_by="system",
    )
    session.add(policy)
    await session.flush()
    session.add(RagRoutingPolicyVersion(
        policy_id=policy.id, version=1,
        config_json=RoutingPolicyConfig(**DEFAULT_POLICY).model_dump_json(),
        note="initial", created_by="system",
    ))
    await session.commit()
    await session.refresh(policy)
    logger.info("기본 라우팅 정책 생성: id=%d", policy.id)
    return policy


async def policy_response(session: AsyncSession, policy: RagRoutingPolicy) -> PolicyResponse:
    count = (await session.execute(
        select(func.count()).where(RagRoutingPolicyVersion.policy_id == policy.id)
    )).scalar() or 0
    config = await _config_of(session, policy.id, policy.active_version)
    return PolicyResponse(
        id=policy.id, policy_id=policy.policy_id, name=policy.name,
        description=policy.description, active_version=policy.active_version,
        version_count=count, config=config, created_by=policy.created_by,
        created_at=policy.created_at, updated_at=policy.updated_at,
    )


async def update_config(
    session: AsyncSession, policy: RagRoutingPolicy, config: RoutingPolicyConfig,
    note: str | None, created_by: str | None,
) -> PolicyResponse:
    """새 버전을 생성하고 active 로 만든다(append-only)."""
    next_version = ((await session.execute(
        select(func.max(RagRoutingPolicyVersion.version)).where(
            RagRoutingPolicyVersion.policy_id == policy.id
        )
    )).scalar() or 0) + 1
    session.add(RagRoutingPolicyVersion(
        policy_id=policy.id, version=next_version, config_json=config.model_dump_json(),
        note=note, created_by=created_by,
    ))
    policy.active_version = next_version
    await session.commit()
    await session.refresh(policy)
    logger.info("라우팅 정책 새 버전: v%d (active)", next_version)
    return await policy_response(session, policy)


async def set_active(
    session: AsyncSession, policy: RagRoutingPolicy, version: int
) -> PolicyResponse:
    """active 포인터를 지정 버전으로 이동(롤백). 없으면 ValueError."""
    if not await _version_row(session, policy.id, version):
        raise ValueError(f"버전 {version} 이(가) 없습니다.")
    policy.active_version = version
    await session.commit()
    await session.refresh(policy)
    logger.info("라우팅 정책 active 변경 → v%d", version)
    return await policy_response(session, policy)


async def list_versions(session: AsyncSession, policy_id: int) -> list[PolicyVersionResponse]:
    rows = (await session.execute(
        select(RagRoutingPolicyVersion)
        .where(RagRoutingPolicyVersion.policy_id == policy_id)
        .order_by(RagRoutingPolicyVersion.version.desc())
    )).scalars().all()
    return [
        PolicyVersionResponse(
            version=r.version,
            config=RoutingPolicyConfig.model_validate_json(r.config_json),
            note=r.note, created_by=r.created_by, created_at=r.created_at,
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# 라우팅 결정 실행 + 로깅
# ---------------------------------------------------------------------------

async def _active_collections(session: AsyncSession) -> list[RagCollection]:
    return list((await session.execute(
        select(RagCollection).where(RagCollection.status == "active")
    )).scalars().all())


# 선두 텍스트(lead_text)가 필요한 내용 기반 라우터들 — 추출 비용 게이트의 기준.
# custom_function 도 포함 — 함수가 doc["lead_text"] 를 쓸 수 있게 한다.
CONTENT_ROUTERS = {"content_embedding", "llm_classify", "custom_function"}

# 동기 블로킹 호출(LLM HTTP·샌드박스 subprocess)을 포함하는 라우터 — 정책 실행을 스레드로.
SYNC_HEAVY_ROUTERS = {"llm_classify", "custom_function"}


async def policy_needs_content(session: AsyncSession) -> bool:
    """활성 정책에 내용 기반 단계(content_embedding/llm_classify)가 있는지 —
    선두 텍스트 추출 여부 판단용."""
    policy = await get_default_policy(session)
    config = await _config_of(session, policy.id, policy.active_version)
    return any(
        (s.get("id") if isinstance(s, dict) else s) in CONTENT_ROUTERS
        for s in (config.model_dump().get("stages") or [])
    )


async def decide(session: AsyncSession, route_input: RouteInput) -> dict:
    """활성 정책으로 라우팅을 결정한다. 반환: run_policy 결과 + policy_version + collection_name.

    매칭/폴백 모두 실패하면 ``collection_id`` 가 None 으로 돌아온다(호출부가 처리).
    """
    policy = await get_default_policy(session)
    config = await _config_of(session, policy.id, policy.active_version)
    collections = await _active_collections(session)
    name_by_id = {c.id: c.name for c in collections}
    ctx = RouteContext(collections=[
        {"id": c.id, "name": c.name, "description": c.description} for c in collections
    ])

    # 내용 임베딩 라우터(Phase 2) 준비 — 정책에 해당 단계가 있고 선두 텍스트가 있을 때만
    # 임베딩 1회 + 프로파일 로딩(불필요한 비용 방지). 실패해도 라우팅은 계속된다.
    policy_dict = config.model_dump()
    stage_ids = {s.get("id") if isinstance(s, dict) else s for s in (policy_dict.get("stages") or [])}
    if "content_embedding" in stage_ids and (route_input.lead_text or "").strip():
        from app.routing.profiles import embed_lead_text, load_profiles_for_ctx

        ctx.profiles = await load_profiles_for_ctx(session)
        if ctx.profiles:
            ctx.lead_embedding = await embed_lead_text(route_input.lead_text)

    # llm_classify 는 라우터 내부에서 동기 HTTP(LLM) 호출을 한다 — 이벤트 루프를 막지
    # 않도록 해당 단계가 있을 때만 정책 실행을 스레드로 내린다(캐스케이드 도달 시에만
    # 호출되는 의미는 유지 — first_match 가 앞 단계에서 확정하면 LLM 은 불리지 않는다).
    if stage_ids & SYNC_HEAVY_ROUTERS:
        import asyncio

        result = await asyncio.to_thread(run_policy, policy_dict, route_input, ctx)
    else:
        result = run_policy(policy_dict, route_input, ctx)
    result["policy_version"] = policy.active_version
    cid = result.get("collection_id")
    result["collection_name"] = name_by_id.get(cid) if cid is not None else None
    return result


async def log_decision(
    session: AsyncSession, document_id: int, result: dict, created_by: str | None
) -> None:
    """라우팅 결정 1건을 감사 로그로 남긴다(best-effort 호출부에서 감쌈)."""
    session.add(RagRoutingDecision(
        decision_id=str(uuid.uuid4()),
        document_id=document_id,
        collection_id=result.get("collection_id"),
        confidence=float(result.get("confidence") or 0.0),
        mode=result.get("mode"),
        matched_router=result.get("matched_router"),
        fallback_used=bool(result.get("fallback_used")),
        review=bool(result.get("review")),
        policy_version=result.get("policy_version"),
        trace_json=json.dumps(result.get("trace") or [], ensure_ascii=False),
        created_by=created_by,
    ))
    await session.commit()


# ---------------------------------------------------------------------------
# 검토 큐 — 결정 로그 조회 + 확인/재배정 처리(Phase 3)
# ---------------------------------------------------------------------------

class ReassignConflictError(Exception):
    """재배정 대상 컬렉션에 동일 내용(content_hash) 문서가 이미 있음(라우터가 409 로 변환)."""


def _decision_item(
    d: RagRoutingDecision,
    doc,  # RagDocument | None — 삭제된 문서면 None(행은 CASCADE 로 보통 함께 삭제됨)
    names: dict[int, str],
) -> DecisionItem:
    try:
        trace = json.loads(d.trace_json) if d.trace_json else []
    except (TypeError, ValueError):
        # 손상된 trace 는 목록 표시를 막지 않는다 — 빈 trace 로 강등하고 흔적만 남김.
        logger.warning("결정 trace JSON 파싱 실패(무시): decision=%s", d.decision_id)
        trace = []
    return DecisionItem(
        id=d.id, decision_id=d.decision_id, document_id=d.document_id,
        document_uuid=doc.document_id if doc else None,
        document_name=doc.name if doc else None,
        document_status=doc.status if doc else None,
        collection_id=d.collection_id,
        collection_name=names.get(d.collection_id) if d.collection_id else None,
        confidence=d.confidence, mode=d.mode, matched_router=d.matched_router,
        fallback_used=d.fallback_used, review=d.review, policy_version=d.policy_version,
        trace=trace, created_by=d.created_by, created_at=d.created_at,
        reviewed_at=d.reviewed_at, reviewed_by=d.reviewed_by,
        corrected_collection_id=d.corrected_collection_id,
        corrected_collection_name=(
            names.get(d.corrected_collection_id) if d.corrected_collection_id else None
        ),
    )


async def _collection_names(session: AsyncSession) -> dict[int, str]:
    return dict((await session.execute(
        select(RagCollection.id, RagCollection.name)
    )).all())


async def list_decisions(
    session: AsyncSession, review_only: bool, page: int, page_size: int
) -> DecisionListResponse:
    """결정 로그 목록(최신순) — ``review_only=True`` 가 검토 큐다."""
    from app.documents.models import RagDocument

    where = [RagRoutingDecision.review.is_(True)] if review_only else []
    total = (await session.execute(
        select(func.count()).select_from(RagRoutingDecision).where(*where)
    )).scalar() or 0
    pending = (await session.execute(
        select(func.count()).select_from(RagRoutingDecision)
        .where(RagRoutingDecision.review.is_(True))
    )).scalar() or 0
    # 문서는 outer join — 문서 삭제 시 결정 행은 CASCADE 로 보통 사라지지만, 트랜잭션
    # 타이밍에 따라 잠깐 남을 수 있어 doc=None 도 표시 가능해야 한다.
    rows = (await session.execute(
        select(RagRoutingDecision, RagDocument)
        .join(RagDocument, RagDocument.id == RagRoutingDecision.document_id, isouter=True)
        .where(*where)
        .order_by(RagRoutingDecision.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).all()
    names = await _collection_names(session)
    logger.debug(
        "결정 로그 조회: review_only=%s page=%d/%d건 → %d행(검토 대기 %d)",
        review_only, page, page_size, len(rows), pending,
    )
    return DecisionListResponse(
        total=total, pending_review=pending, page=page, page_size=page_size,
        items=[_decision_item(d, doc, names) for d, doc in rows],
    )


async def resolve_decision(
    session: AsyncSession, decision_id: str, target_collection_id: int | None,
    username: str | None,
) -> tuple[DecisionItem, bool, str | None] | None:
    """검토 처리 — 확인(대상 미지정) 또는 재배정(문서 이동 + 재색인 잡).

    반환: (결정, 재배정 여부, job_id). 결정이 없으면 None.

    Raises:
        ValueError: 대상 컬렉션이 없거나 비활성, 또는 문서가 이미 삭제됨(라우터가 400).
        ReassignConflictError: 대상 컬렉션에 동일 content_hash 문서 존재(라우터가 409).
    """
    from app.documents.models import RagDocument
    from app.ingestion import service as ingestion_service

    decision = (await session.execute(
        select(RagRoutingDecision).where(RagRoutingDecision.decision_id == decision_id)
    )).scalars().first()
    if not decision:
        return None
    document = (await session.execute(
        select(RagDocument).where(RagDocument.id == decision.document_id)
    )).scalars().first()

    reassigned = False
    job_id: str | None = None
    # 현재 컬렉션과 같은 대상은 이동 없이 '확인' 으로 취급한다(불필요한 재색인 방지).
    if (target_collection_id is not None and document is not None
            and target_collection_id == document.collection_id):
        logger.debug(
            "검토 재배정 대상=현재 컬렉션 — 확인으로 처리: decision=%s collection=%d",
            decision_id, target_collection_id,
        )
    elif target_collection_id is not None:
        if document is None:
            logger.warning("검토 재배정 불가(문서 삭제됨): decision=%s", decision_id)
            raise ValueError("문서가 이미 삭제되어 재배정할 수 없습니다.")
        target = (await session.execute(
            select(RagCollection).where(RagCollection.id == target_collection_id)
        )).scalars().first()
        if not target or target.status != "active":
            logger.warning(
                "검토 재배정 불가(대상 컬렉션 없음/비활성): decision=%s target=%d",
                decision_id, target_collection_id,
            )
            raise ValueError(
                f"재배정 대상 컬렉션(id={target_collection_id})을 찾을 수 없거나 비활성입니다."
            )
        if document.content_hash:
            dup = await ingestion_service.find_document_by_hash(
                session, target.id, document.content_hash
            )
            if dup and dup.id != document.id:
                logger.warning(
                    "검토 재배정 충돌(동일 content_hash): decision=%s target=%d dup_doc=%d",
                    decision_id, target.id, dup.id,
                )
                raise ReassignConflictError(
                    f"동일한 내용의 문서가 이미 등록되어 있습니다(컬렉션 {target.id}, id={dup.id})."
                )
        document.collection_id = target.id
        document.status = "registered"
        decision.corrected_collection_id = target.id
        reassigned = True

    decision.review = False
    decision.reviewed_at = func.now()
    decision.reviewed_by = username
    await session.commit()

    if reassigned:
        # 워커가 기존 청크를 document_id 기준으로 지우고 새 컬렉션 설정으로 재색인한다.
        job = await ingestion_service.enqueue_job(
            session, decision.document_id, target_collection_id
        )
        job_id = job.job_id
        logger.info(
            "검토 재배정: decision=%s document=%d → collection=%d (job=%s) by %s",
            decision_id, decision.document_id, target_collection_id, job_id, username,
        )
    else:
        logger.info("검토 확인: decision=%s by %s", decision_id, username)

    await session.refresh(decision)
    document = (await session.execute(
        select(RagDocument).where(RagDocument.id == decision.document_id)
    )).scalars().first()
    names = await _collection_names(session)
    return _decision_item(decision, document, names), reassigned, job_id
