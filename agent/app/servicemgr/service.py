"""Service management service - systemd unit lifecycle.

servicemgr가 관리하는 unit 은 ``MANAGED_PREFIX`` 로 시작하는 것만 허용한다.
unit 파일은 ``SYSTEMD_DIR`` 아래에 ``<name>.service`` 로 작성되며, ``kind``/``version``
메타데이터는 ``# X-Argus-*`` 주석으로 보존하여 heartbeat 인벤토리에서 재파싱한다.
"""

import asyncio
import logging
import re
from pathlib import Path

from app.servicemgr.schemas import (
    MANAGED_PREFIX,
    OperationResult,
    ServiceSpec,
    ServiceStatus,
)

logger = logging.getLogger(__name__)

# systemd unit 디렉토리. 테스트에서 tmp_path 로 patch 한다.
SYSTEMD_DIR = Path("/etc/systemd/system")

# unit 이름 허용 문자(systemd 규칙의 보수적 부분집합) — 명령 인젝션/경로탈출 방지.
_NAME_RE = re.compile(r"^[A-Za-z0-9_.@-]+$")

# systemctl show 에서 읽을 속성.
_SHOW_PROPS = (
    "LoadState",
    "ActiveState",
    "SubState",
    "UnitFileState",
    "MainPID",
    "ExecMainStatus",
    "MemoryCurrent",
    "ActiveEnterTimestamp",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _run(cmd: str) -> tuple[int, str, str]:
    """Run a shell command and return (exit_code, stdout, stderr)."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
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
    """Raise ValueError if name is not a safe managed unit name."""
    if not name.startswith(MANAGED_PREFIX):
        raise ValueError(f"managed unit must start with '{MANAGED_PREFIX}'")
    if not _NAME_RE.match(name):
        raise ValueError(f"invalid unit name: {name!r}")


def _unit_path(name: str) -> Path:
    return SYSTEMD_DIR / f"{name}.service"


def unit_exists(name: str) -> bool:
    """Return True if the unit file exists on disk (no subprocess)."""
    return _unit_path(name).is_file()


def _check_no_newline(field: str, value: str) -> None:
    """Reject control characters that could inject extra unit directives."""
    if "\n" in value or "\r" in value:
        raise ValueError(f"{field} must not contain newlines")


def render_unit(spec: ServiceSpec) -> str:
    """Render a systemd unit file from a ServiceSpec (pure, no side effects)."""
    validate_name(spec.name)
    _check_no_newline("exec_start", spec.exec_start)
    _check_no_newline("description", spec.description)
    for k, v in spec.environment.items():
        if not _NAME_RE.match(k):
            raise ValueError(f"invalid environment key: {k!r}")
        _check_no_newline(f"environment[{k}]", v)

    lines: list[str] = [
        f"# {_unit_path(spec.name)}",
        "# Managed by Argus RAG Studio Agent (servicemgr) - DO NOT EDIT BY HAND",
        f"# X-Argus-Kind={spec.kind}",
    ]
    if spec.version:
        lines.append(f"# X-Argus-Version={spec.version}")

    lines += ["", "[Unit]", f"Description={spec.description}"]
    if spec.after:
        lines.append(f"After={' '.join(spec.after)}")

    lines += ["", "[Service]", "Type=simple"]
    if spec.user:
        lines.append(f"User={spec.user}")
    if spec.group:
        lines.append(f"Group={spec.group}")
    if spec.working_directory:
        lines.append(f"WorkingDirectory={spec.working_directory}")
    for k, v in spec.environment.items():
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'Environment="{k}={escaped}"')
    lines.append(f"ExecStart={spec.exec_start}")
    lines.append(f"Restart={spec.restart}")
    lines.append(f"RestartSec={spec.restart_sec}")
    if spec.limit_nofile is not None:
        lines.append(f"LimitNOFILE={spec.limit_nofile}")

    lines += ["", "[Install]", f"WantedBy={spec.wanted_by}", ""]
    return "\n".join(lines)


def _parse_show(output: str) -> dict[str, str]:
    """Parse `systemctl show` KEY=VALUE output into a dict."""
    result: dict[str, str] = {}
    for line in output.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def _read_metadata(name: str) -> tuple[str | None, str | None]:
    """Read kind/version from the unit file's X-Argus- comments."""
    path = _unit_path(name)
    if not path.is_file():
        return None, None
    kind: str | None = None
    version: str | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("# X-Argus-Kind="):
            kind = line.split("=", 1)[1].strip()
        elif line.startswith("# X-Argus-Version="):
            version = line.split("=", 1)[1].strip()
    return kind, version


def _int_or_none(value: str | None) -> int | None:
    """Parse a systemctl numeric field; treat 0 / '[not set]' / non-numeric as None."""
    if not value or not value.lstrip("-").isdigit():
        return None
    n = int(value)
    return n if n > 0 else None


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


async def status(name: str) -> ServiceStatus:
    """Query a unit's current status via `systemctl show`."""
    validate_name(name)
    exists = unit_exists(name)
    props = ",".join(_SHOW_PROPS)
    exit_code, stdout, stderr = await _run(f"systemctl show {name} --property={props}")
    if exit_code != 0:
        return ServiceStatus(name=name, exists=exists, message=stderr or "systemctl show failed")

    show = _parse_show(stdout)
    kind, version = _read_metadata(name)
    unit_file_state = show.get("UnitFileState") or None
    enabled: bool | None
    if unit_file_state in ("enabled", "enabled-runtime"):
        enabled = True
    elif unit_file_state in ("disabled", "static", "masked"):
        enabled = False
    else:
        enabled = None

    return ServiceStatus(
        name=name,
        exists=exists,
        load_state=show.get("LoadState") or None,
        active_state=show.get("ActiveState") or None,
        sub_state=show.get("SubState") or None,
        enabled=enabled,
        pid=_int_or_none(show.get("MainPID")),
        memory_bytes=_int_or_none(show.get("MemoryCurrent")),
        since=show.get("ActiveEnterTimestamp") or None,
        exit_code=(
            int(show["ExecMainStatus"])
            if show.get("ExecMainStatus", "").lstrip("-").isdigit()
            else None
        ),
        kind=kind,
        version=version,
        message="",
    )


async def list_managed() -> list[ServiceStatus]:
    """List all servicemgr-managed units (by file glob)."""
    if not SYSTEMD_DIR.is_dir():
        return []
    names = sorted(
        p.stem for p in SYSTEMD_DIR.glob(f"{MANAGED_PREFIX}*.service") if p.is_file()
    )
    return [await status(name) for name in names]


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


async def create_or_update(spec: ServiceSpec) -> ServiceStatus:
    """Write the unit file, daemon-reload, then optionally enable and start."""
    validate_name(spec.name)
    content = render_unit(spec)

    SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)
    _unit_path(spec.name).write_text(content, encoding="utf-8")
    logger.info("Wrote unit file: %s", _unit_path(spec.name))

    await _run("systemctl daemon-reload")
    if spec.enable:
        await _run(f"systemctl enable {spec.name}")
    if spec.start:
        # restart 는 멱등(정지 상태면 시작, 동작 중이면 재시작).
        await _run(f"systemctl restart {spec.name}")

    return await status(spec.name)


