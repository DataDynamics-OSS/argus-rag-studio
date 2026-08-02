# SPDX-License-Identifier: Apache-2.0
"""deploy 패키지 — 전략 선택/변환/매니페스트(순수 로직) 단위 테스트."""

import pytest

from app.deploy import docker_strategy, systemd_strategy
from app.deploy.docker_strategy import DockerStrategy
from app.deploy.k8s_strategy import K8sStrategy, build_manifests, cluster_endpoint
from app.deploy.models import (
    DeployError,
    DeploySpec,
    DeployTarget,
    Privilege,
    ServiceKind,
)
from app.deploy.registry import get_strategy
from app.deploy.systemd_strategy import SystemdStrategy

# ---------------------------------------------------------------------------
# 레지스트리 / 권한
# ---------------------------------------------------------------------------


def test_registry_selects_strategy_by_target():
    assert isinstance(get_strategy(DeployTarget(type="agent_host", method="docker")), DockerStrategy)
    assert isinstance(get_strategy(DeployTarget(type="agent_host", method="systemd")), SystemdStrategy)
    assert isinstance(get_strategy(DeployTarget(type="agent_host")), DockerStrategy)  # 기본 docker
    assert isinstance(get_strategy(DeployTarget(type="k8s", cluster_id="c1")), K8sStrategy)


def test_registry_unknown_target():
    with pytest.raises(DeployError) as ei:
        get_strategy(DeployTarget(type="nope"))
    assert ei.value.code == 400


def test_required_privileges():
    assert DockerStrategy().required_privilege() == Privilege.host_docker
    assert SystemdStrategy().required_privilege() == Privilege.host_root
    assert K8sStrategy().required_privilege() == Privilege.cluster_rbac


def test_supports():
    assert DockerStrategy().supports(ServiceKind.embedding)
    assert SystemdStrategy().supports(ServiceKind.worker)
    assert not SystemdStrategy().supports(ServiceKind.embedding)  # 컨테이너 전용


# ---------------------------------------------------------------------------
# Docker 변환
# ---------------------------------------------------------------------------


def test_docker_to_request_maps_fields():
    spec = DeploySpec(
        kind=ServiceKind.embedding,
        variant="gpu-torch",
        gpu=True,
        version="0.4.2",
        env={"FOO": "bar"},
        network="host",
        extra_hosts=["db:192.0.2.10"],
    )
    req = docker_strategy._to_request(spec)
    assert req.kind == "embedding"
    assert req.variant == "gpu-torch"
    assert req.gpus == "all"  # gpu=True → --gpus all
    assert req.environment == {"FOO": "bar"}
    assert req.network == "host"
    assert req.extra_hosts == ["db:192.0.2.10"]


def test_docker_to_request_no_gpu():
    req = docker_strategy._to_request(DeploySpec(kind=ServiceKind.worker, gpu=False))
    assert req.gpus is None


def test_docker_to_service_running():
    svc = docker_strategy._to_service(
        {"name": "argus-rag-embedding-1", "image": "img:1", "state": "running", "kind": "embedding", "id": "abc"},
        endpoint="http://192.0.2.47:8080/v1",
    )
    assert svc.runtime == "docker"
    assert svc.state == "running"
    assert svc.ready_replicas == 1
    assert svc.endpoint == "http://192.0.2.47:8080/v1"
    assert svc.instances[0].id == "abc"


# ---------------------------------------------------------------------------
# systemd 변환
# ---------------------------------------------------------------------------


def test_systemd_to_request_requires_working_directory():
    with pytest.raises(DeployError) as ei:
        systemd_strategy._to_request(DeploySpec(kind=ServiceKind.worker))
    assert ei.value.code == 400


def test_systemd_to_request_extracts_control_keys():
    spec = DeploySpec(
        kind=ServiceKind.worker,
        replicas=3,
        env={"working_directory": "/opt/app", "python_path": "/venv/bin/python", "user": "argus", "X": "1"},
    )
    req = systemd_strategy._to_request(spec)
    assert req.working_directory == "/opt/app"
    assert req.python_path == "/venv/bin/python"
    assert req.user == "argus"
    assert req.replicas == 3
    assert req.environment == {"X": "1"}  # 제어키 제거됨


