# SPDX-License-Identifier: Apache-2.0
"""kubernetes_asyncio 래퍼 — 등록된 클러스터(SA 토큰/CA)로 Deployment/Service/Pod 조작.

kubernetes_asyncio 는 지연 임포트(미설치 시 앱은 정상, k8s 배포 시도 시에만 안내).
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone

from app.deploy.cluster_models import K8sCluster
from app.deploy.models import DeployError

_MANAGED_SELECTOR = "app.kubernetes.io/managed-by=argus-rag-studio"


def _load_k8s():
    try:
        from kubernetes_asyncio import client  # noqa: PLC0415
        from kubernetes_asyncio.client.exceptions import ApiException  # noqa: PLC0415
        return client, ApiException
    except ImportError as e:  # pragma: no cover
        raise DeployError("kubernetes_asyncio 미설치 — k8s 배포 불가", code=501) from e


def _state(desired: int, ready: int) -> str:
    if desired == 0:
        return "stopped"
    if ready >= desired:
        return "running"
    return "partial" if ready > 0 else "pending"


def _dep_to_dict(dep) -> dict:
    spec = dep.spec
    status = dep.status
    desired = spec.replicas or 0
    ready = (status.ready_replicas if status else 0) or 0
    containers = spec.template.spec.containers
    image = containers[0].image if containers else None
    labels = dep.metadata.labels or {}
    return {
        "name": dep.metadata.name,
        "kind": labels.get("argus.rag/kind", ""),
        "desired": desired,
        "ready": ready,
        "state": _state(desired, ready),
        "image": image,
    }


class K8sClient:
    """1개 클러스터에 대한 조작. 호출마다 ApiClient 를 열고 닫는다."""

    def __init__(self, cluster: K8sCluster) -> None:
        self.cluster = cluster

    def _config(self):
        client, _ = _load_k8s()
        cfg = client.Configuration()
        cfg.host = self.cluster.api_server
        if self.cluster.token:
            cfg.api_key = {"authorization": self.cluster.token}
            cfg.api_key_prefix = {"authorization": "Bearer"}
        cfg.verify_ssl = bool(self.cluster.verify_ssl)
        if self.cluster.ca_cert:
            f = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
            f.write(self.cluster.ca_cert)
            f.flush()
            cfg.ssl_ca_cert = f.name
        return client, cfg

    async def apply(self, ns: str, deployment: dict, service: dict | None) -> None:
        """Deployment(+Service) 생성 또는 갱신(있으면 patch)."""
        client, cfg = self._config()
        _, ApiException = _load_k8s()  # noqa: N806  (예외 클래스 참조)
        async with client.ApiClient(cfg) as api:
            apps = client.AppsV1Api(api)
            core = client.CoreV1Api(api)
            name = deployment["metadata"]["name"]
            try:
                await apps.create_namespaced_deployment(ns, deployment)
            except ApiException as e:
                if e.status == 409:
                    await apps.patch_namespaced_deployment(name, ns, deployment)
                else:
                    raise DeployError(f"Deployment apply 실패: {e.status} {e.reason}", code=e.status or 502) from e
            if service:
                try:
                    await core.create_namespaced_service(ns, service)
                except ApiException as e:
                    if e.status == 409:
                        # ClusterIP 는 immutable 필드가 있어 patch (metadata/ports 만)
                        await core.patch_namespaced_service(name, ns, service)
                    else:
                        raise DeployError(f"Service apply 실패: {e.status} {e.reason}", code=e.status or 502) from e

    async def list(self, ns: str) -> list[dict]:
        client, cfg = self._config()
        async with client.ApiClient(cfg) as api:
            apps = client.AppsV1Api(api)
            res = await apps.list_namespaced_deployment(ns, label_selector=_MANAGED_SELECTOR)
            return [_dep_to_dict(d) for d in res.items]

    async def read(self, ns: str, name: str) -> dict:
        client, cfg = self._config()
        _, ApiException = _load_k8s()  # noqa: N806  (예외 클래스 참조)
        async with client.ApiClient(cfg) as api:
            apps = client.AppsV1Api(api)
            try:
                return _dep_to_dict(await apps.read_namespaced_deployment(name, ns))
            except ApiException as e:
                raise DeployError(f"Deployment 조회 실패: {e.status}", code=e.status or 404) from e

    async def scale(self, ns: str, name: str, replicas: int) -> dict:
        client, cfg = self._config()
        async with client.ApiClient(cfg) as api:
            apps = client.AppsV1Api(api)
            await apps.patch_namespaced_deployment(name, ns, {"spec": {"replicas": replicas}})
            return _dep_to_dict(await apps.read_namespaced_deployment(name, ns))

    async def restart(self, ns: str, name: str) -> dict:
        """rollout restart — 템플릿 어노테이션 갱신으로 파드 재생성."""
        client, cfg = self._config()
        stamp = datetime.now(timezone.utc).isoformat()
        patch = {"spec": {"template": {"metadata": {"annotations": {"argus.rag/restartedAt": stamp}}}}}
        async with client.ApiClient(cfg) as api:
            apps = client.AppsV1Api(api)
            await apps.patch_namespaced_deployment(name, ns, patch)
            return _dep_to_dict(await apps.read_namespaced_deployment(name, ns))

    async def delete(self, ns: str, name: str) -> None:
        client, cfg = self._config()
        _, ApiException = _load_k8s()  # noqa: N806  (예외 클래스 참조)
        async with client.ApiClient(cfg) as api:
            apps = client.AppsV1Api(api)
            core = client.CoreV1Api(api)
            for fn in (apps.delete_namespaced_deployment, core.delete_namespaced_service):
                try:
                    await fn(name, ns)
                except ApiException as e:
                    if e.status != 404:
                        raise DeployError(f"삭제 실패: {e.status}", code=e.status or 502) from e

    async def logs(self, ns: str, name: str, tail: int) -> str:
        client, cfg = self._config()
        async with client.ApiClient(cfg) as api:
            core = client.CoreV1Api(api)
            pods = await core.list_namespaced_pod(ns, label_selector=f"app={name}")
            if not pods.items:
                return ""
            return await core.read_namespaced_pod_log(pods.items[0].metadata.name, ns, tail_lines=tail)
