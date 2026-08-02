# SPDX-License-Identifier: Apache-2.0
"""DeploymentService — 방식 무관 오케스트레이션. 전략 선택 + 배포 후 설정 자동주입.

변형(variant)/이미지 결정은 docker/systemd 의 경우 기존 build_* 빌더가 호스트 arch/gpu 로 수행하고,
k8s 는 Phase 4 에서 오케스트레이터가 resolve_variant/image_for 로 사전결정한다. 설계 §5.
"""

from __future__ import annotations

import asyncio
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.deploy.models import DeployError, DeploySpec, DeployTarget, ManagedService
from app.deploy.registry import get_strategy
from app.servermgr import service as sm
from app.settings import service as settings_service


async def deploy(
    session: AsyncSession, spec: DeploySpec, target: DeployTarget
) -> tuple[ManagedService, dict[str, str]]:
    """배포 + (wire_settings 시) RAG Studio 설정 주입. (ManagedService, applied_settings) 반환."""
    strat = get_strategy(target)
    if not strat.supports(spec.kind):
        raise DeployError(f"{strat.runtime} 는 {spec.kind} 를 지원하지 않습니다", code=400)

    svc = await strat.deploy(spec, target)

    applied: dict[str, str] = {}
    if spec.wire_settings and svc.endpoint:
        cat = sm.CONTAINER_KINDS.get(spec.kind.value)
        key = cat.get("setting") if cat else None
        if key:
            await settings_service.update_settings(session, {key: svc.endpoint})
            applied[key] = svc.endpoint
    return svc, applied


async def deploy_stream(session: AsyncSession, spec: DeploySpec, target: DeployTarget):
    """단계별 진행 이벤트를 yield 하는 스트리밍 배포(docker pull 레이어 진행 포함).

    이벤트(dict): {phase, status, detail?, layers_done?, layers_total?, slot?, service?, applied_settings?}
    phase: agent | pull | run | settings | verify | done | error
    """
    from app.deploy._agent import agent_request, agent_stream, resolve_host
    from app.deploy.docker_strategy import _BASE, _to_request, _to_service
    from app.deploy.models import ServiceKind
    from app.deploy.schemas import ManagedServiceOut
    from app.servermgr import service as sm

    yield {"phase": "agent", "status": "running", "detail": "에이전트 확인"}

    # docker 호스트 배포만 상세 스트리밍 — 그 외(systemd/k8s)는 일반 배포 후 done.
    if target.type != "agent_host" or (target.method or "docker") != "docker":
        svc, applied = await deploy(session, spec, target)
        yield {
            "phase": "done",
            "status": "done",
            "service": ManagedServiceOut.of(svc).model_dump(),
            "applied_settings": applied,
        }
        return

    host = await resolve_host(target.hostname)
    yield {"phase": "agent", "status": "done", "detail": f"{target.hostname} ({host.ip})"}

    kind = spec.kind.value
    # vlm — 컨테이너 기동 전에 모델을 볼륨에 준비(보유 검증 → 에이전트 설치 → 오프라인 서빙).
    if spec.kind == ServiceKind.vlm:
        from app.deploy.model_prep import prepare_vlm_model

        try:
            async for ev in prepare_vlm_model(spec, host):
                yield ev
        except DeployError as e:
            yield {"phase": "error", "status": "error", "detail": str(e)}
            return
    # 임베딩/리랭커 — 선택 모델 필수 설치(미보유=거부) 또는 미선택 시 보유분 pre-warm.
    elif kind in ("embedding", "reranker"):
        from app.deploy.model_prep import prepare_kind_models

        model_selected = bool((spec.env.get("MODEL_NAMES") or "").strip())
        try:
            async for ev in prepare_kind_models(spec, host):
                yield ev
        except DeployError as e:
            if model_selected:
                # 사용자가 명시 선택 — vlm 과 같은 필수 semantics(배포 거부).
                yield {"phase": "error", "status": "error", "detail": str(e)}
                return
            yield {"phase": "model", "status": "running", "detail": f"경고: 모델 사전 설치 건너뜀 — {e}"}

    n = spec.replicas if spec.kind == ServiceKind.worker else 1
    existing = await agent_request("GET", host.ip, _BASE)
    names = [c.get("name") for c in (existing or []) if c.get("name")]
    slots = sm.next_slots(sm.container_prefix(kind), names, n)
    req = _to_request(spec)

    last_container: dict | None = None
    for name in slots:
        payload = sm.build_container_spec(
            kind, name, req, arch=host.arch, gpu_count=host.gpu_count
        )
        async for ev in agent_stream(host.ip, "/api/v1/container/stream", payload):
            ev["slot"] = name
            if ev.get("phase") == "done":
                last_container = ev.get("container")
            elif ev.get("phase") == "error" or ev.get("status") == "error":
                # 단계 실패(run 등 status=error 포함) — 여기서 중단해 실패한 배포가
                # 전역 설정(server_url 등)을 덮어쓰지 않게 한다.
                yield ev
                return
            else:
                yield ev

    applied: dict[str, str] = {}
    to_apply: dict[str, str] = {}
    inj = sm.setting_injection(kind, host.ip, spec.host_port)
    if inj:
        to_apply[inj[0]] = inj[1]
    if kind == "vlm":
        # 선택한 카탈로그 모델의 served-model-name 을 전역 모델 설정에도 반영.
        to_apply.update(sm.vlm_setting_injection(spec.env))
    if spec.wire_settings and to_apply:
        yield {"phase": "settings", "status": "running", "detail": "설정 주입"}
        await settings_service.update_settings(session, to_apply)
        applied.update(to_apply)
        detail = ", ".join(f"{k} = {v}" for k, v in to_apply.items())
        yield {"phase": "settings", "status": "done", "detail": detail}

    svc = _to_service(last_container or {"name": slots[0], "state": "running", "kind": kind})
    svc.desired_replicas = svc.ready_replicas = len(slots)
    yield {"phase": "verify", "status": "done"}
    yield {
        "phase": "done",
        "status": "done",
        "service": ManagedServiceOut.of(svc).model_dump(),
        "applied_settings": applied,
    }