# ---------------------------------------------------------------------------
# K8s 매니페스트 (순수)
# ---------------------------------------------------------------------------


def test_k8s_manifests_server_kind_has_service_and_gpu():
    spec = DeploySpec(kind=ServiceKind.embedding, gpu=True, env={"EMBED_PORT": "8080"})
    m = build_manifests(spec, image="reg/embed:0.4.2-gpu-torch", variant="gpu-torch", namespace="rag", arch="arm64")
    dep, svc = m["deployment"], m["service"]
    assert dep["kind"] == "Deployment"
    assert dep["metadata"]["namespace"] == "rag"
    c = dep["spec"]["template"]["spec"]["containers"][0]
    assert c["image"] == "reg/embed:0.4.2-gpu-torch"
    assert c["resources"]["limits"]["nvidia.com/gpu"] == 1
    assert dep["spec"]["template"]["spec"]["nodeSelector"]["kubernetes.io/arch"] == "arm64"
    assert dep["spec"]["replicas"] == 1  # 서버형 단일
    assert svc is not None and svc["spec"]["ports"][0]["port"] == 8080
    assert dep["metadata"]["labels"]["argus.rag/kind"] == "embedding"


def test_k8s_manifests_worker_no_service_replicas():
    spec = DeploySpec(kind=ServiceKind.worker, replicas=4)
    m = build_manifests(spec, image="reg/worker:0.4.2", variant="", namespace="rag")
    assert m["service"] is None  # worker 포트 없음
    assert m["deployment"]["spec"]["replicas"] == 4


def test_k8s_cluster_endpoint():
    assert cluster_endpoint("embedding", "rag") == "http://argus-rag-embedding.rag.svc.cluster.local:8080/v1"
    assert cluster_endpoint("worker", "rag") is None  # 포트 없음


@pytest.mark.asyncio
async def test_k8s_deploy_unregistered_cluster_404():
    from unittest.mock import AsyncMock, patch

    with patch("app.deploy.cluster_service.require_cluster", AsyncMock(side_effect=DeployError("없음", code=404))):
        with pytest.raises(DeployError) as ei:
            await K8sStrategy().deploy(
                DeploySpec(kind=ServiceKind.embedding), DeployTarget(type="k8s", cluster_id="c1")
            )
    assert ei.value.code == 404


# ---------------------------------------------------------------------------
# 통합 API 스키마 변환 (Phase 3)
# ---------------------------------------------------------------------------


def test_specin_to_model_roundtrip():
    from app.deploy.schemas import DeploySpecIn

    spec = DeploySpecIn(kind="embedding", replicas=2, gpu=True, env={"A": "1"}).to_model()
    assert spec.kind == ServiceKind.embedding
    assert spec.replicas == 2 and spec.gpu is True
    assert spec.env == {"A": "1"}


def test_targetin_to_model():
    from app.deploy.schemas import DeployTargetIn

    t = DeployTargetIn(type="agent_host", hostname="h1", method="docker").to_model()
    assert t.type == "agent_host" and t.hostname == "h1" and t.method == "docker"


def test_managed_service_out_of():
    from app.deploy.models import ManagedInstance, ManagedService
    from app.deploy.schemas import ManagedServiceOut

    out = ManagedServiceOut.of(
        ManagedService(
            name="argus-rag-embedding-1",
            kind="embedding",
            runtime="docker",
            desired_replicas=1,
            ready_replicas=1,
            state="running",
            endpoint="http://h:8080/v1",
            instances=[ManagedInstance(id="abc", state="running")],
        )
    )
    assert out.runtime == "docker"
    assert out.endpoint == "http://h:8080/v1"
    assert out.instances[0].id == "abc"


def test_deploy_routes_registered():
    import app.main as m

    paths = {r.path for r in m.app.routes if hasattr(r, "path")}
    assert "/api/v1/deploy" in paths
    assert "/api/v1/deploy/{name}/{action}" in paths
    assert "/api/v1/deploy/{name}/scale/{replicas}" in paths


# ---------------------------------------------------------------------------
# K8s 실행 (Phase 4) — 클러스터/클라이언트 모킹
# ---------------------------------------------------------------------------

