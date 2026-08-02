"""Yum repository and package management API routes."""

from fastapi import APIRouter, HTTPException, Query

from app.yum.schemas import (
    OperationResult,
    RepoBackupResult,
    RepoFileContent,
    RepoFileCreateRequest,
    RepoFileInfo,
    RepoFileUpdateRequest,
    YumPackageDetail,
    YumPackageFiles,
    YumPackageInfo,
    YumPackageRequest,
    YumPackageResult,
    YumPackageSearchResult,
)
from app.yum.service import (
    backup_repo_files,
    create_repo_file,
    get_package_info,
    list_installed_packages,
    list_package_files,
    list_repo_files,
    manage_yum_package,
    read_repo_file,
    search_packages,
    update_repo_file,
)

router = APIRouter(prefix="/yum", tags=["yum"])


# ---------------------------------------------------------------------------
# Repository endpoints
# ---------------------------------------------------------------------------


@router.get("/repo", response_model=list[RepoFileInfo])
async def repo_list() -> list[RepoFileInfo]:
    """List all .repo files in /etc/yum.repos.d/."""
    return list_repo_files()


@router.post("/repo", response_model=OperationResult)
async def repo_create(request: RepoFileCreateRequest) -> OperationResult:
    """Create a new .repo file."""
    return create_repo_file(filename=request.filename, content=request.content)


@router.put("/repo", response_model=OperationResult)
async def repo_update(request: RepoFileUpdateRequest) -> OperationResult:
    """Update an existing .repo file."""
    return update_repo_file(filename=request.filename, content=request.content)


@router.get("/repo/{filename}", response_model=RepoFileContent)
async def repo_read(filename: str) -> RepoFileContent:
    """Read the content of a .repo file."""
    try:
        return read_repo_file(filename)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/repo/backup", response_model=RepoBackupResult)
async def repo_backup() -> RepoBackupResult:
    """Backup all .repo files to a zip archive."""
    return backup_repo_files()


# ---------------------------------------------------------------------------
# Package endpoints
# ---------------------------------------------------------------------------


@router.post("/package", response_model=YumPackageResult)
async def package_manage(request: YumPackageRequest) -> YumPackageResult:
    """Install, remove, or upgrade a package via yum."""
    return await manage_yum_package(name=request.name, action=request.action)


@router.get("/package", response_model=list[YumPackageInfo])
async def package_list() -> list[YumPackageInfo]:
    """List all installed RPM packages."""
    return await list_installed_packages()


@router.get("/package/search", response_model=list[YumPackageSearchResult])
async def package_search(
    keyword: str = Query(..., description="Search keyword"),
) -> list[YumPackageSearchResult]:
    """Search installed packages by keyword."""
    return await search_packages(keyword)


@router.get("/package/{name}/info", response_model=YumPackageDetail)
async def package_info(name: str) -> YumPackageDetail:
    """Get detailed metadata for a package."""
    try:
        return await get_package_info(name)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/package/{name}/files", response_model=YumPackageFiles)
async def package_files(name: str) -> YumPackageFiles:
    """List files owned by a package."""
    try:
        return await list_package_files(name)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))