async def list_services(target: DeployTarget) -> list[ManagedService]:
    return await get_strategy(target).list(target)


async def enrich_workers(
    session: AsyncSession, services: list[ManagedService]
) -> list[ManagedService]:
    """worker kind 서비스에 워커 레지스트리(argus_workers) 정보를 교차참조로 붙인다.

    매칭 키(우선순위): ① systemd MainPID == 워커 pid(같은 호스트 다중 워커도 정밀 구분)
    ② 컨테이너 short id(=ManagedInstance.id) == 워커 hostname(컨테이너 hostname)
    ③ instance.node(대상 호스트명) == 워커 hostname(systemd 폴백 — 단일 워커 가정).
    매칭된 워커는 소진해 중복 부착을 막고, 레지스트리의 version/started_at 으로
    행의 빈 필드를 보충한다(워커는 이미지 태그·엔드포인트가 없어 이쪽이 유일한 출처).
    """
    if not any(s.kind == "worker" for s in services):
        return services
    from app.workers.service import list_workers

    remaining = list(await list_workers(session))

    def take(pred):
        for i, w in enumerate(remaining):
            if pred(w):
                return remaining.pop(i)
        return None

    for svc in services:
        if svc.kind != "worker":
            continue
        for inst in svc.instances:
            w = (
                (take(lambda w: w.pid == inst.pid) if inst.pid else None)
                or take(lambda w: w.hostname in (inst.id, inst.id[:12]))
                or (take(lambda w: w.hostname == inst.node) if inst.node else None)
            )
            if w:
                svc.worker_alive = w.alive
                svc.worker_status = w.status
                svc.worker_current_job = w.current_job_id
                svc.worker_processed_total = w.processed_total
                svc.worker_mode = w.mode
                svc.version = svc.version or w.version
                if not svc.started_at and w.started_at:
                    svc.started_at = w.started_at.isoformat()
                break
    return services


# --- 전체 서비스 집계 (에이전트 > 서비스 관리 탭 — design/agent-services-overview.md §3) ---

