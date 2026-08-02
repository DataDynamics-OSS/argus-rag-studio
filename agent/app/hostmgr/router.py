"""Host management API routes."""

from fastapi import APIRouter, HTTPException

from app.hostmgr.schemas import (
    BackupResult,
    FileContent,
    FileUpdateRequest,
    HostnameChangeRequest,
    HostnameInfo,
    HostnameValidation,
    InspectResult,
    LimitsConfResponse,
    LimitsConfSetRequest,
    NameserverUpdateRequest,
    OperationResult,
    ResolvConfInfo,
    UlimitAllResponse,
    UlimitEntry,
    UlimitSetRequest,
)
from app.hostmgr.service import (
    backup_hosts_file,
    backup_resolv_conf,
    change_hostname,
    get_hostname,
    get_nameservers,
    get_ulimit,
    get_ulimit_all,
    inspect_host,
    read_hosts_file,
    read_resolv_conf,
    set_ulimit,
    set_user_max_open_files,
    update_hosts_file,
    update_nameservers,
    update_resolv_conf,
    validate_hostname,
)

router = APIRouter(prefix="/host", tags=["host"])


# ---------------------------------------------------------------------------
# Hostname
# ---------------------------------------------------------------------------


@router.get("/hostname", response_model=HostnameInfo)
async def hostname_get() -> HostnameInfo:
    """Get current hostname and FQDN."""
    return await get_hostname()


@router.put("/hostname", response_model=OperationResult)
async def hostname_change(request: HostnameChangeRequest) -> OperationResult:
    """Change the system hostname."""
    return await change_hostname(request.hostname)


@router.get("/hostname/validate", response_model=HostnameValidation)
async def hostname_validate() -> HostnameValidation:
    """Validate hostname consistency (hostname vs hostname -f)."""
    return await validate_hostname()


# ---------------------------------------------------------------------------
# /etc/hosts
# ---------------------------------------------------------------------------


@router.get("/hosts", response_model=FileContent)
async def hosts_read() -> FileContent:
    """Read /etc/hosts file."""
    try:
        return read_hosts_file()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/hosts", response_model=OperationResult)
async def hosts_update(request: FileUpdateRequest) -> OperationResult:
    """Update /etc/hosts file."""
    return update_hosts_file(request.content)


@router.post("/hosts/backup", response_model=BackupResult)
async def hosts_backup() -> BackupResult:
    """Backup /etc/hosts file."""
    return backup_hosts_file()


# ---------------------------------------------------------------------------
# /etc/resolv.conf
# ---------------------------------------------------------------------------


@router.get("/resolv", response_model=FileContent)
async def resolv_read() -> FileContent:
    """Read /etc/resolv.conf file."""
    try:
        return read_resolv_conf()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/resolv", response_model=OperationResult)
async def resolv_update(request: FileUpdateRequest) -> OperationResult:
    """Update /etc/resolv.conf file."""
    return update_resolv_conf(request.content)


@router.post("/resolv/backup", response_model=BackupResult)
async def resolv_backup() -> BackupResult:
    """Backup /etc/resolv.conf file."""
    return backup_resolv_conf()


@router.get("/resolv/nameservers", response_model=ResolvConfInfo)
async def resolv_nameservers() -> ResolvConfInfo:
    """Get parsed nameserver list from /etc/resolv.conf."""
    return get_nameservers()


@router.put("/resolv/nameservers", response_model=OperationResult)
async def resolv_nameservers_update(
    request: NameserverUpdateRequest,
) -> OperationResult:
    """Update nameserver entries in /etc/resolv.conf."""
    return update_nameservers(request.nameservers)


# ---------------------------------------------------------------------------
# Ulimit
# ---------------------------------------------------------------------------


@router.get("/ulimit", response_model=UlimitAllResponse)
async def ulimit_get_all() -> UlimitAllResponse:
    """Get all ulimit values (soft and hard)."""
    return await get_ulimit_all()


@router.get("/ulimit/{option}", response_model=UlimitEntry)
async def ulimit_get(option: str) -> UlimitEntry:
    """Get a specific ulimit value. Option: -n, -u, -v, -s, -c."""
    try:
        return await get_ulimit(option)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/ulimit", response_model=OperationResult)
async def ulimit_set(request: UlimitSetRequest) -> OperationResult:
    """Set a ulimit value (persists to /etc/security/limits.conf)."""
    return await set_ulimit(request.option, request.value)


@router.put("/ulimit/nofile", response_model=LimitsConfResponse)
async def ulimit_set_nofile(request: LimitsConfSetRequest) -> LimitsConfResponse:
    """Set max open files (nofile) for a user or all users in limits.conf."""
    return set_user_max_open_files(request)


# ---------------------------------------------------------------------------
# Host Inspection
# ---------------------------------------------------------------------------


@router.get("/inspect", response_model=InspectResult)
async def host_inspect() -> InspectResult:
    """Perform a comprehensive host inspection.

    Collects hostname, IP addresses, nameservers, environment variables,
    disk partitions, resource usage, process list, ulimits, sysctl.conf,
    network interfaces, uname, /etc/passwd, and /etc/hosts.
    """
    return await inspect_host()
