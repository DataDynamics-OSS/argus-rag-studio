"""Process management service."""

import logging
import os
import signal
from pathlib import Path

import psutil

from app.processmgr.schemas import (
    OperationResult,
    ProcessCpuEntry,
    ProcessCpuResponse,
    ProcessDetail,
    ProcessInfo,
    ProcessLimits,
    ProcessListResponse,
    TooManyOpenFilesProcess,
    TooManyOpenFilesResponse,
)

logger = logging.getLogger(__name__)

# Signal name to number mapping
_SIGNALS: dict[str, int] = {
    "SIGTERM": signal.SIGTERM,
    "SIGKILL": signal.SIGKILL,
    "SIGHUP": signal.SIGHUP,
    "SIGINT": signal.SIGINT,
    "SIGSTOP": signal.SIGSTOP,
    "SIGCONT": signal.SIGCONT,
    "SIGUSR1": signal.SIGUSR1,
    "SIGUSR2": signal.SIGUSR2,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _proc_info(proc: psutil.Process) -> ProcessInfo | None:
    """Build ProcessInfo from a psutil Process, return None on error."""
    try:
        with proc.oneshot():
            return ProcessInfo(
                pid=proc.pid,
                ppid=proc.ppid(),
                name=proc.name(),
                username=proc.username(),
                status=proc.status(),
                cpu_percent=proc.cpu_percent(),
                memory_rss=proc.memory_info().rss,
                memory_vms=proc.memory_info().vms,
                create_time=proc.create_time(),
                cmdline=" ".join(proc.cmdline()) if proc.cmdline() else "",
                num_threads=proc.num_threads(),
            )
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def _read_proc_file(pid: int, filename: str) -> str:
    """Read a /proc/<pid>/<filename> file, return empty string on failure."""
    try:
        return Path(f"/proc/{pid}/{filename}").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _get_oom_score(pid: int) -> int:
    """Read OOM score from /proc/<pid>/oom_score."""
    content = _read_proc_file(pid, "oom_score")
    try:
        return int(content.strip())
    except (ValueError, AttributeError):
        return 0


def _get_limits(pid: int) -> ProcessLimits:
    """Parse /proc/<pid>/limits for resource limits."""
    content = _read_proc_file(pid, "limits")
    if not content:
        return ProcessLimits()

    limits = ProcessLimits()
    for line in content.splitlines():
        lower = line.lower()
        parts = line.rsplit(None, 3)
        if len(parts) < 3:
            continue
        # Format: "Limit Name       Soft Limit       Hard Limit       Units"
        # We need to extract soft and hard values
        if "max open files" in lower:
            limits.max_open_files_soft = parts[-3]
            limits.max_open_files_hard = parts[-2]
        elif "max processes" in lower:
            limits.max_processes_soft = parts[-3]
            limits.max_processes_hard = parts[-2]
        elif "max stack size" in lower:
            limits.max_stack_size_soft = parts[-3]
            limits.max_stack_size_hard = parts[-2]

    return limits


def _get_open_file_count(pid: int) -> int:
    """Get the number of open file descriptors for a process."""
    fd_path = Path(f"/proc/{pid}/fd")
    try:
        return len(list(fd_path.iterdir()))
    except (OSError, PermissionError):
        return 0


def _get_max_open_files(pid: int) -> int:
    """Get max open files (soft limit) for a process."""
    limits = _get_limits(pid)
    try:
        return int(limits.max_open_files_soft)
    except (ValueError, AttributeError):
        return 0


def _get_memory_maps(proc: psutil.Process) -> tuple[int, int]:
    """Get PSS and USS memory from process memory maps.

    Returns (pss, uss) in bytes.
    """
    try:
        mem = proc.memory_full_info()
        return getattr(mem, "pss", 0), getattr(mem, "uss", 0)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return 0, 0


# ---------------------------------------------------------------------------
# 1. Process list
# ---------------------------------------------------------------------------


def list_processes(
    sort_by: str = "pid", limit: int = 0, username: str | None = None
) -> ProcessListResponse:
    """List running processes with basic info."""
    processes: list[ProcessInfo] = []
    for proc in psutil.process_iter():
        info = _proc_info(proc)
        if info is None:
            continue
        if username and info.username != username:
            continue
        processes.append(info)

    # Sort
    sort_fields = {"pid", "cpu_percent", "memory_rss", "name", "username"}
    if sort_by in sort_fields:
        reverse = sort_by in ("cpu_percent", "memory_rss")
        processes.sort(key=lambda p: getattr(p, sort_by), reverse=reverse)

    if limit > 0:
        processes = processes[:limit]

    return ProcessListResponse(processes=processes, total=len(processes))


# ---------------------------------------------------------------------------
# 2. Send signal (SIGTERM, SIGKILL, etc.)
# ---------------------------------------------------------------------------


def send_signal(pid: int, sig_name: str) -> OperationResult:
    """Send a signal to a process."""
    sig_name_upper = sig_name.upper()
    sig_num = _SIGNALS.get(sig_name_upper)
    if sig_num is None:
        return OperationResult(
            success=False,
            message=f"Unknown signal: {sig_name}. Supported: {list(_SIGNALS)}",
        )

    try:
        os.kill(pid, sig_num)
        logger.info("Sent %s to PID %d", sig_name_upper, pid)
        return OperationResult(
            success=True,
            message=f"Sent {sig_name_upper} to PID {pid}",
        )
    except ProcessLookupError:
        return OperationResult(success=False, message=f"Process not found: PID {pid}")
    except PermissionError:
        return OperationResult(success=False, message=f"Permission denied: PID {pid}")
    except OSError as e:
        return OperationResult(success=False, message=str(e))


# ---------------------------------------------------------------------------
# 3. Restart process (SIGHUP)
# ---------------------------------------------------------------------------


def restart_process(pid: int) -> OperationResult:
    """Restart a process by sending SIGHUP."""
    return send_signal(pid, "SIGHUP")


# ---------------------------------------------------------------------------
# 4. Zombie processes
# ---------------------------------------------------------------------------


def list_zombies() -> ProcessListResponse:
    """List zombie processes."""
    zombies: list[ProcessInfo] = []
    for proc in psutil.process_iter():
        try:
            if proc.status() == psutil.STATUS_ZOMBIE:
                info = ProcessInfo(
                    pid=proc.pid,
                    ppid=proc.ppid(),
                    name=proc.name(),
                    username=proc.username() if proc.username() else "",
                    status="zombie",
                    cmdline=" ".join(proc.cmdline()) if proc.cmdline() else "",
                )
                zombies.append(info)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return ProcessListResponse(processes=zombies, total=len(zombies))


# ---------------------------------------------------------------------------
# 5. Kill all processes of a user
# ---------------------------------------------------------------------------


def kill_user_processes(username: str, sig_name: str = "SIGKILL") -> OperationResult:
    """Kill all processes of a specific user."""
    sig_name_upper = sig_name.upper()
    sig_num = _SIGNALS.get(sig_name_upper)
    if sig_num is None:
        return OperationResult(
            success=False,
            message=f"Unknown signal: {sig_name}. Supported: {list(_SIGNALS)}",
        )

    killed = []
    errors = []
    for proc in psutil.process_iter():
        try:
            if proc.username() == username:
                os.kill(proc.pid, sig_num)
                killed.append(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        except ProcessLookupError:
            continue
        except PermissionError:
            errors.append(proc.pid)
        except OSError:
            continue

    if not killed and not errors:
        return OperationResult(
            success=False,
            message=f"No processes found for user: {username}",
        )

    msg = f"Sent {sig_name_upper} to {len(killed)} processes of user {username}"
    if errors:
        msg += f" ({len(errors)} failed due to permissions)"

    logger.info(msg)
    return OperationResult(success=True, message=msg)


# ---------------------------------------------------------------------------
# 6. Process detail
# ---------------------------------------------------------------------------


def get_process_detail(pid: int) -> ProcessDetail:
    """Get detailed process information including open files, limits, memory, OOM score."""
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        raise ProcessLookupError(f"Process not found: PID {pid}")

    try:
        with proc.oneshot():
            name = proc.name()
            username = proc.username()
            status = proc.status()
            cpu_percent = proc.cpu_percent(interval=0.1)
            mem_info = proc.memory_info()
            cmdline = " ".join(proc.cmdline()) if proc.cmdline() else ""
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        raise ProcessLookupError(str(e))

    pss, uss = _get_memory_maps(proc)
    current_open = _get_open_file_count(pid)
    max_open = _get_max_open_files(pid)
    usage_pct = (current_open / max_open * 100) if max_open > 0 else 0.0
    oom_score = _get_oom_score(pid)
    limits = _get_limits(pid)

    return ProcessDetail(
        pid=pid,
        name=name,
        username=username,
        status=status,
        cpu_percent=cpu_percent,
        memory_rss=mem_info.rss,
        memory_pss=pss,
        memory_uss=uss,
        memory_vms=mem_info.vms,
        current_open_files=current_open,
        max_open_files=max_open,
        open_files_usage_percent=round(usage_pct, 2),
        open_files_warning=usage_pct >= 90.0,
        oom_score=oom_score,
        limits=limits,
        cmdline=cmdline,
    )


# ---------------------------------------------------------------------------
# 7. Too many open files
# ---------------------------------------------------------------------------


def list_too_many_open_files(threshold: float = 90.0) -> TooManyOpenFilesResponse:
    """List processes where open files usage >= threshold% of max."""
    results: list[TooManyOpenFilesProcess] = []

    for proc in psutil.process_iter():
        try:
            pid = proc.pid
            current = _get_open_file_count(pid)
            max_open = _get_max_open_files(pid)

            if max_open <= 0:
                continue

            usage = current / max_open * 100
            if usage >= threshold:
                results.append(
                    TooManyOpenFilesProcess(
                        pid=pid,
                        name=proc.name(),
                        username=proc.username(),
                        current_open_files=current,
                        max_open_files=max_open,
                        usage_percent=round(usage, 2),
                    )
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    results.sort(key=lambda p: p.usage_percent, reverse=True)
    return TooManyOpenFilesResponse(
        processes=results, total=len(results), threshold_percent=threshold
    )


# ---------------------------------------------------------------------------
# 8. Process CPU usage list
# ---------------------------------------------------------------------------


def list_process_cpu(limit: int = 50) -> ProcessCpuResponse:
    """List processes sorted by CPU usage."""
    entries: list[ProcessCpuEntry] = []

    for proc in psutil.process_iter():
        try:
            with proc.oneshot():
                entries.append(
                    ProcessCpuEntry(
                        pid=proc.pid,
                        name=proc.name(),
                        username=proc.username(),
                        cpu_percent=proc.cpu_percent(),
                        status=proc.status(),
                        num_threads=proc.num_threads(),
                        memory_rss=proc.memory_info().rss,
                    )
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    entries.sort(key=lambda p: p.cpu_percent, reverse=True)
    if limit > 0:
        entries = entries[:limit]

    return ProcessCpuResponse(processes=entries, total=len(entries))
