# SPDX-License-Identifier: Apache-2.0
"""deploy overview — 전체 서비스 집계(부분 실패 병합·워커 enrich 1회) 단위 테스트.

설계: design/agent-services-overview.md §3.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.deploy import service as deploy_service
from app.deploy.models import DeployError, ManagedInstance, ManagedService


def _svc(name: str, kind: str = "embedding", runtime: str = "docker") -> ManagedService:
    return ManagedService(name=name, kind=kind, runtime=runtime,
                          instances=[ManagedInstance(id=f"{name}-1", state="running")])


def _cluster(cluster_id: str = "c1", namespace: str = "argus") -> SimpleNamespace:
    return SimpleNamespace(cluster_id=cluster_id, default_namespace=namespace)


@pytest.mark.asyncio
async def test_overview_enumerates_hosts_and_clusters():
    """REGISTERED 호스트는 docker+systemd 2개 대상, 클러스터는 1개 대상."""
    calls: list[tuple] = []

    async def fake_list(target):
        calls.append((target.type, target.hostname or target.cluster_id, target.method))
        return [_svc(f"svc-{len(calls)}")]

    with patch.object(deploy_service, "list_services", side_effect=fake_list), \
         patch.object(deploy_service, "enrich_workers", new=AsyncMock(side_effect=lambda s, x: x)):
        entries = await deploy_service.collect_overview(
            None, [("host-a", "REGISTERED")], [_cluster()]
        )

    assert sorted(calls) == [
        ("agent_host", "host-a", "docker"),
        ("agent_host", "host-a", "systemd"),
        ("k8s", "c1", None),
    ]
    assert len(entries) == 3
    assert all(e["error"] is None and len(e["services"]) == 1 for e in entries)


@pytest.mark.asyncio
async def test_overview_merges_partial_failures():
    """대상 하나의 실패(DeployError/예외)는 error 로 병합 — 나머지는 정상 반환."""

    async def fake_list(target):
        if target.method == "systemd":
            raise DeployError("에이전트 응답 없음", code=502)
        if target.type == "k8s":
            raise RuntimeError("클러스터 인증 만료")
        return [_svc("embed-1")]

    with patch.object(deploy_service, "list_services", side_effect=fake_list), \
         patch.object(deploy_service, "enrich_workers", new=AsyncMock(side_effect=lambda s, x: x)):
        entries = await deploy_service.collect_overview(
            None, [("host-a", "REGISTERED")], [_cluster()]
        )

    by_key = {(e["target"].type, e["target"].method): e for e in entries}
    assert by_key[("agent_host", "docker")]["error"] is None
    assert "에이전트 응답 없음" in by_key[("agent_host", "systemd")]["error"]
    assert "인증 만료" in by_key[("k8s", None)]["error"]
    assert by_key[("k8s", None)]["services"] == []


@pytest.mark.asyncio
async def test_overview_disconnected_host_skips_probe():
    """DISCONNECTED 호스트는 네트워크 시도 없이 즉시 실패 행 1개."""
    probe = AsyncMock(return_value=[])
    with patch.object(deploy_service, "list_services", probe), \
         patch.object(deploy_service, "enrich_workers", new=AsyncMock(side_effect=lambda s, x: x)):
        entries = await deploy_service.collect_overview(
            None, [("host-down", "DISCONNECTED")], []
        )

    probe.assert_not_awaited()
    assert len(entries) == 1
    assert entries[0]["target"].hostname == "host-down"
    assert "연결 끊김" in entries[0]["error"]


@pytest.mark.asyncio
async def test_overview_timeout_becomes_error(monkeypatch):
    """느린 대상은 타임아웃 error 로 — 전체 응답을 붙들지 않는다."""
    import asyncio

    monkeypatch.setattr(deploy_service, "OVERVIEW_TIMEOUT_S", 0.05)

    async def slow_list(target):
        await asyncio.sleep(1)
        return []

    with patch.object(deploy_service, "list_services", side_effect=slow_list), \
         patch.object(deploy_service, "enrich_workers", new=AsyncMock(side_effect=lambda s, x: x)):
        entries = await deploy_service.collect_overview(
            None, [("host-slow", "REGISTERED")], []
        )

    assert len(entries) == 2  # docker + systemd
    assert all("시간 초과" in e["error"] for e in entries)


@pytest.mark.asyncio
async def test_external_merges_heartbeat_and_settings_with_dedup():
    """외부(수동) 수집 — 관리형 netloc 중복 제거·heartbeat 우선·설정 kind 매핑(rerank→reranker)."""
    from app.embedding.router import ExtServerStat

    registered = [
        # 관리형(argus-rag-embedding-1, 192.0.2.48:8090)과 같은 주소 — 제외돼야 함
        ExtServerStat(kind="embedding", url="http://192.0.2.48:8090", ok=True,
                      stats={"version": "0.1.0"}),
        # 순수 수동 배포 — 포함
        ExtServerStat(kind="reranker", url="http://192.0.2.99:8081", ok=False,
                      error="하트비트 끊김(30s 전)"),
    ]

    probes = [
        ExtServerStat(kind="embedding", url="http://192.0.2.48:8090/stats", ok=True,
                      stats={"model": "m"}),                        # 관리형과 중복 — 제외
        ExtServerStat(kind="rerank", url="http://192.0.2.77:8081/stats", ok=True,
                      stats={"model": "m", "system": {"cpu_percent": 1.5}}),  # 신규 — 포함(kind 매핑)
    ]
    out = deploy_service.external_services({"192.0.2.48:8090"}, registered, probes)

    by = {(x["kind"], x["source"]): x for x in out}
    assert len(out) == 2
    assert ("reranker", "heartbeat") in by and not by[("reranker", "heartbeat")]["ok"]
    assert ("reranker", "settings") in by  # settings 의 "rerank" 가 매핑됨
    assert by[("reranker", "settings")]["cpu_percent"] == 1.5


def test_merge_heartbeat_stats_attaches_to_managed_and_parses_vlm():
    """heartbeat stats 는 endpoint netloc 일치 관리형 행에 병합, vlm 은 Cmd 에서 모델 파싱."""
    from app.embedding.router import ExtServerStat
    from app.deploy.models import DeployTarget

    embed = _svc("argus-rag-embedding-1", kind="embedding")
    embed.endpoint = "http://192.0.2.48:8090/v1"
    vlm = _svc("argus-rag-vlm-1", kind="vlm")
    vlm.endpoint = "http://192.0.2.47:8000/v1"
    vlm.command = ["vllm", "serve", "Qwen/Qwen2-VL-7B-Instruct",
                   "--served-model-name", "qwen2-vl-7b"]
    entries = [{"target": DeployTarget(type="agent_host", hostname="h"),
                "services": [embed, vlm], "error": None}]
    registered = [ExtServerStat(
        kind="embedding", url="http://192.0.2.48:8090", ok=True,
        stats={"model": "mxbai", "device": "cuda", "uptime_seconds": 10,
               "models": {"loaded": ["mxbai", "e5"]},
               "system": {"cpu_percent": 1.0}, "gpu": [{"name": "GB10", "utilization_percent": 3}]},
    )]

    netlocs = deploy_service.merge_heartbeat_stats(entries, registered)

    assert netlocs == {"192.0.2.48:8090", "192.0.2.47:8000"}
    assert embed.stats["model"] == "mxbai" and embed.stats["device"] == "cuda"
    assert embed.stats["models_loaded"] == ["mxbai", "e5"]
    assert embed.stats["gpu"][0]["name"] == "GB10"
    assert vlm.stats == {"model": "qwen2-vl-7b"}  # Cmd 파싱 보충


@pytest.mark.asyncio
async def test_enrich_matches_multiple_systemd_workers_by_pid():
    """같은 호스트의 systemd 워커 N개 — MainPID 로 레지스트리 항목을 정확히 1:1 부착."""
    from datetime import datetime, timezone

    w1 = _svc("argus-rag-worker-1", kind="worker", runtime="systemd")
    w1.instances[0].pid = 100
    w1.instances[0].node = "host-a"
    w2 = _svc("argus-rag-worker-2", kind="worker", runtime="systemd")
    w2.instances[0].pid = 200
    w2.instances[0].node = "host-a"

    started = datetime(2026, 7, 12, tzinfo=timezone.utc)
    workers = [
        SimpleNamespace(hostname="host-a", pid=200, mode="standalone", status="busy",
                        version="0.1.1", alive=True, processed_total=7, current_job_id="j-1",
                        started_at=started, heartbeat_age_seconds=1.0, metrics={}),
        SimpleNamespace(hostname="host-a", pid=100, mode="standalone", status="idle",
                        version="0.1.1", alive=True, processed_total=2, current_job_id=None,
                        started_at=started, heartbeat_age_seconds=1.0, metrics={}),
    ]

    async def fake_list(session):
        return workers

    with patch("app.workers.service.list_workers", side_effect=fake_list):
        await deploy_service.enrich_workers(None, [w1, w2])

    assert w1.worker_status == "idle" and w1.worker_processed_total == 2    # pid 100
    assert w2.worker_status == "busy" and w2.worker_current_job == "j-1"    # pid 200
    assert w1.version == "0.1.1" and w1.started_at == started.isoformat()   # 레지스트리 보충


@pytest.mark.asyncio
async def test_worker_external_entries_shows_unmatched_standalone():
    """레지스트리 워커 중 관리형 미매칭 standalone 만 외부 행 — docker id·systemd 호스트 매칭 제외."""
    from app.deploy.models import DeployTarget

    docker_worker = _svc("argus-rag-worker-1", kind="worker")
    docker_worker.instances[0].id = "abc123def456"
    systemd_worker = _svc("argus-rag-worker-2", kind="worker", runtime="systemd")
    entries = [{"target": DeployTarget(type="agent_host", hostname="host-a"),
                "services": [docker_worker, systemd_worker], "error": None}]

    workers = [
        SimpleNamespace(hostname="abc123def456", pid=1, mode="standalone", status="idle",
                        version="0.1", alive=True, processed_total=1, current_job_id=None,
                        started_at=None, heartbeat_age_seconds=1.0, metrics={}),   # docker 매칭 → 제외
        SimpleNamespace(hostname="host-a", pid=2, mode="standalone", status="idle",
                        version="0.1", alive=True, processed_total=2, current_job_id=None,
                        started_at=None, heartbeat_age_seconds=1.0, metrics={}),   # systemd 호스트 매칭 → 제외
        SimpleNamespace(hostname="host-b", pid=3, mode="in_process", status="idle",
                        version="0.1", alive=True, processed_total=0, current_job_id=None,
                        started_at=None, heartbeat_age_seconds=1.0, metrics={}),   # API 내장 → 제외
        SimpleNamespace(hostname="dev.example.net", pid=4, mode="standalone", status="busy",
                        version="0.1.1", alive=True, processed_total=3, current_job_id="j-9",
                        started_at=None, heartbeat_age_seconds=1.0,
                        metrics={"cpu_percent": 0.6}),                             # 미매칭 → 포함
    ]

    async def fake_list(session):
        return workers

    with patch("app.workers.service.list_workers", side_effect=fake_list):
        out = await deploy_service.worker_external_entries(None, entries)

    assert len(out) == 1
    w = out[0]
    assert w["kind"] == "worker" and w["source"] == "worker" and w["ok"]
    assert w["url"] == "worker://dev.example.net/pid-4"
    assert "standalone" in w["detail"] and "처리 3건" in w["detail"] and "잡 j-9" in w["detail"]
    assert w["cpu_percent"] == 0.6


def test_served_model_from_command():
    f = deploy_service._served_model_from
    assert f(["vllm", "serve", "m", "--served-model-name", "x"]) == "x"
    assert f(["--served-model-name=y"]) == "y"
    assert f(["vllm", "serve", "m"]) is None
    assert f([]) is None


def test_docker_endpoint_derived_from_ports():
    """에이전트 inspect ports + kind 규약 포트 → endpoint(호스트 포트 오버라이드 반영)."""
    from app.deploy.docker_strategy import _endpoint_from

    raw = {"kind": "embedding", "ports": ["8090:8080"]}
    assert _endpoint_from(raw, "192.0.2.48") == "http://192.0.2.48:8090/v1"
    assert _endpoint_from({"kind": "worker", "ports": []}, "h") is None      # 포트 없는 kind
    assert _endpoint_from({"kind": "embedding", "ports": []}, "h") is None   # 구버전 에이전트
    assert _endpoint_from({"kind": "", "ports": ["1:2"]}, "h") is None       # 미분류 컨테이너


@pytest.mark.asyncio
async def test_overview_enriches_workers_once_over_merged():
    """워커 enrich 는 전 대상 병합 후 1회 호출된다."""

    async def fake_list(target):
        return [_svc(f"worker-{target.method}", kind="worker", runtime=target.method or "k8s")]

    enrich = AsyncMock(side_effect=lambda s, x: x)
    with patch.object(deploy_service, "list_services", side_effect=fake_list), \
         patch.object(deploy_service, "enrich_workers", enrich):
        await deploy_service.collect_overview(None, [("host-a", "REGISTERED")], [])

    enrich.assert_awaited_once()
    merged = enrich.await_args.args[1]
    assert {s.name for s in merged} == {"worker-docker", "worker-systemd"}
