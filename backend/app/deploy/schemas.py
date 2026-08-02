# SPDX-License-Identifier: Apache-2.0
"""통합 배포 API 스키마 — DeploySpec/DeployTarget 의 pydantic 입출력 + 도메인 변환."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.deploy.models import (
    DeploySpec,
    DeployTarget,
    ManagedInstance,
    ManagedService,
    ServiceKind,
)


class DeployTargetIn(BaseModel):
    """어디에 배포/조회하나."""

    type: str = Field("agent_host", description="agent_host | k8s")
    hostname: str | None = None
    method: str | None = Field(None, description="docker | systemd (agent_host)")
    cluster_id: str | None = None
    namespace: str | None = None

    def to_model(self) -> DeployTarget:
        return DeployTarget(
            type=self.type,
            hostname=self.hostname,
            method=self.method,
            cluster_id=self.cluster_id,
            namespace=self.namespace,
        )


class DeploySpecIn(BaseModel):
    """무엇을 배포하나."""

    kind: ServiceKind
    replicas: int = Field(1, ge=1, le=32)
    variant: str = "auto"
    image: str | None = None
    version: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    gpu: bool = False
    wire_settings: bool = True
    network: str | None = None
    extra_hosts: list[str] = Field(default_factory=list)
    db_url: str | None = None
    os_endpoint: str | None = None
    host_port: int | None = Field(
        None, ge=1, le=65535,
        description="호스트 포트 오버라이드(docker 전용) — 기본 포트 점유 시",
    )

    def to_model(self) -> DeploySpec:
        return DeploySpec(
            kind=self.kind,
            replicas=self.replicas,
            variant=self.variant,
            image=self.image,
            version=self.version,
            env=dict(self.env),
            gpu=self.gpu,
            wire_settings=self.wire_settings,
            network=self.network,
            extra_hosts=list(self.extra_hosts),
            db_url=self.db_url,
            os_endpoint=self.os_endpoint,
            host_port=self.host_port,
        )


class DeployRequest(BaseModel):
    spec: DeploySpecIn
    target: DeployTargetIn


class ManagedInstanceOut(BaseModel):
    id: str
    state: str
    node: str | None = None
    pid: int | None = None

    @classmethod
    def of(cls, m: ManagedInstance) -> "ManagedInstanceOut":
        return cls(id=m.id, state=m.state, node=m.node, pid=m.pid)


class ManagedServiceOut(BaseModel):
    name: str
    kind: str
    runtime: str
    desired_replicas: int
    ready_replicas: int
    state: str
    image: str | None = None
    version: str | None = None
    endpoint: str | None = None
    started_at: str | None = None
    exit_code: int | None = None
    message: str | None = None
    restart_count: int | None = None
    health: str | None = None
    cpu_percent: float | None = None
    mem_percent: float | None = None
    worker_alive: bool | None = None
    worker_status: str | None = None
    worker_current_job: str | None = None
    worker_processed_total: int | None = None
    worker_mode: str | None = None
    command: list[str] = Field(default_factory=list)
    stats: dict | None = None  # heartbeat /stats 요약(model·device·gpu·uptime 등)
    instances: list[ManagedInstanceOut] = Field(default_factory=list)

    @classmethod
    def of(cls, m: ManagedService) -> "ManagedServiceOut":
        return cls(
            name=m.name,
            kind=m.kind,
            runtime=m.runtime,
            desired_replicas=m.desired_replicas,
            ready_replicas=m.ready_replicas,
            state=m.state,
            image=m.image,
            version=m.version,
            endpoint=m.endpoint,
            started_at=m.started_at,
            exit_code=m.exit_code,
            message=m.message,
            restart_count=m.restart_count,
            health=m.health,
            cpu_percent=m.cpu_percent,
            mem_percent=m.mem_percent,
            worker_alive=m.worker_alive,
            worker_status=m.worker_status,
            worker_current_job=m.worker_current_job,
            worker_processed_total=m.worker_processed_total,
            worker_mode=m.worker_mode,
            command=list(m.command),
            stats=m.stats,
            instances=[ManagedInstanceOut.of(i) for i in m.instances],
        )


class DeployResponse(BaseModel):
    service: ManagedServiceOut
    applied_settings: dict[str, str] = Field(default_factory=dict)


class OverviewTargetOut(BaseModel):
    """집계 대상 1개(서버×방식 또는 클러스터)의 조회 결과 — 실패 시 error 에 사유."""

    target: DeployTargetIn
    services: list[ManagedServiceOut] = Field(default_factory=list)
    error: str | None = None


class ServiceEndpointOut(BaseModel):
    """설정 픽커용 서비스 엔드포인트 — 실행 중(관리형+수동) 서비스만."""

    kind: str
    name: str
    url: str
    model: str | None = None
    runtime: str          # docker | systemd | k8s | manual
    location: str = ""    # 호스트/클러스터


class ExternalServiceOut(BaseModel):
    """관리 외(수동 배포) 서비스 — heartbeat 자기 등록 또는 전역 설정 URL 폴링으로 관측."""

    kind: str
    url: str
    ok: bool
    error: str | None = None
    source: str  # heartbeat | settings | worker(레지스트리)
    version: str | None = None
    model: str | None = None
    device: str | None = None
    uptime_seconds: float | None = None
    cpu_percent: float | None = None
    mem_percent: float | None = None
    detail: str | None = None  # 부가 표시(워커: mode·상태·처리량 등)


class OverviewOut(BaseModel):
    """전체 배포 서비스 집계 — 에이전트 > 서비스 관리 탭."""

    targets: list[OverviewTargetOut]
    external: list[ExternalServiceOut] = Field(default_factory=list)
    generated_at: str


# ---------------------------------------------------------------------------
# 클러스터 등록 (k8s 배포 대상)
# ---------------------------------------------------------------------------


class ClusterIn(BaseModel):
    cluster_id: str
    name: str
    api_server: str
    token: str | None = None
    ca_cert: str | None = None
    verify_ssl: bool = True
    default_namespace: str = "default"
    default_arch: str = "amd64"


class ClusterOut(BaseModel):
    """토큰/CA 는 비노출(보유 여부만)."""

    cluster_id: str
    name: str
    api_server: str
    verify_ssl: bool
    default_namespace: str
    default_arch: str
    has_token: bool

    @classmethod
    def of(cls, c) -> "ClusterOut":
        return cls(
            cluster_id=c.cluster_id,
            name=c.name,
            api_server=c.api_server,
            verify_ssl=bool(c.verify_ssl),
            default_namespace=c.default_namespace,
            default_arch=c.default_arch,
            has_token=bool(c.token),
        )
