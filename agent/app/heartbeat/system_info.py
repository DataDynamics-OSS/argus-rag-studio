"""System information collector for heartbeat.

Kernel and OS version are collected once at module load time and cached
in module-level variables since they do not change at runtime.
"""

import logging
import platform
import shutil
import socket
import subprocess

import psutil

logger = logging.getLogger(__name__)

# nvidia-smi 바이너리가 없으면(=GPU 미탑재 서버) 이후 호출에서 영구 스킵.
_no_nvidia_smi = False

# --- Static info: collected once at import time ---

_hostname: str = socket.gethostname()
_kernel_version: str = platform.release()


def _detect_arch() -> str:
    """Normalize platform.machine() to amd64|arm64 (else raw)."""
    m = platform.machine().lower()
    if m in ("aarch64", "arm64"):
        return "arm64"
    if m in ("x86_64", "amd64"):
        return "amd64"
    return m


_arch: str = _detect_arch()


def _detect_os_version() -> str:
    """Read /etc/os-release for PRETTY_NAME, fall back to platform.platform()."""
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            info: dict[str, str] = {}
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    info[k] = v.strip('"')
            return info.get("PRETTY_NAME", platform.platform())
    except FileNotFoundError:
        return platform.platform()


_os_version: str = _detect_os_version()


def get_static_info() -> dict[str, str | int]:
    """Return hostname, kernel_version, os_version, cpu/core counts, total_memory (cached)."""
    return {
        "hostname": _hostname,
        "kernel_version": _kernel_version,
        "os_version": _os_version,
        "arch": _arch,
        "cpu_count": psutil.cpu_count(logical=True) or 1,
        "core_count": psutil.cpu_count(logical=False) or 1,
        "total_memory": psutil.virtual_memory().total,
    }


def get_dynamic_info() -> dict[str, str | float]:
    """Return ip_address, cpu_usage, memory_usage, disk_swap_percent (collected each call)."""
    ip = _detect_ip_address()
    swap = psutil.swap_memory()
    disk_swap_percent = (swap.used / swap.total * 100) if swap.total > 0 else 0.0
    return {
        "ip_address": ip,
        "cpu_usage": psutil.cpu_percent(interval=0),
        "memory_usage": psutil.virtual_memory().percent,
        "disk_swap_percent": round(disk_swap_percent, 1),
    }


def get_gpu_info() -> dict:
    """NVIDIA GPU 메트릭(nvidia-smi)을 집계해 반환. GPU 없으면 빈 dict.

    반환: gpu_count, gpu_usage(평균 이용률 %), gpu_memory_usage(평균 메모리 점유 %),
    gpu_name(첫 GPU 모델명). nvidia-smi 미설치/오류 시 빈 dict 로 하트비트를 막지 않는다.
    """
    global _no_nvidia_smi
    if _no_nvidia_smi:
        return {}
    smi = shutil.which("nvidia-smi")
    if not smi:
        _no_nvidia_smi = True
        return {}

    try:
        proc = subprocess.run(
            [
                smi,
                "--query-gpu=utilization.gpu,memory.total,memory.used,name",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0:
            return {}

        # GB10(통합메모리) 등은 memory.total/used 가 '[N/A]' 일 수 있다. 이런 필드는
        # None 으로 두고 GPU 개수·이용률·이름은 그대로 보고한다(전체를 버리지 않음).
        def _num(x: str) -> float | None:
            x = x.strip()
            try:
                return float(x)
            except ValueError:
                return None

        utils: list[float] = []
        mem_pcts: list[float] = []
        totals_mb: list[float] = []
        names: list[str] = []
        for line in proc.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                continue
            util = _num(parts[0])
            total = _num(parts[1])
            used = _num(parts[2])
            names.append(parts[3])  # 줄 1개 = GPU 1개
            if util is not None:
                utils.append(util)
            if total is not None and total > 0:
                totals_mb.append(total)
            if total and used is not None and total > 0:
                mem_pcts.append(used / total * 100)

        if not names:
            return {}

        return {
            "gpu_count": len(names),
            "gpu_usage": round(sum(utils) / len(utils), 1) if utils else None,
            "gpu_memory_usage": round(sum(mem_pcts) / len(mem_pcts), 1) if mem_pcts else None,
            # 디스크리트(A100/H100)는 총 VRAM(MiB) 합계, 통합메모리(GB10)는 None.
            "gpu_memory_total": round(sum(totals_mb)) if totals_mb else None,
            "gpu_name": names[0],
        }
    except Exception:
        logger.warning("nvidia-smi GPU collection failed", exc_info=True)
        return {}


def _detect_ip_address() -> str:
    """Find the first non-loopback IPv4 address."""
    for iface, addrs in psutil.net_if_addrs().items():
        if iface == "lo":
            continue
        for addr in addrs:
            if addr.family.name == "AF_INET":
                return addr.address
    return "127.0.0.1"


async def get_managed_services() -> list[dict]:
    """Return servicemgr-managed services for the heartbeat inventory.

    On any failure (e.g. systemctl unavailable) returns an empty list so that
    heartbeat delivery is never blocked by service inventory collection.
    """
    try:
        from app.servicemgr import service

        statuses = await service.list_managed()
    except Exception:
        logger.warning("Failed to collect managed services for heartbeat", exc_info=True)
        return []

    return [
        {
            "name": st.name,
            "kind": st.kind,
            "runtime": "systemd",
            "version": st.version,
            "active_state": st.active_state,
            "sub_state": st.sub_state,
            "enabled": st.enabled,
            "pid": st.pid,
        }
        for st in statuses
    ]
