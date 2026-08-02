"""Service management API routes (systemd)."""

from fastapi import APIRouter, HTTPException

from app.servicemgr import service
from app.servicemgr.schemas import (
    MANAGED_PREFIX,
    EnabledRequest,
    OperationResult,
    ServiceSpec,
    ServiceStatus,
)

router = APIRouter(prefix="/service", tags=["service"])


def _guard(name: str) -> None:
    """Reject non-managed unit names early (403)."""
    if not name.startswith(MANAGED_PREFIX):
        raise HTTPException(
            status_code=403, detail=f"managed unit must start with '{MANAGED_PREFIX}'"
        )


def _require_exists(name: str) -> None:
    """Raise 404 if the unit file does not exist."""
    if not service.unit_exists(name):
        raise HTTPException(status_code=404, detail=f"service not found: {name}")


@router.post("", response_model=ServiceStatus)
async def create(spec: ServiceSpec) -> ServiceStatus:
    """Create or update a managed systemd unit (daemon-reload, optional enable/start)."""
    _guard(spec.name)
    try:
        return await service.create_or_update(spec)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{name}/start", response_model=ServiceStatus)
async def start(name: str) -> ServiceStatus:
    """Start a managed service."""
    _guard(name)
    _require_exists(name)
    return await service.start(name)


@router.post("/{name}/stop", response_model=ServiceStatus)
async def stop(name: str) -> ServiceStatus:
    """Stop a managed service."""
    _guard(name)
    _require_exists(name)
    return await service.stop(name)


@router.post("/{name}/restart", response_model=ServiceStatus)
async def restart(name: str) -> ServiceStatus:
    """Restart a managed service."""
    _guard(name)
    _require_exists(name)
    return await service.restart(name)


@router.put("/{name}/enabled", response_model=OperationResult)
async def set_enabled(name: str, req: EnabledRequest) -> OperationResult:
    """Enable or disable a managed service on boot."""
    _guard(name)
    _require_exists(name)
    return await service.set_enabled(name, req.enabled)


@router.get("/{name}", response_model=ServiceStatus)
async def status(name: str) -> ServiceStatus:
    """Query a managed service's status."""
    _guard(name)
    _require_exists(name)
    return await service.status(name)


@router.get("", response_model=list[ServiceStatus])
async def list_services() -> list[ServiceStatus]:
    """List all servicemgr-managed services."""
    return await service.list_managed()


@router.delete("/{name}", response_model=OperationResult)
async def remove(name: str) -> OperationResult:
    """Stop, disable, and remove a managed service."""
    _guard(name)
    _require_exists(name)
    return await service.remove(name)
