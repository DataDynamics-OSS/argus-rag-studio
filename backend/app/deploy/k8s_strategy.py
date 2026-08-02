# SPDX-License-Identifier: Apache-2.0
"""K8sStrategy — 에이전트리스(백엔드 직접, 네임스페이스 RBAC). 설계 design/deploy-strategy.md §4.3.

매니페스트 빌더(순수)는 그대로 두고, 실행은 등록된 클러스터(cluster_service)의 K8sClient 로 수행한다.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Callable

from app.deploy import cluster_service
from app.deploy.k8s_client import K8sClient
from app.deploy.models import (
    DeployError,
    DeploySpec,
    DeployTarget,
    ManagedService,
    Privilege,
    ServiceKind,
)
from app.deploy.strategy import DeployStrategy
from app.servermgr import service as sm

_MANAGED_LABEL = "app.kubernetes.io/managed-by"
_MANAGED_BY = "argus-rag-studio"


def _name(kind: str) -> str:
    return f"argus-rag-{kind.replace('_', '-')}"


def build_manifests(
    spec: DeploySpec, *, image: str, variant: str, namespace: str, arch: str = "amd64"
) -> dict:
    """DeploySpec → {deployment, service?} 매니페스트(dict). 순수 함수.

    - 서버형 = Deployment + Service(ClusterIP), worker = Deployment(replicas=N).
    - GPU 요청 시 resources.limits['nvidia.com/gpu'] + arch nodeSelector.
    """
    kind = spec.kind.value
    cat = sm.CONTAINER_KINDS[kind]
    name = _name(kind)
    labels = {
        _MANAGED_LABEL: _MANAGED_BY,
        "argus.rag/kind": kind,
        "argus.rag/variant": variant or "cpu",
        "app": name,
    }
    container: dict = {
        "name": name,
        "image": image,
        "env": [{"name": k, "value": v} for k, v in sorted(spec.env.items())],
    }
    if cat["port"]:
        container["ports"] = [{"containerPort": cat["port"]}]
    if spec.gpu and cat.get("gpu_variant"):
        container["resources"] = {"limits": {"nvidia.com/gpu": 1}}
    pod_spec: dict = {"containers": [container], "nodeSelector": {"kubernetes.io/arch": arch}}

    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": namespace, "labels": labels},
        "spec": {
            "replicas": spec.replicas if kind == "worker" else 1,
            "selector": {"matchLabels": {"app": name}},
            "template": {"metadata": {"labels": labels}, "spec": pod_spec},
        },
    }
    service = None
    if cat["port"]:
        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": name, "namespace": namespace, "labels": labels},
            "spec": {
                "selector": {"app": name},
                "ports": [{"port": cat["port"], "targetPort": cat["port"]}],
                "type": "ClusterIP",
            },
        }
    return {"deployment": deployment, "service": service}


def cluster_endpoint(kind: str, namespace: str) -> str | None:
    """클러스터 내부 접속 URL(설정 주입용). 백엔드가 클러스터 밖이면 NodePort/Ingress 필요."""
    cat = sm.CONTAINER_KINDS.get(kind)
    if not cat or not cat["port"]:
        return None
    return f"http://{_name(kind)}.{namespace}.svc.cluster.local:{cat['port']}{cat['suffix']}"


def _to_service(d: dict, *, endpoint: str | None = None) -> ManagedService:
    return ManagedService(
        name=d["name"],
        kind=d["kind"],
        runtime="k8s",
        desired_replicas=d["desired"],
        ready_replicas=d["ready"],
        state=d["state"],
        image=d.get("image"),
        endpoint=endpoint,
    )


class K8sStrategy(DeployStrategy):
    runtime = "k8s"

    def __init__(self, client_factory: Callable[..., K8sClient] | None = None) -> None:
        # 테스트에서 가짜 클라이언트를 주입할 수 있게 팩토리화.
        self._client_factory = client_factory or (lambda cluster: K8sClient(cluster))

    def required_privilege(self) -> Privilege:
        return Privilege.cluster_rbac

    def supports(self, kind: ServiceKind) -> bool:
        return kind in sm.CONTAINER_KINDS

    async def _resolve(self, target: DeployTarget):
        if not target.cluster_id:
            raise DeployError("k8s 배포는 cluster_id 가 필요합니다", code=400)
        cluster = await cluster_service.require_cluster(target.cluster_id)
        ns = target.namespace or cluster.default_namespace
        return self._client_factory(cluster), ns, cluster.default_arch

    async def deploy(self, spec: DeploySpec, target: DeployTarget) -> ManagedService:
        client, ns, arch = await self._resolve(target)
        kind = spec.kind.value
        # 변형/이미지 결정(호스트 전략은 build_* 내부, k8s 는 여기서).
        shim = SimpleNamespace(variant=spec.variant, gpus="all" if spec.gpu else None)
        variant = sm.resolve_variant(kind, shim, arch=arch, gpu_count=1 if spec.gpu else 0)
        image = sm.image_for(kind, variant, spec.image)
        if spec.kind == ServiceKind.worker:
            spec.env.setdefault("ARGUS_WORKER_RUNTIME", "k8s")  # 잡 모니터링 배포 방식 표시
        m = build_manifests(spec, image=image, variant=variant, namespace=ns, arch=arch)
        await client.apply(ns, m["deployment"], m["service"])
        status = await client.read(ns, _name(kind))
        return _to_service(status, endpoint=cluster_endpoint(kind, ns))

    async def list(self, target: DeployTarget) -> list[ManagedService]:
        client, ns, _ = await self._resolve(target)
        return [_to_service(d) for d in await client.list(ns)]

    async def status(self, target: DeployTarget, name: str) -> ManagedService:
        client, ns, _ = await self._resolve(target)
        return _to_service(await client.read(ns, name))

    async def scale(self, target: DeployTarget, name: str, replicas: int) -> ManagedService:
        client, ns, _ = await self._resolve(target)
        return _to_service(await client.scale(ns, name, replicas))

    async def action(self, target: DeployTarget, name: str, action: str) -> ManagedService:
        client, ns, _ = await self._resolve(target)
        if action == "restart":
            return _to_service(await client.restart(ns, name))
        if action == "stop":
            return _to_service(await client.scale(ns, name, 0))
        if action == "start":
            return _to_service(await client.scale(ns, name, 1))
        raise DeployError(f"unknown action: {action}", code=400)

    async def remove(self, target: DeployTarget, name: str) -> None:
        client, ns, _ = await self._resolve(target)
        await client.delete(ns, name)

    async def logs(
        self, target: DeployTarget, name: str, *, tail: int = 200, instance: str | None = None
    ) -> str:
        client, ns, _ = await self._resolve(target)
        return await client.logs(ns, name, tail)
