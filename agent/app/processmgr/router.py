"""Process management API routes."""

from fastapi import APIRouter, HTTPException

from app.processmgr.schemas import (
    KillUserRequest,
    OperationResult,
    ProcessCpuResponse,
    ProcessDetail,
    ProcessListResponse,
    SignalRequest,
    TooManyOpenFilesResponse,
)
from app.processmgr.service import (
    get_process_detail,
    kill_user_processes,
    list_process_cpu,
    list_processes,
    list_too_many_open_files,
    list_zombies,
    restart_process,
    send_signal,
)

router = APIRouter(prefix="/process", tags=["process"])


# ---------------------------------------------------------------------------
# Process list
# ---------------------------------------------------------------------------


@router.get("/list", response_model=ProcessListResponse)
async def process_list(
    sort_by: str = "pid",
    limit: int = 0,
    username: str | None = None,
) -> ProcessListResponse:
    """List running processes."""
    return list_processes(sort_by=sort_by, limit=limit, username=username)


# ---------------------------------------------------------------------------
# Send signal / restart
# ---------------------------------------------------------------------------


@router.post("/signal", response_model=OperationResult)
async def process_signal(request: SignalRequest) -> OperationResult:
    """Send a signal to a process."""
    return send_signal(request.pid, request.signal)


@router.post("/restart/{pid}", response_model=OperationResult)
async def process_restart(pid: int) -> OperationResult:
    """Restart a process (SIGHUP)."""
    return restart_process(pid)


# ---------------------------------------------------------------------------
# Zombie processes
# ---------------------------------------------------------------------------


@router.get("/zombies", response_model=ProcessListResponse)
async def process_zombies() -> ProcessListResponse:
    """List zombie processes."""
    return list_zombies()


# ---------------------------------------------------------------------------
# Kill user processes
# ---------------------------------------------------------------------------


@router.post("/kill-user", response_model=OperationResult)
async def process_kill_user(request: KillUserRequest) -> OperationResult:
    """Kill all processes of a specific user."""
    return kill_user_processes(request.username, request.signal)


# ---------------------------------------------------------------------------
# Process detail
# ---------------------------------------------------------------------------


@router.get("/detail/{pid}", response_model=ProcessDetail)
async def process_detail(pid: int) -> ProcessDetail:
    """Get detailed process information."""
    try:
        return get_process_detail(pid)
    except ProcessLookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Too many open files
# ---------------------------------------------------------------------------


@router.get("/too-many-open-files", response_model=TooManyOpenFilesResponse)
async def process_too_many_open_files(
    threshold: float = 90.0,
) -> TooManyOpenFilesResponse:
    """List processes near their open file limit."""
    return list_too_many_open_files(threshold=threshold)


# ---------------------------------------------------------------------------
# CPU usage
# ---------------------------------------------------------------------------


@router.get("/cpu", response_model=ProcessCpuResponse)
async def process_cpu(limit: int = 50) -> ProcessCpuResponse:
    """List processes sorted by CPU usage."""
    return list_process_cpu(limit=limit)
