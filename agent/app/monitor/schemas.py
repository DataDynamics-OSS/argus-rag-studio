"""Server resource monitoring schemas."""

from pydantic import BaseModel


class CpuInfo(BaseModel):
    """CPU usage information."""

    usage_percent: float
    core_count: int
    load_avg_1m: float
    load_avg_5m: float
    load_avg_15m: float


class MemoryInfo(BaseModel):
    """Memory usage information."""

    total_bytes: int
    used_bytes: int
    available_bytes: int
    usage_percent: float
    swap_total_bytes: int
    swap_used_bytes: int


class DiskInfo(BaseModel):
    """Disk usage information for a mount point."""

    device: str
    mount_point: str
    fs_type: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    usage_percent: float


class NetworkInfo(BaseModel):
    """Network interface information."""

    interface: str
    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int


class SystemInfo(BaseModel):
    """Aggregated system resource information."""

    hostname: str
    uptime_seconds: float
    cpu: CpuInfo
    memory: MemoryInfo
    disks: list[DiskInfo]
    networks: list[NetworkInfo]
