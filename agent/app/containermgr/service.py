"""Container management service - Docker/Podman lifecycle.

containermgr 가 관리하는 컨테이너는 ``MANAGED_PREFIX`` 로 시작하는 이름만 허용한다.
``kind``/``version`` 메타데이터는 컨테이너 라벨(``argus.kind``/``argus.version``)로 보존해
heartbeat 인벤토리/상태 조회에서 재사용한다. 모든 호출은 셸이 아닌 argv(exec)로 실행해
인젝션을 차단한다.
"""

import asyncio
import logging
import re
import shutil

from app.containermgr.schemas import (
    MANAGED_PREFIX,
    ContainerSpec,
    ContainerStatus,
    OperationResult,
)

logger = logging.getLogger(__name__)

# 컨테이너 런타임 — docker 우선, 없으면 podman. 테스트에서 patch 가능.
CONTAINER_CMD = shutil.which("docker") or shutil.which("podman") or "docker"

# 이름 허용 문자(보수적) — 인젝션/이상문자 방지.
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# inspect 필드 구분자(값에 탭이 없다는 가정). 마지막 두 필드는 JSON(탭 없음).
_FMT = (
    "{{.Id}}\t{{.Config.Image}}\t{{.State.Status}}\t{{.State.ExitCode}}\t"
    '{{.State.StartedAt}}\t{{index .Config.Labels "argus.kind"}}\t'
    '{{index .Config.Labels "argus.version"}}\t{{.RestartCount}}\t'
    "{{json .NetworkSettings.Ports}}\t{{json .Config.Cmd}}"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _run(args: list[str]) -> tuple[int, str, str]:
    """Run `<runtime> <args...>` via exec and return (exit_code, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        CONTAINER_CMD,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout.decode(errors="replace").strip(),
        stderr.decode(errors="replace").strip(),
    )


def validate_name(name: str) -> None:
    """Raise ValueError if name is not a safe managed container name."""
    if not name.startswith(MANAGED_PREFIX):
        raise ValueError(f"managed container must start with '{MANAGED_PREFIX}'")
    if not _NAME_RE.match(name):
        raise ValueError(f"invalid container name: {name!r}")


def render_run_args(spec: ContainerSpec, action: str = "run") -> list[str]:
    """Render `docker run|create ...` argv from a ContainerSpec (pure, no side effects)."""
    validate_name(spec.name)
    if action not in ("run", "create"):
        raise ValueError(f"invalid action: {action}")

    args: list[str] = [action]
    if action == "run":
        args.append("-d")
    args += ["--name", spec.name, "--restart", spec.restart]
    args += ["--label", f"argus.kind={spec.kind}"]
    if spec.version:
        args += ["--label", f"argus.version={spec.version}"]
    for k, v in spec.labels.items():
        args += ["--label", f"{k}={v}"]
    for k, v in spec.environment.items():
        if not _ENV_KEY_RE.match(k):
            raise ValueError(f"invalid environment key: {k!r}")
        args += ["-e", f"{k}={v}"]
    for p in spec.ports:
        args += ["-p", p]
    for vol in spec.volumes:
        args += ["-v", vol]
    if spec.gpus:
        args += ["--gpus", spec.gpus]
    if spec.ipc:
        args += ["--ipc", spec.ipc]
    if spec.network:
        args += ["--network", spec.network]
    for host in spec.extra_hosts:
        args += ["--add-host", host]
    args.append(spec.image)
    args += spec.command
    return args


def _clean(value: str) -> str | None:
    """Normalize an inspect field ('<no value>'/empty → None)."""
    value = value.strip()
    if not value or value == "<no value>":
        return None
    return value


def _parse_inspect(line: str) -> dict:
    """Parse a tab-delimited inspect line into fields."""
    parts = line.split("\t")
    while len(parts) < 10:
        parts.append("")
    return {
        "id": _clean(parts[0]),
        "image": _clean(parts[1]),
        "state": _clean(parts[2]),
        "exit_code": parts[3].strip(),
        "started_at": _clean(parts[4]),
        "kind": _clean(parts[5]),
        "version": _clean(parts[6]),
        "restart_count": parts[7].strip(),
        "ports_json": parts[8].strip(),
        "cmd_json": parts[9].strip(),
    }


def _parse_cmd(raw: str) -> list[str]:
    """`{{json .Config.Cmd}}` → argv 목록(없으면 빈 목록)."""
    import json as _json

    try:
        cmd = _json.loads(raw or "null")
    except ValueError:
        return []
    return [str(a) for a in cmd] if isinstance(cmd, list) else []


def _parse_ports(raw: str) -> list[str]:
    """`{{json .NetworkSettings.Ports}}` → ["host:container", …] (호스트 미노출 포트 제외).

    예: {"8080/tcp":[{"HostIp":"0.0.0.0","HostPort":"8090"}, …]} → ["8090:8080"]"""
    import json as _json

    try:
        mapping = _json.loads(raw or "null")
    except ValueError:
        return []
    if not isinstance(mapping, dict):
        return []
    out: set[str] = set()
    for cport, binds in mapping.items():
        container = cport.split("/")[0]
        for b in binds or []:
            host = (b or {}).get("HostPort")
            if host:
                out.add(f"{host}:{container}")
    return sorted(out)


def _pct(value: str) -> float | None:
    """'12.34%' → 12.34. 비숫자/빈값은 None."""
    value = value.strip().rstrip("%")
    try:
        return float(value)
    except ValueError:
        return None


async def _collect_stats() -> dict[str, dict]:
    """`docker stats --no-stream` 로 실행 중 컨테이너의 CPU%/MEM% 를 한 번에 수집(이름→값)."""
    rc, out, _ = await _run(
        ["stats", "--no-stream", "--no-trunc", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemPerc}}"]
    )
    if rc != 0 or not out:
        return {}
    result: dict[str, dict] = {}
    for line in out.splitlines():
        p = line.split("\t")
        if len(p) < 3:
            continue
        result[p[0].strip()] = {"cpu_percent": _pct(p[1]), "mem_percent": _pct(p[2])}
    return result


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


async def status(name: str) -> ContainerStatus:
    """Query a container's status via `inspect`."""
    validate_name(name)
    exit_code, stdout, stderr = await _run(["inspect", name, "--format", _FMT])
    if exit_code != 0:
        # 존재하지 않으면 inspect 가 실패한다.
        return ContainerStatus(name=name, exists=False, message=stderr or "not found")

    f = _parse_inspect(stdout)
    ec = int(f["exit_code"]) if f["exit_code"].lstrip("-").isdigit() else None
    rc = int(f["restart_count"]) if f["restart_count"].isdigit() else None
    return ContainerStatus(
        name=name,
        exists=True,
        id=(f["id"][:12] if f["id"] else None),
        image=f["image"],
        state=f["state"],
        exit_code=ec,
        started_at=f["started_at"],
        kind=f["kind"],
        version=f["version"],
        restart_count=rc,
        ports=_parse_ports(f["ports_json"]),
        command=_parse_cmd(f["cmd_json"]),
        message="",
    )


async def list_managed() -> list[ContainerStatus]:
    """List all containermgr-managed containers (name prefix filter) + CPU/MEM(stats)."""
    exit_code, stdout, _ = await _run(
        ["ps", "-a", "--filter", f"name={MANAGED_PREFIX}", "--format", "{{.Names}}"]
    )
    if exit_code != 0 or not stdout:
        return []
    names = sorted(n for n in stdout.splitlines() if n.startswith(MANAGED_PREFIX))
    stats = await _collect_stats()  # 실행 중 컨테이너만 포함
    out: list[ContainerStatus] = []
    for name in names:
        st = await status(name)
        s = stats.get(name)
        if s:
            st.cpu_percent = s["cpu_percent"]
            st.mem_percent = s["mem_percent"]
        out.append(st)
    return out


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


async def create_or_run(spec: ContainerSpec) -> ContainerStatus:
    """Pull(optional), remove any same-named container, then run/create."""
    validate_name(spec.name)
    action = "run" if spec.start else "create"
    args = render_run_args(spec, action=action)  # 검증 먼저(잘못된 spec 은 여기서 실패)

    if spec.pull:
        rc, _, err = await _run(["pull", spec.image])
        if rc != 0:
            logger.warning("Image pull failed (continuing): %s — %s", spec.image, err)

    # 동일 이름 컨테이너가 있으면 제거(멱등 재배포).
    await _run(["rm", "-f", spec.name])

    rc, _, err = await _run(args)
    if rc != 0:
        return ContainerStatus(name=spec.name, exists=False, message=err or "run failed")
    logger.info("Container %s: %s %s", action, spec.name, spec.image)
    return await status(spec.name)


async def start(name: str) -> ContainerStatus:
    """Start a container."""
    validate_name(name)
    rc, _, err = await _run(["start", name])
    st = await status(name)
    if rc != 0:
        st.message = err or "start failed"
    return st


async def stop(name: str) -> ContainerStatus:
    """Stop a container."""
    validate_name(name)
    rc, _, err = await _run(["stop", name])
    st = await status(name)
    if rc != 0:
        st.message = err or "stop failed"
    return st


async def restart(name: str) -> ContainerStatus:
    """Restart a container."""
    validate_name(name)
    rc, _, err = await _run(["restart", name])
    st = await status(name)
    if rc != 0:
        st.message = err or "restart failed"
    return st


async def remove(name: str) -> OperationResult:
    """Stop and remove a container."""
    validate_name(name)
    rc, _, err = await _run(["rm", "-f", name])
    if rc != 0:
        return OperationResult(success=False, message=err or "remove failed")
    logger.info("Removed container: %s", name)
    return OperationResult(success=True, message=f"{name} removed")


async def logs(name: str, tail: int = 200) -> str:
    """Return the last `tail` lines of a container's logs."""
    validate_name(name)
    rc, stdout, stderr = await _run(["logs", "--tail", str(tail), name])
    if rc != 0:
        return stderr or "logs unavailable"
    # docker 는 로그를 stderr 로도 내보내므로 둘을 합친다.
    return "\n".join(s for s in (stdout, stderr) if s)


# ---------------------------------------------------------------------------
# 스트리밍 배포 — docker pull 레이어 진행 + run 결과를 이벤트로 yield (NDJSON 소스)
# ---------------------------------------------------------------------------

_LAYER_RE = re.compile(r"^([0-9a-f]{12,}):\s*(.+)$")


async def _pull_stream(image: str):
    """`docker pull` stdout 을 줄 단위로 파싱해 레이어 진행 이벤트를 yield. pull 실패는 비치명적."""
    yield {"phase": "pull", "status": "running", "detail": f"이미지 받는 중: {image}",
           "layers_done": 0, "layers_total": 0}
    proc = await asyncio.create_subprocess_exec(
        CONTAINER_CMD, "pull", image,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    layers: set[str] = set()
    done: set[str] = set()
    assert proc.stdout is not None
    async for raw in proc.stdout:
        m = _LAYER_RE.match(raw.decode(errors="replace").strip())
        if not m:
            continue
        lid, msg = m.group(1), m.group(2)
        layers.add(lid)
        if "Pull complete" in msg or "Already exists" in msg:
            done.add(lid)
            yield {"phase": "pull", "status": "running",
                   "layers_done": len(done), "layers_total": len(layers)}
    await proc.wait()
    if proc.returncode != 0:
        yield {"phase": "pull", "status": "done", "detail": "pull 실패 — 로컬 이미지 사용"}
    else:
        yield {"phase": "pull", "status": "done",
               "layers_done": len(done), "layers_total": max(len(layers), len(done))}


async def create_or_run_stream(spec: ContainerSpec):
    """create_or_run 의 스트리밍 버전 — pull 레이어 진행 + run 결과를 이벤트로 yield."""
    validate_name(spec.name)
    action = "run" if spec.start else "create"
    args = render_run_args(spec, action=action)  # 검증 먼저

    if spec.pull:
        async for ev in _pull_stream(spec.image):
            yield ev

    await _run(["rm", "-f", spec.name])  # 동일 이름 제거(멱등)
    rc, _, err = await _run(args)
    if rc != 0:
        yield {"phase": "run", "status": "error", "detail": err or "run failed"}
        return
    st = await status(spec.name)
    yield {"phase": "run", "status": "done"}
    yield {"phase": "done", "status": "done", "container": st.model_dump()}
