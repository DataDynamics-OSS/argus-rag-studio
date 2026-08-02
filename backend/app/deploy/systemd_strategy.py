# SPDX-License-Identifier: Apache-2.0
"""SystemdStrategy — 에이전트 servicemgr 경유(호스트 root). 주로 worker(비컨테이너 바이너리)."""

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
from app.servermgr.schemas import DeployWorkerRequest

_BASE = "/api/v1/service"
# 에이전트 자신의 unit 도 argus-rag- 접두사라 servicemgr 목록에 잡힌다 — 관리 대상에서 제외(자가 제어 방지).
_SELF_UNIT = "argus-rag-studio-agent"


def _to_request(spec: DeploySpec) -> DeployWorkerRequest:
    """DeploySpec → DeployWorkerRequest. systemd 전용 옵션은 spec.env 의 제어키로 전달.

    working_directory(필수) / python_path / user 는 spec.env 에서 꺼내고 나머지는 환경변수로 넘긴다.
    """
    env = dict(spec.env)
    working_directory = env.pop("working_directory", None)
    python_path = env.pop("python_path", "python")
    user = env.pop("user", None)
    if not working_directory:
        raise DeployError("systemd worker 배포에는 env.working_directory 가 필요합니다", code=400)
    return DeployWorkerRequest(
        replicas=spec.replicas,
        working_directory=working_directory,
        python_path=python_path,
        user=user,
        version=spec.version,
        environment=env,
    )


def _to_service(raw: dict, *, hostname: str | None = None) -> ManagedService:
    """에이전트 ServiceStatus(dict) → ManagedService.

    instance.node 에 호스트명을 실어 워커 레지스트리 교차참조(enrich_workers)의
    매칭 키로 쓴다 — systemd 워커의 레지스트리 hostname 은 머신 호스트명."""
    active = str(raw.get("active_state") or "").lower()
    running = active == "active"
    return ManagedService(
        name=str(raw.get("name")),
        kind=str(raw.get("kind") or "worker"),
        runtime="systemd",
        desired_replicas=1,
        ready_replicas=1 if running else 0,
        state="running" if running else "stopped",
        version=raw.get("version"),
        instances=[
            ManagedInstance(
                id=str(raw.get("name")),
                state=raw.get("sub_state") or active or "unknown",
                node=hostname,
                pid=raw.get("pid"),
            )
        ],
    )


class SystemdStrategy(DeployStrategy):
    runtime = "systemd"

    def required_privilege(self) -> Privilege:
        return Privilege.host_root

    def supports(self, kind: ServiceKind) -> bool:
        return kind == ServiceKind.worker  # 비컨테이너 바이너리 워커

    async def deploy(self, spec: DeploySpec, target: DeployTarget) -> ManagedService:
        if not self.supports(spec.kind):
            raise DeployError(f"systemd 는 {spec.kind} 를 지원하지 않습니다(worker 만)", code=400)
        if not target.hostname:
            raise DeployError("systemd 배포는 hostname 이 필요합니다", code=400)
        host = await resolve_host(target.hostname)

        existing = await agent_request("GET", host.ip, _BASE)
        names = [s.get("name") for s in (existing or []) if s.get("name")]
        slots = sm.next_worker_slots(names, spec.replicas)

        req = _to_request(spec)
        deployed: list[dict] = []
        for name in slots:
            payload = sm.build_worker_spec(name, req)
            deployed.append(await agent_request("POST", host.ip, _BASE, json=payload))

        svc = _to_service(deployed[0], hostname=target.hostname)
        svc.desired_replicas = svc.ready_replicas = len(deployed)
        return svc

    async def list(self, target: DeployTarget) -> list[ManagedService]:
        host = await resolve_host(target.hostname or "")
        raw = await agent_request("GET", host.ip, _BASE)
        return [
            _to_service(s, hostname=target.hostname)
            for s in (raw or []) if s.get("name") != _SELF_UNIT
        ]

    async def status(self, target: DeployTarget, name: str) -> ManagedService:
        host = await resolve_host(target.hostname or "")
        return _to_service(
            await agent_request("GET", host.ip, f"{_BASE}/{name}"), hostname=target.hostname
        )

    async def scale(self, target: DeployTarget, name: str, replicas: int) -> ManagedService:
        raise DeployError(
            "systemd 는 이름 단위 scale 을 지원하지 않습니다. replicas 로 재배포하거나 unit 을 제거하세요.",
            code=400,
        )

    async def action(self, target: DeployTarget, name: str, action: str) -> ManagedService:
        if name == _SELF_UNIT:
            raise DeployError("에이전트 자신은 제어할 수 없습니다", code=400)
        if action not in ("start", "stop", "restart"):
            raise DeployError(f"unknown action: {action}", code=400)
        host = await resolve_host(target.hostname or "")
        return _to_service(await agent_request("POST", host.ip, f"{_BASE}/{name}/{action}"))

    async def remove(self, target: DeployTarget, name: str) -> None:
        if name == _SELF_UNIT:
            raise DeployError("에이전트 자신은 제어할 수 없습니다", code=400)
        host = await resolve_host(target.hostname or "")
        await agent_request("DELETE", host.ip, f"{_BASE}/{name}")

    async def logs(
        self, target: DeployTarget, name: str, *, tail: int = 200, instance: str | None = None
    ) -> str:
        raise DeployError("systemd 로그는 터미널(journalctl)로 확인하세요", code=400)