OVERVIEW_TIMEOUT_S = 5.0


async def _agent_hosts(session: AsyncSession) -> list[tuple[str, str]]:
    """집계 대상 에이전트 호스트 — REGISTERED(조회) + DISCONNECTED(실패 행 표시용)."""
    from sqlalchemy import select

    from app.agent.models import ArgusAgent

    rows = await session.execute(
        select(ArgusAgent.hostname, ArgusAgent.status)
        .where(ArgusAgent.status.in_(["REGISTERED", "DISCONNECTED"]))
        .order_by(ArgusAgent.hostname)
    )
    return [(h, s) for h, s in rows.all()]


async def collect_overview(
    session: AsyncSession, hosts: list[tuple[str, str]], clusters: list
) -> list[dict]:
    """호스트×{docker,systemd} + 클러스터를 병렬 조회해 대상별로 병합.

    부분 실패는 error 로 남긴다(조용히 빠지면 "서비스 없음"과 구분 불가) — 항상 성공 응답.
    반환: [{"target": DeployTarget, "services": [ManagedService…], "error": str|None}…]
    """
    import asyncio

    async def probe(target: DeployTarget) -> dict:
        try:
            services = await asyncio.wait_for(list_services(target), OVERVIEW_TIMEOUT_S)
            return {"target": target, "services": services, "error": None}
        except TimeoutError:
            return {"target": target, "services": [],
                    "error": f"조회 시간 초과({OVERVIEW_TIMEOUT_S:g}s)"}
        except DeployError as e:
            return {"target": target, "services": [], "error": str(e)}
        except Exception as e:  # 대상 하나의 실패가 전체 집계를 무너뜨리지 않게
            return {"target": target, "services": [], "error": str(e)}

    entries: list[dict] = []
    probes = []
    for hostname, status_ in hosts:
        if status_ == "DISCONNECTED":
            # 하트비트 끊김 — 네트워크 시도 없이 즉시 실패 행으로.
            entries.append({
                "target": DeployTarget(type="agent_host", hostname=hostname),
                "services": [], "error": "에이전트 연결 끊김(하트비트 없음)",
            })
            continue
        for method in ("docker", "systemd"):
            probes.append(probe(DeployTarget(type="agent_host", hostname=hostname, method=method)))
    for c in clusters:
        probes.append(probe(DeployTarget(
            type="k8s", cluster_id=c.cluster_id, namespace=c.default_namespace
        )))

    entries.extend(await asyncio.gather(*probes))
    entries.sort(key=lambda e: (e["target"].type, e["target"].hostname or e["target"].cluster_id or "",
                                e["target"].method or ""))

    # 워커 레지스트리 교차참조는 전 대상 병합 후 1회(제자리 갱신).
    await enrich_workers(session, [s for e in entries for s in e["services"]])
    return entries


# settings 폴링(server-stats)의 kind 표기 → 배포 kind 표기.
_EXTERNAL_KIND_MAP = {"rerank": "reranker"}


def _external_entry(kind: str, url: str, ok: bool, error: str | None,
                    source: str, stats: dict | None) -> dict:
    """ExtServerStat(+stats) → 외부(수동) 행 — 화면 표시 필드만 평탄화."""
    st = stats or {}
    sysd = st.get("system") or {}
    return {
        "kind": _EXTERNAL_KIND_MAP.get(kind, kind), "url": url, "ok": ok,
        "error": error, "source": source,
        "version": st.get("version"), "model": st.get("model"), "device": st.get("device"),
        "uptime_seconds": st.get("uptime_seconds"),
        "cpu_percent": sysd.get("cpu_percent"), "mem_percent": sysd.get("mem_percent"),
    }


