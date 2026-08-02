"""Process management schemas."""

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------


class OperationResult(BaseModel):
    """Generic operation result."""

    success: bool
    message: str = ""


# ---------------------------------------------------------------------------
# Process info
# ---------------------------------------------------------------------------


class ProcessInfo(BaseModel):
    """Basic process information."""

    pid: int
    ppid: int = 0
    name: str = ""
    username: str = ""
    status: str = ""
    cpu_percent: float = 0.0
    memory_rss: int = 0
    memory_vms: int = 0
    create_time: float = 0.0
    cmdline: str = ""
    num_threads: int = 0


class ProcessListResponse(BaseModel):
    """Process list response."""

    processes: list[ProcessInfo] = Field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------------------
# Process detail (feature 6)
# ---------------------------------------------------------------------------


class ProcessLimits(BaseModel):
    """Process resource limits from /proc/<pid>/limits."""

    max_open_files_soft: str = ""
    max_open_files_hard: str = ""
    max_processes_soft: str = ""
    max_processes_hard: str = ""
    max_stack_size_soft: str = ""
    max_stack_size_hard: str = ""


class ProcessDetail(BaseModel):
    """Detailed process information."""

    pid: int
    name: str = ""
    username: str = ""
    status: str = ""
    cpu_percent: float = 0.0
    memory_rss: int = 0
    memory_pss: int = 0
    memory_uss: int = 0
    memory_vms: int = 0
    current_open_files: int = 0
    max_open_files: int = 0
    open_files_usage_percent: float = 0.0
    open_files_warning: bool = Field(
        default=False,
        description="True if current open files >= 90% of max",
    )
    oom_score: int = 0
    limits: ProcessLimits = Field(default_factory=ProcessLimits)
    cmdline: str = ""


# ---------------------------------------------------------------------------
# Too many open files (feature 7)
# ---------------------------------------------------------------------------


class TooManyOpenFilesProcess(BaseModel):
    """Process that has too many open files (>= 90% of max)."""

    pid: int
    name: str = ""
    username: str = ""
    current_open_files: int = 0
    max_open_files: int = 0
    usage_percent: float = 0.0


class TooManyOpenFilesResponse(BaseModel):
    """Response listing processes near open file limits."""

    processes: list[TooManyOpenFilesProcess] = Field(default_factory=list)
    total: int = 0
    threshold_percent: float = 90.0


# ---------------------------------------------------------------------------
# Signal request
# ---------------------------------------------------------------------------


class SignalRequest(BaseModel):
    """Request to send a signal to a process."""

    pid: int = Field(..., description="Process ID")
    signal: str = Field(
        default="SIGTERM",
        description="Signal name (SIGTERM, SIGKILL, SIGHUP, etc.)",
    )


class KillUserRequest(BaseModel):
    """Request to kill all processes of a user."""

    username: str = Field(..., description="Username whose processes to kill")
    signal: str = Field(
        default="SIGKILL",
        description="Signal to send (default: SIGKILL)",
    )


# ---------------------------------------------------------------------------
# CPU usage list (feature 8)
# ---------------------------------------------------------------------------


class ProcessCpuEntry(BaseModel):
    """Process with CPU usage info."""

    pid: int
    name: str = ""
    username: str = ""
    cpu_percent: float = 0.0
    status: str = ""
    num_threads: int = 0
    memory_rss: int = 0


class ProcessCpuResponse(BaseModel):
    """Process list sorted by CPU usage."""

    processes: list[ProcessCpuEntry] = Field(default_factory=list)
    total: int = 0
