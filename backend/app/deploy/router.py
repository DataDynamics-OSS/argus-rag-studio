# SPDX-License-Identifier: Apache-2.0
"""통합 배포 API — 방식(docker/systemd/k8s) 무관. 설계 design/deploy-strategy.md §8.

기존 servermgr 의 /servers/{h}/containers|services 는 하위호환으로 유지하고, 신규 작업은 이 API 로.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.deploy import cluster_service
from app.deploy import service as deploy_service
from app.deploy.models import DeployError
from app.deploy.schemas import (
    ClusterIn,
    ClusterOut,
    DeployRequest,
    DeployResponse,
    DeployTargetIn,
    ExternalServiceOut,
    ServiceEndpointOut,
    ManagedServiceOut,
    OverviewOut,
    OverviewTargetOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deploy", tags=["deploy"])


def _http(e: DeployError) -> HTTPException:
    return HTTPException(status_code=e.code, detail=str(e))


def _target(
    type: str = Query("agent_host"),
    hostname: str | None = Query(None),
    method: str | None = Query(None),
    cluster_id: str | None = Query(None),
    namespace: str | None = Query(None),
) -> DeployTargetIn:
    """라이프사이클/조회용 — target 을 쿼리파라미터로 받는다."""
    return DeployTargetIn(
        type=type, hostname=hostname, method=method, cluster_id=cluster_id, namespace=namespace
    )


@router.post("", response_model=DeployResponse)
async def deploy(body: DeployRequest, session: AsyncSession = Depends(get_session)):
    """spec 을 target 에 배포(+wire_settings 시 설정 자동주입)."""
    try:
        svc, applied = await deploy_service.deploy(session, body.spec.to_model(), body.target.to_model())
    except DeployError as e:
        raise _http(e) from e
    return DeployResponse(service=ManagedServiceOut.of(svc), applied_settings=applied)


@router.post("/stream")
async def deploy_stream(body: DeployRequest, session: AsyncSession = Depends(get_session)):
    """배포를 단계별 진행 이벤트(NDJSON)로 스트리밍 — docker pull 레이어 진행 포함."""
    import json

    from fastapi.responses import StreamingResponse

    spec, target = body.spec.to_model(), body.target.to_model()

    async def gen():
        try:
            async for ev in deploy_service.deploy_stream(session, spec, target):
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except DeployError as e:
            yield json.dumps({"phase": "error", "status": "error", "detail": str(e), "code": e.code}) + "\n"
        except Exception as e:  # noqa: BLE001 — 스트림은 에러 이벤트로 전달
            yield json.dumps({"phase": "error", "status": "error", "detail": str(e)}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@router.get("", response_model=list[ManagedServiceOut])
async def list_services(
    target: DeployTargetIn = Depends(_target),
    session: AsyncSession = Depends(get_session),
):
    """대상의 관리 서비스 목록 (worker 는 레지스트리 alive/잡/처리량 교차참조)."""
    try:
        items = await deploy_service.list_services(target.to_model())
        items = await deploy_service.enrich_workers(session, items)
    except DeployError as e:
        raise _http(e) from e
    return [ManagedServiceOut.of(s) for s in items]


@router.get("/overview", response_model=OverviewOut)
async def overview(session: AsyncSession = Depends(get_session)):
    """전체 배포 서비스 집계 — 에이전트 > 서비스 관리 탭(설계 agent-services-overview.md).

    등록 서버×{docker,systemd} + 등록 클러스터를 병렬 조회, 부분 실패는 대상별 error 로
    병합해 항상 200 을 반환한다. 관리 외(수동 배포) 서비스는 heartbeat 레지스트리·설정
    URL 폴링으로 수집해 external 로 병합(관리형과 host:port 중복 제거).
    (/{name} 보다 먼저 선언해 경로 가로채기 방지)"""
    from datetime import UTC, datetime

    result = await deploy_service.overview(session)
    return OverviewOut(
        targets=[
            OverviewTargetOut(
                target=DeployTargetIn(
                    type=e["target"].type, hostname=e["target"].hostname,
                    method=e["target"].method, cluster_id=e["target"].cluster_id,
                    namespace=e["target"].namespace,
                ),
                services=[ManagedServiceOut.of(s) for s in e["services"]],
                error=e["error"],
            )
            for e in result["targets"]
        ],
        external=[ExternalServiceOut(**x) for x in result["external"]],
        generated_at=datetime.now(UTC).isoformat(),
    )


# --- 클러스터 등록 (/{name} 보다 먼저 선언해 경로 가로채기 방지) ---


@router.get("/service-endpoints", response_model=list[ServiceEndpointOut])
async def service_endpoints(
    kind: str | None = Query(default=None, description="embedding|reranker|vlm|detection|hwp_render"),
    refresh: bool = Query(default=False, description="TTL 캐시 무시하고 재수집"),
    session: AsyncSession = Depends(get_session),
):
    """설정 픽커용 — 실행 중 서비스 엔드포인트 목록(관리형+수동, 중복 제거).

    overview 재사용이라 에이전트 팬아웃(수 초) 비용 — 픽커를 여는 시점에만 호출.
    (/{name} 보다 먼저 선언해 경로 가로채기 방지)"""
    rows = await deploy_service.service_endpoints(session, kind, refresh=refresh)
    return [ServiceEndpointOut(**r) for r in rows]


@router.get("/clusters", response_model=list[ClusterOut])
async def list_clusters(session: AsyncSession = Depends(get_session)):
    return [ClusterOut.of(c) for c in await cluster_service.list_clusters(session)]


@router.post("/clusters", response_model=ClusterOut)
async def upsert_cluster(body: ClusterIn, session: AsyncSession = Depends(get_session)):
    c = await cluster_service.upsert_cluster(session, body.model_dump())
    return ClusterOut.of(c)


@router.delete("/clusters/{cluster_id}")
async def delete_cluster(cluster_id: str, session: AsyncSession = Depends(get_session)):
    removed = await cluster_service.delete_cluster(session, cluster_id)
    return {"removed": removed}


@router.get("/vlm-models")
async def vlm_models():
    """VLM 모델 목록(모델 레지스트리의 kind=vlm, 활성만).

    배포(vlm kind 모델 선택)와 이미지 내용 주입 단계의 모델 콤보가 공유한다."""
    from app.modelreg.seeds import DEFAULT_VLM_NAME
    from app.modelreg.service import list_models

    return {"models": await list_models("vlm"), "default": DEFAULT_VLM_NAME}


@router.get("/model-catalog")
async def model_catalog(session: AsyncSession = Depends(get_session)):
    """모델 레지스트리(전 kind) + 모델 저장소 보유 여부 — /api/v1/models 와 동일 응답.

    (구 엔드포인트 호환 — 모델 관리 화면·배포 콤보는 /api/v1/models 를 사용.)"""
    from app.modelreg.service import catalog_with_holdings

    return await catalog_with_holdings(session)


@router.get("/{name}", response_model=ManagedServiceOut)
async def status(
    name: str,
    target: DeployTargetIn = Depends(_target),
    session: AsyncSession = Depends(get_session),
):
    try:
        svc = await deploy_service.status(target.to_model(), name)
        (svc,) = await deploy_service.enrich_workers(session, [svc])
    except DeployError as e:
        raise _http(e) from e
    return ManagedServiceOut.of(svc)


@router.post("/{name}/{action}", response_model=ManagedServiceOut)
async def action(name: str, action: str, target: DeployTargetIn = Depends(_target)):
    """action: start | stop | restart."""
    try:
        return ManagedServiceOut.of(await deploy_service.action(target.to_model(), name, action))
    except DeployError as e:
        raise _http(e) from e


@router.post("/{name}/scale/{replicas}", response_model=ManagedServiceOut)
async def scale(name: str, replicas: int, target: DeployTargetIn = Depends(_target)):
    try:
        return ManagedServiceOut.of(await deploy_service.scale(target.to_model(), name, replicas))
    except DeployError as e:
        raise _http(e) from e


@router.delete("/{name}")
async def remove(name: str, target: DeployTargetIn = Depends(_target)):
    try:
        await deploy_service.remove(target.to_model(), name)
    except DeployError as e:
        raise _http(e) from e
    return {"removed": name}


@router.get("/{name}/logs")
async def logs(name: str, tail: int = Query(200, ge=1, le=10000), target: DeployTargetIn = Depends(_target)):
    try:
        return {"logs": await deploy_service.logs(target.to_model(), name, tail=tail)}
    except DeployError as e:
        raise _http(e) from e