def _stats_summary(stats: dict | None) -> dict | None:
    """heartbeat /stats 스냅샷 → 화면 표시용 요약(2행 상세 — 모델·디바이스·GPU·업타임)."""
    if not stats:
        return None
    sysd = stats.get("system") or {}
    models = stats.get("models") or {}
    return {
        "model": stats.get("model"),
        "models_loaded": list(models.get("loaded") or []),
        "device": stats.get("device"),
        "uptime_seconds": stats.get("uptime_seconds"),
        "server_version": stats.get("version"),
        "cpu_percent": sysd.get("cpu_percent"),
        "mem_percent": sysd.get("mem_percent"),
        "gpu": [
            {"name": g.get("name"), "utilization_percent": g.get("utilization_percent"),
             "mem_used_bytes": g.get("mem_used_bytes"), "mem_total_bytes": g.get("mem_total_bytes")}
            for g in (stats.get("gpu") or []) if isinstance(g, dict)
        ],
    }


def _served_model_from(command: list[str]) -> str | None:
    """컨테이너 Cmd 에서 --served-model-name 추출(vlm — heartbeat 없는 kind 의 모델 표시)."""
    for i, arg in enumerate(command):
        if arg == "--served-model-name" and i + 1 < len(command):
            return command[i + 1]
        if arg.startswith("--served-model-name="):
            return arg.split("=", 1)[1]
    return None


async def collect_probes() -> list:
    """전역 설정 URL 프로브 — embedding/rerank/detection(/stats) + vlm(/models·/metrics) +
    hwp_render(/stats). 서비스 탭(server-stats)과 동일 소스를 overview 병합에 재사용한다."""
    import asyncio

    from app.core.config import settings
    from app.embedding.router import _fetch_hwp_stat, _fetch_stat, _fetch_vlm_stat

    targets = [
        ("embedding", settings.embedding_server_url, settings.embedding_api_key,
         settings.embedding_auth_header, settings.embedding_auth_scheme),
        ("rerank", settings.rerank_server_url, settings.rerank_api_key,
         settings.rerank_auth_header, settings.rerank_auth_scheme),
    ]
    if settings.detection_enabled:
        targets.append(
            ("detection", settings.detection_server_url, settings.detection_api_key,
             settings.detection_auth_header, settings.detection_auth_scheme)
        )
    results = await asyncio.gather(
        *(_fetch_stat(*t) for t in targets), _fetch_vlm_stat(), _fetch_hwp_stat()
    )
    return [r for r in results if r is not None]


def merge_heartbeat_stats(entries: list[dict], observations: list) -> set[str]:
    """관측(heartbeat 레지스트리 + 설정 프로브)을 관리형 행에 병합.

    endpoint netloc 일치 → stats 요약 부착(heartbeat 우선 — observations 순서).
    vlm 처럼 heartbeat 가 없는 kind 는 프로브(/metrics)가 device 를, 컨테이너 Cmd 가
    모델명을 보충한다. 반환: 관리형 endpoint netloc 집합(외부 목록 중복 제거용)."""
    from urllib.parse import urlparse

    by_netloc: dict[str, object] = {}
    for r in observations:
        n = urlparse(getattr(r, "url", "") or "").netloc
        if n and n not in by_netloc:
            by_netloc[n] = r
    managed_netlocs: set[str] = set()
    for e in entries:
        for s in e["services"]:
            if s.endpoint:
                n = urlparse(s.endpoint).netloc
                managed_netlocs.add(n)
                r = by_netloc.get(n)
                if r is not None and getattr(r, "stats", None):
                    s.stats = _stats_summary(r.stats)
            if s.kind == "vlm" and not (s.stats or {}).get("model"):
                m = _served_model_from(s.command)
                if m:
                    s.stats = {**(s.stats or {}), "model": m}
    return managed_netlocs


