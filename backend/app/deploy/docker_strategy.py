# SPDX-License-Identifier: Apache-2.0
"""DockerStrategy — 에이전트 containermgr 경유. 기존 servermgr 빌더를 재사용."""

from __future__ import annotations

from app.deploy._agent import agent_request, resolve_host
from app.deploy.models import (
    DeployError,
    DeploySpec,
    DeployTarget,
    ManagedInstance,
    ManagedService,
    Privilege,
    ServiceKind,
)
from app.deploy.strategy import DeployStrategy
from app.servermgr import service as sm
from app.servermgr.schemas import DeployContainerRequest

_BASE = "/api/v1/container"
# 서버형은 단일 인스턴스, worker 만 N 복제.
_SCALABLE = {ServiceKind.worker}


def _to_request(spec: DeploySpec) -> DeployContainerRequest:
    """DeploySpec → 기존 DeployContainerRequest (build_container_spec 입력)."""
    return DeployContainerRequest(
        kind=spec.kind.value,
        replicas=spec.replicas,
        image=spec.image,
        variant=spec.variant,
        gpus="all" if spec.gpu else None,
        version=spec.version,
        environment=dict(spec.env),
        network=spec.network,
        extra_hosts=list(spec.extra_hosts),
        db_url=spec.db_url,
        os_endpoint=spec.os_endpoint,
        host_port=spec.host_port,
    )


def _endpoint_from(raw: dict, host_ip: str) -> str | None:
    """컨테이너 포트 매핑(에이전트 inspect ports) + kind 규약으로 접속 endpoint 파생.

    서버형 kind 만 해당(worker 등 포트 없는 kind 는 None). 구버전 에이전트(ports 미지원)는
    빈 목록이라 None — 외부(수동) 중복 제거의 근거가 약해질 뿐 동작은 유지된다."""
    cat = sm.CONTAINER_KINDS.get(str(raw.get("kind") or ""))
    if not cat or not cat.get("port"):
        return None
    container_port = str(cat["port"])
    for m in raw.get("ports") or []:
        host_port, _, cport = str(m).partition(":")
        if cport == container_port and host_port:
            return f"http://{host_ip}:{host_port}{cat['suffix']}"
    return None


def _to_service(raw: dict, *, endpoint: str | None = None) -> ManagedService:
    """에이전트 ContainerStatus(dict) → ManagedService (docker: 인스턴스 1 = 서비스 1)."""
    state = str(raw.get("state") or "unknown")
    running = state.lower() == "running"
    return ManagedService(
        name=str(raw.get("name")),
        kind=str(raw.get("kind") or ""),
        runtime="docker",
        desired_replicas=1,
        ready_replicas=1 if running else 0,
        state="running" if running else "stopped",
        image=raw.get("image"),
        version=raw.get("version"),
        endpoint=endpoint,
        started_at=raw.get("started_at"),
        exit_code=raw.get("exit_code"),
        message=raw.get("message") or None,
        restart_count=raw.get("restart_count"),
        command=[str(a) for a in (raw.get("command") or [])],
        health=raw.get("health"),
        cpu_percent=raw.get("cpu_percent"),
        mem_percent=raw.get("mem_percent"),
        instances=[ManagedInstance(id=str(raw.get("id") or raw.get("name")), state=state)],
    )


class DockerStrategy(DeployStrategy):
    runtime = "docker"

    def required_privilege(self) -> Privilege:
        return Privilege.host_docker

    def supports(self, kind: ServiceKind) -> bool:
        return kind in sm.CONTAINER_KINDS  # 모든 kind 컨테이너 배포 가능

    async def deploy(self, spec: DeploySpec, target: DeployTarget) -> ManagedService:
        if not target.hostname:
            raise DeployError("docker 배포는 hostname 이 필요합니다", code=400)
        host = await resolve_host(target.hostname)

        n = spec.replicas if spec.kind in _SCALABLE else 1
        existing = await agent_request("GET", host.ip, _BASE)
        names = [c.get("name") for c in (existing or []) if c.get("name")]
        prefix = sm.container_prefix(spec.kind.value)
        slots = sm.next_slots(prefix, names, n)

        req = _to_request(spec)
        deployed: list[dict] = []
        for name in slots:
            payload = sm.build_container_spec(
                spec.kind.value, name, req, arch=host.arch, gpu_count=host.gpu_count
            )
            deployed.append(await agent_request("POST", host.ip, _BASE, json=payload))

        inj = sm.setting_injection(spec.kind.value, host.ip, spec.host_port)
        endpoint = inj[1] if inj else None
        svc = _to_service(deployed[0], endpoint=endpoint)
        svc.desired_replicas = svc.ready_replicas = len(deployed)
        return svc

    async def list(self, target: DeployTarget) -> list[ManagedService]:
        host = await resolve_host(target.hostname or "")
        raw = await agent_request("GET", host.ip, _BASE)
        return [_to_service(c, endpoint=_endpoint_from(c, host.ip)) for c in (raw or [])]

    async def status(self, target: DeployTarget, name: str) -> ManagedService:
        host = await resolve_host(target.hostname or "")
        raw = await agent_request("GET", host.ip, f"{_BASE}/{name}")
        return _to_service(raw, endpoint=_endpoint_from(raw, host.ip))

    async def scale(self, target: DeployTarget, name: str, replicas: int) -> ManagedService:
        # docker 는 이름붙은 인스턴스 추가/삭제로 확장한다(deploy/remove). 단일 이름 scale 미지원.
        raise DeployError(
            "docker 는 이름 단위 scale 을 지원하지 않습니다. replicas 로 재배포하거나 인스턴스를 제거하세요.",
            code=400,
        )

    async def action(self, target: DeployTarget, name: str, action: str) -> ManagedService:
        if action not in ("start", "stop", "restart"):
            raise DeployError(f"unknown action: {action}", code=400)
        host = await resolve_host(target.hostname or "")
        return _to_service(await agent_request("POST", host.ip, f"{_BASE}/{name}/{action}"))

    async def remove(self, target: DeployTarget, name: str) -> None:
        host = await resolve_host(target.hostname or "")
        await agent_request("DELETE", host.ip, f"{_BASE}/{name}")

    async def logs(
        self, target: DeployTarget, name: str, *, tail: int = 200, instance: str | None = None
    ) -> str:
        host = await resolve_host(target.hostname or "")
        raw = await agent_request("GET", host.ip, f"{_BASE}/{name}/logs?tail={tail}")
        if isinstance(raw, dict):
            return raw.get("logs") or raw.get("output") or ""
        return str(raw)
