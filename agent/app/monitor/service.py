"""Server resource monitoring service."""

import logging
import os
import platform

import psutil

from app.monitor.schemas import (
    CpuInfo,
    DiskInfo,
    MemoryInfo,
    NetworkInfo,
    SystemInfo,
)

logger = logging.getLogger(__name__)


def get_cpu_info() -> CpuInfo:
    """Collect CPU usage information."""
    load_avg = os.getloadavg()
    return CpuInfo(
        usage_percent=psutil.cpu_percent(interval=0.1),
        core_count=psutil.cpu_count() or 1,
        load_avg_1m=load_avg[0],
        load_avg_5m=load_avg[1],
        load_avg_15m=load_avg[2],
    )


def get_memory_info() -> MemoryInfo:
    """Collect memory usage information."""
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return MemoryInfo(
        total_bytes=mem.total,
        used_bytes=mem.used,
        available_bytes=mem.available,
        usage_percent=mem.percent,
        swap_total_bytes=swap.total,
        swap_used_bytes=swap.used,
    )


def get_disk_info() -> list[DiskInfo]:
    """Collect disk usage information."""
    disks = []
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append(
                DiskInfo(
                    device=part.device,
                    mount_point=part.mountpoint,
                    fs_type=part.fstype,
                    total_bytes=usage.total,
                    used_bytes=usage.used,
                    free_bytes=usage.free,
                    usage_percent=usage.percent,
                )
            )
        except PermissionError:
            continue
    return disks


def get_network_info() -> list[NetworkInfo]:
    """Collect network interface information."""
    counters = psutil.net_io_counters(pernic=True)
    return [
        NetworkInfo(
            interface=iface,
            bytes_sent=stats.bytes_sent,
            bytes_recv=stats.bytes_recv,
            packets_sent=stats.packets_sent,
            packets_recv=stats.packets_recv,
        )
        for iface, stats in counters.items()
    ]


def get_system_info() -> SystemInfo:
    """Collect all system resource information."""
    return SystemInfo(
        hostname=platform.node(),
        uptime_seconds=_get_uptime(),
        cpu=get_cpu_info(),
        memory=get_memory_info(),
        disks=get_disk_info(),
        networks=get_network_info(),
    )


def _get_uptime() -> float:
    """Get system uptime in seconds."""
    import time

    return time.time() - psutil.boot_time()