async def start(name: str) -> ServiceStatus:
    """Start a unit."""
    validate_name(name)
    exit_code, _, stderr = await _run(f"systemctl start {name}")
    st = await status(name)
    if exit_code != 0:
        st.message = stderr or "systemctl start failed"
    return st


async def stop(name: str) -> ServiceStatus:
    """Stop a unit."""
    validate_name(name)
    exit_code, _, stderr = await _run(f"systemctl stop {name}")
    st = await status(name)
    if exit_code != 0:
        st.message = stderr or "systemctl stop failed"
    return st


async def restart(name: str) -> ServiceStatus:
    """Restart a unit."""
    validate_name(name)
    exit_code, _, stderr = await _run(f"systemctl restart {name}")
    st = await status(name)
    if exit_code != 0:
        st.message = stderr or "systemctl restart failed"
    return st


async def set_enabled(name: str, enabled: bool) -> OperationResult:
    """Enable or disable a unit on boot."""
    validate_name(name)
    action = "enable" if enabled else "disable"
    exit_code, _, stderr = await _run(f"systemctl {action} {name}")
    if exit_code != 0:
        return OperationResult(success=False, message=stderr or f"systemctl {action} failed")
    return OperationResult(success=True, message=f"{name} {action}d")


async def remove(name: str) -> OperationResult:
    """Stop, disable, remove the unit file, and daemon-reload."""
    validate_name(name)
    path = _unit_path(name)
    if not path.is_file():
        return OperationResult(success=False, message=f"unit not found: {name}")

    await _run(f"systemctl stop {name}")
    await _run(f"systemctl disable {name}")
    try:
        path.unlink()
    except OSError as e:
        return OperationResult(success=False, message=str(e))
    await _run("systemctl daemon-reload")
    logger.info("Removed unit file: %s", path)
    return OperationResult(success=True, message=f"{name} removed")
