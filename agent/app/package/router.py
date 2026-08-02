"""Package management API routes."""

from fastapi import APIRouter

from app.package.schemas import (
    PackageActionResult,
    PackageInfo,
    PackageManager,
    PackageRequest,
)
from app.package.service import list_installed_packages, manage_package

router = APIRouter(prefix="/package", tags=["package"])


@router.post("/manage", response_model=PackageActionResult)
async def manage(request: PackageRequest) -> PackageActionResult:
    """Install, remove, or update a package."""
    return await manage_package(
        name=request.name,
        action=request.action,
        manager=request.manager,
    )


@router.get("/list", response_model=list[PackageInfo])
async def list_packages(
    manager: PackageManager | None = None,
) -> list[PackageInfo]:
    """List all installed packages."""
    return await list_installed_packages(manager=manager)
