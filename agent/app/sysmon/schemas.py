"""System monitoring schemas - structured for React UI consumption."""

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 1. dmesg
# ---------------------------------------------------------------------------


class DmesgEntry(BaseModel):
    """A single dmesg log entry."""

    timestamp: str = Field("", description="Kernel timestamp (e.g. '[ 12.345678]')")
    facility: str = Field("", description="Facility/level if available")
    message: str


class DmesgResult(BaseModel):
    """Result of dmesg capture."""

    entries: list[DmesgEntry]
    total_lines: int
    raw: str = Field("", description="Raw dmesg output")


# ---------------------------------------------------------------------------
# 2. CPU usage (top-style aggregate)
# ---------------------------------------------------------------------------


class CpuUsage(BaseModel):
    """Aggregate CPU usage breakdown (top-style)."""

    user_percent: float = Field(description="User space CPU %")
    system_percent: float = Field(description="Kernel space CPU %")
    iowait_percent: float = Field(description="I/O wait CPU %")
    idle_percent: float = Field(description="Idle CPU %")
    nice_percent: float = Field(description="Nice'd processes CPU %")
    irq_percent: float = Field(description="Hardware interrupt CPU %")
    softirq_percent: float = Field(description="Software interrupt CPU %")
    steal_percent: float = Field(description="Hypervisor steal CPU %")
    total_percent: float = Field(description="Total CPU usage %")
    core_count: int
    load_avg_1m: float
    load_avg_5m: float
    load_avg_15m: float


# ---------------------------------------------------------------------------
# 3. Per-core CPU usage (htop-style)
# ---------------------------------------------------------------------------


class CoreUsage(BaseModel):
    """CPU usage for a single core."""

    core_id: int
    user_percent: float
    system_percent: float
    iowait_percent: float
    idle_percent: float
    nice_percent: float
    irq_percent: float
    softirq_percent: float
    steal_percent: float
    total_percent: float


class CpuCoreUsage(BaseModel):
    """Per-core CPU usage (htop-style)."""

    cores: list[CoreUsage]
    core_count: int


# ---------------------------------------------------------------------------
# 4 & 5. Network usage & errors
# ---------------------------------------------------------------------------


class NetworkInterfaceUsage(BaseModel):
    """Network usage for a single interface."""

    interface: str
    # Traffic
    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int
    # Errors & drops
    errors_in: int = Field(description="Receive errors")
    errors_out: int = Field(description="Transmit errors")
    drops_in: int = Field(description="Incoming packets dropped")
    drops_out: int = Field(description="Outgoing packets dropped")
    # Speed (if detectable)
    speed_mbps: int = Field(0, description="Link speed in Mbps (0 if unknown)")
    is_up: bool = Field(True, description="Interface is up")
    mtu: int = Field(0, description="MTU size")
    # Addresses
    ipv4_address: str = Field("", description="Primary IPv4 address")
    ipv6_address: str = Field("", description="Primary IPv6 address")


class NetworkTotalUsage(BaseModel):
    """Aggregate network usage across all interfaces."""

    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int
    errors_in: int
    errors_out: int
    drops_in: int
    drops_out: int


class NetworkUsageResult(BaseModel):
    """Complete network usage report."""

    total: NetworkTotalUsage
    interfaces: list[NetworkInterfaceUsage]


class NetworkErrorEntry(BaseModel):
    """Network error/drop summary for a single interface."""

    interface: str
    errors_in: int
    errors_out: int
    drops_in: int
    drops_out: int
    overruns_in: int = 0
    overruns_out: int = 0
    carrier_errors: int = 0
    collisions: int = 0
    has_errors: bool = Field(description="True if any error counter > 0")


class NetworkErrorResult(BaseModel):
    """Network error report across all interfaces."""

    interfaces: list[NetworkErrorEntry]
    total_errors: int = Field(description="Sum of all error counters")


# ---------------------------------------------------------------------------
# 6. Process resource usage
# ---------------------------------------------------------------------------


class ProcessMemoryDetail(BaseModel):
    """Detailed memory usage for a process."""

    rss_bytes: int = Field(description="Resident Set Size")
    vms_bytes: int = Field(description="Virtual Memory Size")
    shared_bytes: int = Field(0, description="Shared memory")
    uss_bytes: int = Field(0, description="Unique Set Size (process-exclusive)")
    pss_bytes: int = Field(0, description="Proportional Set Size")
    swap_bytes: int = Field(0, description="Swap usage")


class ProcessInfo(BaseModel):
    """Resource usage for a single process."""

    pid: int
    name: str
    username: str = ""
    status: str = ""
    cpu_percent: float = Field(description="CPU usage %")
    memory_percent: float = Field(description="Memory usage % of total RAM")
    memory: ProcessMemoryDetail
    num_threads: int = 0
    num_fds: int = Field(0, description="Number of open file descriptors")
    create_time: float = Field(0, description="Process creation time (epoch)")
    cmdline: str = Field("", description="Full command line")


class ProcessListResult(BaseModel):
    """Process list with resource usage."""

    processes: list[ProcessInfo]
    total_count: int
    sort_by: str = Field("cpu_percent", description="Sort field used")


# ---------------------------------------------------------------------------
# 7. Disk partitions
# ---------------------------------------------------------------------------


class DiskPartitionInfo(BaseModel):
    """Disk partition information."""

    device: str = Field(description="Device path (e.g. /dev/sda1)")
    mount_point: str
    fs_type: str = Field(description="File system type (ext4, xfs, etc.)")
    options: str = Field("", description="Mount options")
    total_bytes: int
    used_bytes: int
    free_bytes: int
    usage_percent: float
    # Disk device info
    disk_device: str = Field("", description="Parent disk device (e.g. /dev/sda)")


class DiskPartitionResult(BaseModel):
    """Disk partition report."""

    partitions: list[DiskPartitionInfo]
    total_count: int


# ---------------------------------------------------------------------------
# 8. Top (htop-style combined view)
# ---------------------------------------------------------------------------


class TopMemoryInfo(BaseModel):
    """Memory and swap summary for top view."""

    total_bytes: int
    used_bytes: int
    free_bytes: int
    available_bytes: int
    usage_percent: float
    swap_total_bytes: int
    swap_used_bytes: int
    swap_free_bytes: int
    swap_usage_percent: float


class TopProcess(BaseModel):
    """Simplified process entry for top view."""

    pid: int
    username: str = ""
    cpu_percent: float
    memory_percent: float
    rss_bytes: int
    vms_bytes: int
    status: str = ""
    num_threads: int = 0
    cmdline: str = ""


class TopResult(BaseModel):
    """Combined top/htop-style system overview."""

    uptime_seconds: float
    cpu: CpuUsage
    cores: list[CoreUsage]
    memory: TopMemoryInfo
    tasks_total: int
    tasks_running: int
    tasks_sleeping: int
    tasks_stopped: int
    tasks_zombie: int
    processes: list[TopProcess]


class GpuInfo(BaseModel):
    """단일 GPU 메트릭. 통합메모리(GB10) 등에서 일부 필드는 None."""

    index: int
    name: str
    util_percent: float | None = None
    mem_total_mb: float | None = None
    mem_used_mb: float | None = None
    temp_c: float | None = None
    power_w: float | None = None
    power_limit_w: float | None = None


class GpuResult(BaseModel):
    """GPU 메트릭 목록. available=False 면 nvidia-smi 없음/GPU 없음."""

    available: bool
    count: int
    gpus: list[GpuInfo] = []