def external_services(
    managed_netlocs: set[str], registered: list, probes: list
) -> list[dict]:
    """관리 외(수동 배포) 서비스 수집 — 자기 등록(heartbeat) 레지스트리 + 전역 설정 URL 프로브.

    에이전트 관리분과 host:port(netloc) 가 겹치는 항목은 제외한다(같은 서비스의 이중 표시
    방지 — 관리형 행에 stats 로 병합됨). 설계 design/agent-services-overview.md §5."""
    from urllib.parse import urlparse

    out: list[dict] = []
    seen = set(managed_netlocs)

    # 1) 자기 등록 레지스트리(rag_ext_servers) — 배포 방식 무관 heartbeat 보고분.
    for s in registered:
        netloc = urlparse(s.url or "").netloc
        if netloc and netloc in seen:
            continue
        if netloc:
            seen.add(netloc)
        out.append(_external_entry(s.kind, s.url, s.ok, s.error, "heartbeat", s.stats))

    # 2) 전역 설정 URL 프로브 — heartbeat 도 없는 완전 수동 배포의 최소 가시성.
    for s in probes:
        netloc = urlparse(s.url or "").netloc
        if not netloc or netloc in seen:  # URL 미설정 또는 이미 표시됨
            continue
        seen.add(netloc)
        out.append(_external_entry(s.kind, s.url, s.ok, s.error, "settings", s.stats))
    return out


async def worker_external_entries(session: AsyncSession, entries: list[dict]) -> list[dict]:
    """워커 레지스트리(자기 등록)의 standalone 워커 중 관리형 행과 매칭 안 되는 것 → 외부 행.

    관리 규약 밖에서 직접 구동한 워커(예: 체크아웃 systemd/nohup)가 잡 모니터링에는
    보이는데 서비스 관리에는 안 보이는 불일치를 해소한다. 매칭 키는 enrich_workers 와
    동일(docker: 컨테이너 short id == 워커 hostname) + systemd 관리 워커는 호스트명.
    in_process 워커(API 내장)는 별도 배포물이 아니므로 제외."""
    from datetime import datetime, timezone

    from app.workers.service import list_workers

    matched_hosts: set[str] = set()   # docker 컨테이너 id(=워커 hostname) / pid 없는 systemd 폴백
    matched_pids: set[int] = set()    # systemd MainPID — 같은 호스트 다중 워커도 정밀 제외
    for e in entries:
        for s in e["services"]:
            if s.kind != "worker":
                continue
            for inst in s.instances:
                matched_hosts.add(inst.id)
                matched_hosts.add(inst.id[:12])
                if inst.pid:
                    matched_pids.add(inst.pid)
                elif s.runtime == "systemd" and e["target"].hostname:
                    matched_hosts.add(e["target"].hostname)

    now = datetime.now(timezone.utc)
    out: list[dict] = []
    for w in await list_workers(session):
        if (not w.hostname or w.hostname in matched_hosts
                or (w.pid and w.pid in matched_pids) or w.mode == "in_process"):
            continue
        started = w.started_at
        if started is not None and started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        metrics = w.metrics or {}
        detail_bits = [b for b in (
            w.mode, w.status,
            f"처리 {w.processed_total}건" if w.processed_total is not None else None,
            f"잡 {w.current_job_id}" if w.current_job_id else None,
        ) if b]
        out.append({
            "kind": "worker",
            # 워커는 접속 URL 이 없다 — 표시·행 키 용도의 의사 URL(host 파싱 호환).
            "url": f"worker://{w.hostname}/pid-{w.pid or 0}",
            "ok": bool(w.alive),
            "error": None if w.alive else (
                f"하트비트 끊김({round(w.heartbeat_age_seconds)}s 전)"
                if w.heartbeat_age_seconds is not None else "하트비트 없음"
            ),
            "source": "worker",
            "version": w.version, "model": None, "device": None,
            "uptime_seconds": (now - started).total_seconds() if started else None,
            "cpu_percent": metrics.get("cpu_percent"), "mem_percent": metrics.get("mem_percent"),
            "detail": " · ".join(detail_bits) or None,
        })
    return out


async def overview(session: AsyncSession) -> dict:
    """등록 서버×{docker,systemd} + 클러스터 + 외부(수동) 서비스의 배포 집계."""
    from app.deploy import cluster_service
    from app.extservers.service import list_registered

    hosts = await _agent_hosts(session)
    clusters = await cluster_service.list_clusters(session)
    entries = await collect_overview(session, hosts, clusters)

    registered = await list_registered(session)
    probes = await collect_probes()
    # heartbeat 가 프로브보다 우선(순서) — 같은 netloc 이면 먼저 온 관측의 stats 를 쓴다.
    managed_netlocs = merge_heartbeat_stats(entries, list(registered) + list(probes))
    external = external_services(managed_netlocs, registered, probes)
    external += await worker_external_entries(session, entries)
    return {"targets": entries, "external": external}


