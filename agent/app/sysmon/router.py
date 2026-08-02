"""System monitoring API routes."""

from fastapi import APIRouter, Query

from app.sysmon.schemas import (
    CpuCoreUsage,
    CpuUsage,
    DiskPartitionResult,
    DmesgResult,
    GpuResult,
    NetworkErrorResult,
    NetworkUsageResult,
    ProcessListResult,
    TopResult,
)
from app.sysmon.service import (
    get_cpu_core_usage,
    get_cpu_usage,
    get_disk_partitions,
    get_dmesg,
    get_gpu_usage,
    get_network_errors,
    get_network_usage,
    get_process_list,
    get_top,
)

router = APIRouter(prefix="/sysmon", tags=["sysmon"])


@router.get("/dmesg", response_model=DmesgResult)
async def dmesg(
    lines: int = Query(200, ge=1, le=10000, description="Number of lines to return"),
    level: str | None = Query(None, description="Filter by level (err, warn, info, etc.)"),
) -> DmesgResult:
    """Capture dmesg kernel log output."""
    return await get_dmesg(lines=lines, level=level)


@router.get("/cpu", response_model=CpuUsage)
async def cpu_usage(
    interval: float = Query(0.5, ge=0.1, le=5.0, description="Measurement interval (seconds)"),
) -> CpuUsage:
    """Get aggregate CPU usage breakdown (top-style)."""
    return get_cpu_usage(interval=interval)


@router.get("/cpu/cores", response_model=CpuCoreUsage)
async def cpu_core_usage(
    interval: float = Query(0.5, ge=0.1, le=5.0, description="Measurement interval (seconds)"),
) -> CpuCoreUsage:
    """Get per-core CPU usage breakdown (htop-style)."""
    return get_cpu_core_usage(interval=interval)


@router.get("/network", response_model=NetworkUsageResult)
async def network_usage() -> NetworkUsageResult:
    """Get network usage for all interfaces with totals."""
    return get_network_usage()


@router.get("/network/errors", response_model=NetworkErrorResult)
async def network_errors() -> NetworkErrorResult:
    """Get network error and drop counters per interface."""
    return await get_network_errors()


@router.get("/processes", response_model=ProcessListResult)
async def process_list(
    sort_by: str = Query(
        "cpu_percent",
        description="Sort field: cpu_percent, memory_percent, rss, pid",
    ),
    limit: int = Query(50, ge=1, le=500, description="Maximum processes to return"),
) -> ProcessListResult:
    """Get process list with resource usage (CPU, memory VSS/RSS/PSS/USS/SWAP)."""
    return get_process_list(sort_by=sort_by, limit=limit)


@router.get("/disk/partitions", response_model=DiskPartitionResult)
async def disk_partitions() -> DiskPartitionResult:
    """Get disk partition information with usage stats."""
    return get_disk_partitions()


@router.get("/top", response_model=TopResult)
async def top(
    limit: int = Query(50, ge=1, le=500, description="Maximum processes to return"),
) -> TopResult:
    """Get combined htop-style system overview (CPU, memory, swap, processes)."""
    return get_top(limit=limit)


@router.get("/gpu", response_model=GpuResult)
async def gpu() -> GpuResult:
    """GPU별 메트릭(nvidia-smi). 디스크리트(A100/H100)는 VRAM/온도/전력 포함, GB10은 가능값만."""
    return get_gpu_usage()
