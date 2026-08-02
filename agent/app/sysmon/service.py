"""System monitoring service - advanced metrics collection."""

import asyncio
import logging
import os
import re
import shutil
import socket
import subprocess
from pathlib import Path

import psutil

from app.sysmon.schemas import (
    CoreUsage,
    CpuCoreUsage,
    CpuUsage,
    DiskPartitionInfo,
    DiskPartitionResult,
    DmesgEntry,
    DmesgResult,
    GpuInfo,
    GpuResult,
    NetworkErrorEntry,
    NetworkErrorResult,
    NetworkInterfaceUsage,
    NetworkTotalUsage,
    NetworkUsageResult,
    ProcessInfo,
    ProcessListResult,
    ProcessMemoryDetail,
    TopMemoryInfo,
    TopProcess,
    TopResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. dmesg
# ---------------------------------------------------------------------------

_DMESG_LINE_RE = re.compile(r"^\[?\s*([\d.]+)\]?\s*(.*)")


async def get_dmesg(lines: int = 200, level: str | None = None) -> DmesgResult:
    """Capture dmesg output.

    Args:
        lines: Maximum number of lines to return (tail).
        level: Filter by level (e.g. 'err', 'warn', 'info'). None for all.
    """
    cmd = "dmesg --time-format iso"
    if level:
        cmd += f" --level={level}"
    cmd += f" | tail -n {lines}"

    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    raw = stdout.decode(errors="replace")

    entries = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # Try to split timestamp and message
        # ISO format: "2025-03-15T14:30:45,123456+09:00 kernel: message"
        parts = line.split(" ", 1)
        if len(parts) == 2:
            entries.append(DmesgEntry(timestamp=parts[0], message=parts[1]))
        else:
            entries.append(DmesgEntry(message=line))

    return DmesgResult(
        entries=entries,
        total_lines=len(entries),
        raw=raw,
    )


# ---------------------------------------------------------------------------
# 2. CPU usage (top-style aggregate)
# ---------------------------------------------------------------------------


def get_cpu_usage(interval: float = 0.5) -> CpuUsage:
    """Get aggregate CPU usage breakdown.

    Args:
        interval: Measurement interval in seconds.
    """
    times = psutil.cpu_times_percent(interval=interval)
    load = os.getloadavg()

    user = getattr(times, "user", 0.0)
    system = getattr(times, "system", 0.0)
    iowait = getattr(times, "iowait", 0.0)
    idle = getattr(times, "idle", 0.0)
    nice = getattr(times, "nice", 0.0)
    irq = getattr(times, "irq", 0.0)
    softirq = getattr(times, "softirq", 0.0)
    steal = getattr(times, "steal", 0.0)

    return CpuUsage(
        user_percent=user,
        system_percent=system,
        iowait_percent=iowait,
        idle_percent=idle,
        nice_percent=nice,
        irq_percent=irq,
        softirq_percent=softirq,
        steal_percent=steal,
        total_percent=round(100.0 - idle, 2),
        core_count=psutil.cpu_count() or 1,
        load_avg_1m=load[0],
        load_avg_5m=load[1],
        load_avg_15m=load[2],
    )


# ---------------------------------------------------------------------------
# 3. Per-core CPU usage (htop-style)
# ---------------------------------------------------------------------------


def get_cpu_core_usage(interval: float = 0.5) -> CpuCoreUsage:
    """Get per-core CPU usage breakdown.

    Args:
        interval: Measurement interval in seconds.
    """
    per_cpu = psutil.cpu_times_percent(interval=interval, percpu=True)

    cores = []
    for i, times in enumerate(per_cpu):
        user = getattr(times, "user", 0.0)
        system = getattr(times, "system", 0.0)
        iowait = getattr(times, "iowait", 0.0)
        idle = getattr(times, "idle", 0.0)
        nice = getattr(times, "nice", 0.0)
        irq = getattr(times, "irq", 0.0)
        softirq = getattr(times, "softirq", 0.0)
        steal = getattr(times, "steal", 0.0)

        cores.append(
            CoreUsage(
                core_id=i,
                user_percent=user,
                system_percent=system,
                iowait_percent=iowait,
                idle_percent=idle,
                nice_percent=nice,
                irq_percent=irq,
                softirq_percent=softirq,
                steal_percent=steal,
                total_percent=round(100.0 - idle, 2),
            )
        )

    return CpuCoreUsage(cores=cores, core_count=len(cores))


# ---------------------------------------------------------------------------
# 4. Network usage (total + per interface)
# ---------------------------------------------------------------------------


def _get_iface_speed(iface: str) -> int:
    """Try to read interface speed in Mbps from sysfs."""
    speed_path = Path(f"/sys/class/net/{iface}/speed")
    try:
        if speed_path.is_file():
            val = int(speed_path.read_text().strip())
            return val if val > 0 else 0
    except (ValueError, OSError):
        pass
    return 0


def _get_iface_mtu(iface: str) -> int:
    """Read interface MTU from sysfs."""
    mtu_path = Path(f"/sys/class/net/{iface}/mtu")
    try:
        if mtu_path.is_file():
            return int(mtu_path.read_text().strip())
    except (ValueError, OSError):
        pass
    return 0


def _get_iface_operstate(iface: str) -> bool:
    """Check if interface is operationally up."""
    state_path = Path(f"/sys/class/net/{iface}/operstate")
    try:
        if state_path.is_file():
            return state_path.read_text().strip().lower() == "up"
    except OSError:
        pass
    return True


def get_network_usage() -> NetworkUsageResult:
    """Get network usage for all interfaces with totals."""
    counters = psutil.net_io_counters(pernic=True)
    addrs = psutil.net_if_addrs()

    interfaces = []
    total_sent = total_recv = total_pkt_sent = total_pkt_recv = 0
    total_err_in = total_err_out = total_drop_in = total_drop_out = 0

    for iface, stats in counters.items():
        # IP addresses
        ipv4 = ""
        ipv6 = ""
        for addr in addrs.get(iface, []):
            if addr.family == socket.AF_INET and not ipv4:
                ipv4 = addr.address
            elif addr.family == socket.AF_INET6 and not ipv6:
                ipv6 = addr.address

        iface_info = NetworkInterfaceUsage(
            interface=iface,
            bytes_sent=stats.bytes_sent,
            bytes_recv=stats.bytes_recv,
            packets_sent=stats.packets_sent,
            packets_recv=stats.packets_recv,
            errors_in=stats.errin,
            errors_out=stats.errout,
            drops_in=stats.dropin,
            drops_out=stats.dropout,
            speed_mbps=_get_iface_speed(iface),
            is_up=_get_iface_operstate(iface),
            mtu=_get_iface_mtu(iface),
            ipv4_address=ipv4,
            ipv6_address=ipv6,
        )
        interfaces.append(iface_info)

        total_sent += stats.bytes_sent
        total_recv += stats.bytes_recv
        total_pkt_sent += stats.packets_sent
        total_pkt_recv += stats.packets_recv
        total_err_in += stats.errin
        total_err_out += stats.errout
        total_drop_in += stats.dropin
        total_drop_out += stats.dropout

    total = NetworkTotalUsage(
        bytes_sent=total_sent,
        bytes_recv=total_recv,
        packets_sent=total_pkt_sent,
        packets_recv=total_pkt_recv,
        errors_in=total_err_in,
        errors_out=total_err_out,
        drops_in=total_drop_in,
        drops_out=total_drop_out,
    )

    return NetworkUsageResult(total=total, interfaces=interfaces)


# ---------------------------------------------------------------------------
# 5. Network errors per interface
# ---------------------------------------------------------------------------


async def get_network_errors() -> NetworkErrorResult:
    """Get detailed network error counters per interface.

    Uses /proc/net/dev and ethtool for extended stats.
    """
    counters = psutil.net_io_counters(pernic=True)

    # Try to get extended stats from ethtool
    extended: dict[str, dict[str, int]] = {}
    for iface in counters:
        ext = await _get_ethtool_stats(iface)
        if ext:
            extended[iface] = ext

    entries = []
    total_errors = 0
    for iface, stats in counters.items():
        ext = extended.get(iface, {})
        entry = NetworkErrorEntry(
            interface=iface,
            errors_in=stats.errin,
            errors_out=stats.errout,
            drops_in=stats.dropin,
            drops_out=stats.dropout,
            overruns_in=ext.get("rx_over_errors", 0),
            overruns_out=0,
            carrier_errors=ext.get("tx_carrier_errors", 0),
            collisions=ext.get("collisions", 0),
            has_errors=(
                stats.errin
                + stats.errout
                + stats.dropin
                + stats.dropout
                + ext.get("rx_over_errors", 0)
                + ext.get("tx_carrier_errors", 0)
                + ext.get("collisions", 0)
            )
            > 0,
        )
        total_errors += (
            entry.errors_in
            + entry.errors_out
            + entry.drops_in
            + entry.drops_out
            + entry.overruns_in
            + entry.carrier_errors
            + entry.collisions
        )
        entries.append(entry)

    return NetworkErrorResult(interfaces=entries, total_errors=total_errors)


async def _get_ethtool_stats(iface: str) -> dict[str, int]:
    """Try to get extended NIC stats via ethtool -S."""
    proc = await asyncio.create_subprocess_shell(
        f"ethtool -S {iface} 2>/dev/null",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return {}

    result: dict[str, int] = {}
    for line in stdout.decode(errors="replace").splitlines():
        line = line.strip()
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            try:
                result[key] = int(val.strip())
            except ValueError:
                pass
    return result


# ---------------------------------------------------------------------------
# 6. Process resource usage
# ---------------------------------------------------------------------------


def get_process_list(
    sort_by: str = "cpu_percent",
    limit: int = 50,
) -> ProcessListResult:
    """Get process list with detailed resource usage.

    Args:
        sort_by: Sort field ('cpu_percent', 'memory_percent', 'rss', 'pid').
        limit: Maximum number of processes to return.
    """
    # Pre-call to get meaningful cpu_percent values
    for proc in psutil.process_iter():
        try:
            proc.cpu_percent()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Brief pause for CPU measurement
    import time

    time.sleep(0.1)

    processes = []
    for proc in psutil.process_iter():
        try:
            with proc.oneshot():
                pinfo = proc.as_dict(
                    attrs=[
                        "pid",
                        "name",
                        "username",
                        "status",
                        "cpu_percent",
                        "memory_percent",
                        "memory_info",
                        "num_threads",
                        "create_time",
                    ]
                )

                mem_info = pinfo.get("memory_info")
                if mem_info is None:
                    continue

                # Try to get extended memory info (USS, PSS, SWAP)
                uss = pss = swap = shared = 0
                try:
                    mem_full = proc.memory_full_info()
                    uss = getattr(mem_full, "uss", 0)
                    pss = getattr(mem_full, "pss", 0)
                    swap = getattr(mem_full, "swap", 0)
                    shared = getattr(mem_full, "shared", 0)
                except (psutil.AccessDenied, psutil.NoSuchProcess, AttributeError):
                    shared = getattr(mem_info, "shared", 0)

                # File descriptor count
                num_fds = 0
                try:
                    num_fds = proc.num_fds()
                except (psutil.AccessDenied, psutil.NoSuchProcess, AttributeError):
                    pass

                # Command line
                cmdline = ""
                try:
                    cmdline = " ".join(proc.cmdline())
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass

                memory = ProcessMemoryDetail(
                    rss_bytes=mem_info.rss,
                    vms_bytes=mem_info.vms,
                    shared_bytes=shared,
                    uss_bytes=uss,
                    pss_bytes=pss,
                    swap_bytes=swap,
                )

                processes.append(
                    ProcessInfo(
                        pid=pinfo["pid"],
                        name=pinfo.get("name", ""),
                        username=pinfo.get("username", ""),
                        status=pinfo.get("status", ""),
                        cpu_percent=pinfo.get("cpu_percent", 0.0) or 0.0,
                        memory_percent=pinfo.get("memory_percent", 0.0) or 0.0,
                        memory=memory,
                        num_threads=pinfo.get("num_threads", 0) or 0,
                        num_fds=num_fds,
                        create_time=pinfo.get("create_time", 0) or 0,
                        cmdline=cmdline[:512],
                    )
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Sort
    sort_key_map = {
        "cpu_percent": lambda p: p.cpu_percent,
        "memory_percent": lambda p: p.memory_percent,
        "rss": lambda p: p.memory.rss_bytes,
        "pid": lambda p: p.pid,
    }
    key_func = sort_key_map.get(sort_by, sort_key_map["cpu_percent"])
    processes.sort(key=key_func, reverse=(sort_by != "pid"))

    return ProcessListResult(
        processes=processes[:limit],
        total_count=len(processes),
        sort_by=sort_by,
    )


# ---------------------------------------------------------------------------
# 7. Disk partitions
# ---------------------------------------------------------------------------


def _get_parent_disk(device: str) -> str:
    """Extract parent disk device from partition path.

    e.g. /dev/sda1 -> /dev/sda, /dev/nvme0n1p1 -> /dev/nvme0n1
    """
    name = os.path.basename(device)
    # NVMe: nvme0n1p1 -> nvme0n1
    nvme_match = re.match(r"(nvme\d+n\d+)p\d+", name)
    if nvme_match:
        return f"/dev/{nvme_match.group(1)}"
    # SCSI/SATA: sda1 -> sda, vda1 -> vda
    scsi_match = re.match(r"([a-z]+)\d+", name)
    if scsi_match:
        return f"/dev/{scsi_match.group(1)}"
    return device


def get_disk_partitions() -> DiskPartitionResult:
    """Get disk partition information with usage stats."""
    partitions = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue

        partitions.append(
            DiskPartitionInfo(
                device=part.device,
                mount_point=part.mountpoint,
                fs_type=part.fstype,
                options=part.opts,
                total_bytes=usage.total,
                used_bytes=usage.used,
                free_bytes=usage.free,
                usage_percent=usage.percent,
                disk_device=_get_parent_disk(part.device),
            )
        )

    return DiskPartitionResult(
        partitions=partitions,
        total_count=len(partitions),
    )


# ---------------------------------------------------------------------------
# 8. Top (htop-style combined view)
# ---------------------------------------------------------------------------


def get_top(limit: int = 50) -> TopResult:
    """Get combined htop-style system overview in a single call.

    Collects CPU (aggregate + per-core), memory, swap, uptime, task counts,
    and top processes sorted by CPU usage.
    """
    import time as _time

    # CPU measurement (aggregate + per-core in one interval)
    # Pre-call for meaningful cpu_percent on processes
    for proc in psutil.process_iter():
        try:
            proc.cpu_percent()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Brief pause then collect CPU times
    _time.sleep(0.1)

    times = psutil.cpu_times_percent(interval=0.3)
    per_cpu = psutil.cpu_times_percent(interval=0, percpu=True)
    load = os.getloadavg()

    user = getattr(times, "user", 0.0)
    system = getattr(times, "system", 0.0)
    iowait = getattr(times, "iowait", 0.0)
    idle = getattr(times, "idle", 0.0)
    nice = getattr(times, "nice", 0.0)
    irq = getattr(times, "irq", 0.0)
    softirq = getattr(times, "softirq", 0.0)
    steal = getattr(times, "steal", 0.0)

    cpu = CpuUsage(
        user_percent=user,
        system_percent=system,
        iowait_percent=iowait,
        idle_percent=idle,
        nice_percent=nice,
        irq_percent=irq,
        softirq_percent=softirq,
        steal_percent=steal,
        total_percent=round(100.0 - idle, 2),
        core_count=psutil.cpu_count() or 1,
        load_avg_1m=load[0],
        load_avg_5m=load[1],
        load_avg_15m=load[2],
    )

    cores = []
    for i, ct in enumerate(per_cpu):
        c_idle = getattr(ct, "idle", 0.0)
        cores.append(
            CoreUsage(
                core_id=i,
                user_percent=getattr(ct, "user", 0.0),
                system_percent=getattr(ct, "system", 0.0),
                iowait_percent=getattr(ct, "iowait", 0.0),
                idle_percent=c_idle,
                nice_percent=getattr(ct, "nice", 0.0),
                irq_percent=getattr(ct, "irq", 0.0),
                softirq_percent=getattr(ct, "softirq", 0.0),
                steal_percent=getattr(ct, "steal", 0.0),
                total_percent=round(100.0 - c_idle, 2),
            )
        )

    # Memory
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    memory = TopMemoryInfo(
        total_bytes=mem.total,
        used_bytes=mem.used,
        free_bytes=mem.free,
        available_bytes=mem.available,
        usage_percent=mem.percent,
        swap_total_bytes=swap.total,
        swap_used_bytes=swap.used,
        swap_free_bytes=swap.free,
        swap_usage_percent=swap.percent,
    )

    # Uptime
    uptime = _time.time() - psutil.boot_time()

    # Processes
    task_counts = {"running": 0, "sleeping": 0, "stopped": 0, "zombie": 0}
    processes: list[TopProcess] = []
    for proc in psutil.process_iter():
        try:
            with proc.oneshot():
                pinfo = proc.as_dict(
                    attrs=[
                        "pid", "username", "status", "cpu_percent",
                        "memory_percent", "memory_info", "num_threads",
                    ]
                )
                status = pinfo.get("status", "")
                if status == psutil.STATUS_RUNNING:
                    task_counts["running"] += 1
                elif status in (psutil.STATUS_SLEEPING, psutil.STATUS_IDLE):
                    task_counts["sleeping"] += 1
                elif status == psutil.STATUS_STOPPED:
                    task_counts["stopped"] += 1
                elif status == psutil.STATUS_ZOMBIE:
                    task_counts["zombie"] += 1

                mem_info = pinfo.get("memory_info")
                if mem_info is None:
                    continue

                cmdline = ""
                try:
                    cmdline = " ".join(proc.cmdline())
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass

                processes.append(
                    TopProcess(
                        pid=pinfo["pid"],
                        username=pinfo.get("username", "") or "",
                        cpu_percent=pinfo.get("cpu_percent", 0.0) or 0.0,
                        memory_percent=pinfo.get("memory_percent", 0.0) or 0.0,
                        rss_bytes=mem_info.rss,
                        vms_bytes=mem_info.vms,
                        status=status,
                        num_threads=pinfo.get("num_threads", 0) or 0,
                        cmdline=cmdline[:512],
                    )
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    total_count = len(processes)
    processes.sort(key=lambda p: p.cpu_percent, reverse=True)

    return TopResult(
        uptime_seconds=uptime,
        cpu=cpu,
        cores=cores,
        memory=memory,
        tasks_total=total_count,
        tasks_running=task_counts["running"],
        tasks_sleeping=task_counts["sleeping"],
        tasks_stopped=task_counts["stopped"],
        tasks_zombie=task_counts["zombie"],
        processes=processes[:limit],
    )


def _gpu_num(x: str) -> float | None:
    """nvidia-smi 필드 → float. '[N/A]'/비숫자(GB10 통합메모리 등)는 None."""
    x = x.strip()
    try:
        return float(x)
    except ValueError:
        return None


def get_gpu_usage() -> GpuResult:
    """nvidia-smi 로 GPU별 메트릭 수집(디스크리트 A100/H100 풀, GB10 통합메모리 N/A 내성)."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return GpuResult(available=False, count=0, gpus=[])
    try:
        proc = subprocess.run(
            [
                smi,
                "--query-gpu=index,name,utilization.gpu,memory.total,memory.used,"
                "temperature.gpu,power.draw,power.limit",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0:
            return GpuResult(available=False, count=0, gpus=[])

        gpus: list[GpuInfo] = []
        for line in proc.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 8:
                continue
            idx = int(parts[0]) if parts[0].lstrip("-").isdigit() else len(gpus)
            gpus.append(
                GpuInfo(
                    index=idx,
                    name=parts[1] or "GPU",
                    util_percent=_gpu_num(parts[2]),
                    mem_total_mb=_gpu_num(parts[3]),
                    mem_used_mb=_gpu_num(parts[4]),
                    temp_c=_gpu_num(parts[5]),
                    power_w=_gpu_num(parts[6]),
                    power_limit_w=_gpu_num(parts[7]),
                )
            )
        return GpuResult(available=bool(gpus), count=len(gpus), gpus=gpus)
    except Exception:
        logger.warning("nvidia-smi GPU collection failed", exc_info=True)
        return GpuResult(available=False, count=0, gpus=[])