# service_endpoints TTL 캐시 — overview(에이전트 팬아웃, 수 초)를 픽커마다 반복하지 않도록.
# 만료 후 첫 요청이 재수집하고, 동시 요청은 락으로 1회 수집에 합류한다. refresh=True 로 강제 갱신.
ENDPOINTS_CACHE_TTL_S = 60.0
_endpoints_cache: dict = {"ts": 0.0, "rows": None}
_endpoints_lock: asyncio.Lock | None = None


async def service_endpoints(
    session: AsyncSession, kind: str | None = None, refresh: bool = False
) -> list[dict]:
    """설정 픽커용 — 실행 중 서비스의 엔드포인트 목록(관리형+수동, netloc 중복 제거).

    설정 화면·라우팅 정책·파이프라인 빌더가 서버 URL 을 손으로 치는 대신 배포된
    서비스에서 고르게 한다. overview(에이전트 팬아웃) 결과를 TTL 캐시(60s)로 재사용한다.
    """
    global _endpoints_lock
    if _endpoints_lock is None:
        _endpoints_lock = asyncio.Lock()
    now = time.monotonic()
    if not refresh and _endpoints_cache["rows"] is not None \
            and now - _endpoints_cache["ts"] <= ENDPOINTS_CACHE_TTL_S:
        rows = _endpoints_cache["rows"]
    else:
        async with _endpoints_lock:
            # 락 대기 중 다른 요청이 채웠으면 재사용(중복 팬아웃 방지).
            now = time.monotonic()
            if refresh or _endpoints_cache["rows"] is None \
                    or now - _endpoints_cache["ts"] > ENDPOINTS_CACHE_TTL_S:
                _endpoints_cache["rows"] = await _collect_service_endpoints(session)
                _endpoints_cache["ts"] = time.monotonic()
            rows = _endpoints_cache["rows"]
    return [r for r in rows if not kind or r["kind"] == kind]


async def _collect_service_endpoints(session: AsyncSession) -> list[dict]:
    """전체 kind 의 엔드포인트 수집(캐시 미스 시 1회) — overview 재사용."""
    from urllib.parse import urlparse

    def _netloc(u: str) -> str:
        try:
            return (urlparse(u).netloc or u).lower()
        except ValueError:
            return u.lower()

    result = await overview(session)
    out: list[dict] = []
    seen: set[str] = set()
    for e in result["targets"]:
        t = e["target"]
        for s in e["services"]:
            if s.state != "running" or not s.endpoint:
                continue
            key = _netloc(s.endpoint)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "kind": s.kind, "name": s.name, "url": s.endpoint,
                "model": (s.stats or {}).get("model"),
                "runtime": s.runtime,
                "location": t.hostname or t.cluster_id or "",
            })
    for x in result["external"]:
        url = x.get("url") or ""
        if not x.get("ok") or not url.startswith("http"):
            continue
        key = _netloc(url)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "kind": x.get("kind"), "name": f"{x.get('kind')} (수동)", "url": url,
            "model": x.get("model"), "runtime": "manual", "location": _netloc(url),
        })
    out.sort(key=lambda r: (r["kind"] or "", r["name"] or ""))
    return out


async def status(target: DeployTarget, name: str) -> ManagedService:
    return await get_strategy(target).status(target, name)


async def action(target: DeployTarget, name: str, action_name: str) -> ManagedService:
    return await get_strategy(target).action(target, name, action_name)


async def scale(target: DeployTarget, name: str, replicas: int) -> ManagedService:
    return await get_strategy(target).scale(target, name, replicas)


async def remove(target: DeployTarget, name: str) -> None:
    await get_strategy(target).remove(target, name)


async def logs(target: DeployTarget, name: str, *, tail: int = 200) -> str:
    return await get_strategy(target).logs(target, name, tail=tail)