from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402


def _fake_cluster():
    return SimpleNamespace(
        cluster_id="c1", name="dev", api_server="https://k:6443", token="t",
        ca_cert=None, verify_ssl=True, default_namespace="rag", default_arch="amd64",
    )


def _fake_client(read_ret=None):
    c = AsyncMock()
    c.apply = AsyncMock(return_value=None)
    c.read = AsyncMock(
        return_value=read_ret
        or {"name": "argus-rag-embedding", "kind": "embedding", "desired": 1, "ready": 1, "state": "running", "image": "img"}
    )
    c.list = AsyncMock(return_value=[
        {"name": "argus-rag-embedding", "kind": "embedding", "desired": 1, "ready": 1, "state": "running", "image": "img"}
    ])
    c.scale = AsyncMock(return_value={"name": "argus-rag-worker", "kind": "worker", "desired": 0, "ready": 0, "state": "stopped", "image": "img"})
    c.restart = AsyncMock(return_value={"name": "argus-rag-embedding", "kind": "embedding", "desired": 1, "ready": 1, "state": "running", "image": "img"})
    c.delete = AsyncMock(return_value=None)
    c.logs = AsyncMock(return_value="hello logs")
    return c


@pytest.mark.asyncio
async def test_k8s_deploy_applies_manifests_and_returns_endpoint():
    fake = _fake_client()
    strat = K8sStrategy(client_factory=lambda cluster: fake)
    with patch("app.deploy.cluster_service.require_cluster", AsyncMock(return_value=_fake_cluster())):
        svc = await strat.deploy(
            DeploySpec(kind=ServiceKind.embedding, gpu=True, env={"EMBED_PORT": "8080"}),
            DeployTarget(type="k8s", cluster_id="c1", namespace="rag"),
        )
    fake.apply.assert_awaited_once()
    ns_arg, dep, svc_manifest = fake.apply.await_args.args
    assert ns_arg == "rag"
    # amd64 GPU → gpu 변형, image_for 로 태그 산출
    c = dep["spec"]["template"]["spec"]["containers"][0]
    assert c["resources"]["limits"]["nvidia.com/gpu"] == 1
    assert svc_manifest is not None
    assert svc.runtime == "k8s"
    assert svc.endpoint == "http://argus-rag-embedding.rag.svc.cluster.local:8080/v1"


@pytest.mark.asyncio
async def test_k8s_action_stop_scales_to_zero():
    fake = _fake_client()
    strat = K8sStrategy(client_factory=lambda cluster: fake)
    with patch("app.deploy.cluster_service.require_cluster", AsyncMock(return_value=_fake_cluster())):
        await strat.action(DeployTarget(type="k8s", cluster_id="c1"), "argus-rag-worker", "stop")
    fake.scale.assert_awaited_once()
    assert fake.scale.await_args.args[2] == 0  # replicas=0


@pytest.mark.asyncio
async def test_k8s_list_and_logs():
    fake = _fake_client()
    strat = K8sStrategy(client_factory=lambda cluster: fake)
    with patch("app.deploy.cluster_service.require_cluster", AsyncMock(return_value=_fake_cluster())):
        items = await strat.list(DeployTarget(type="k8s", cluster_id="c1"))
        logs = await strat.logs(DeployTarget(type="k8s", cluster_id="c1"), "argus-rag-embedding")
    assert items[0].runtime == "k8s" and items[0].state == "running"
    assert logs == "hello logs"


@pytest.mark.asyncio
async def test_k8s_deploy_requires_cluster_id():
    strat = K8sStrategy(client_factory=lambda cluster: _fake_client())
    with pytest.raises(DeployError) as ei:
        await strat.deploy(DeploySpec(kind=ServiceKind.embedding), DeployTarget(type="k8s"))
    assert ei.value.code == 400


@pytest.mark.asyncio
async def test_systemd_self_unit_protected():
    from app.deploy.systemd_strategy import SystemdStrategy

    s = SystemdStrategy()
    with pytest.raises(DeployError) as ei:
        await s.action(DeployTarget(type="agent_host", hostname="h", method="systemd"), "argus-rag-studio-agent", "stop")
    assert ei.value.code == 400
