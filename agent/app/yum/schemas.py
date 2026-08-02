"""Yum repository and package management schemas."""

from enum import Enum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class RepoFileInfo(BaseModel):
    """Summary info of a .repo file in /etc/yum.repos.d/."""

    filename: str
    path: str
    size_bytes: int


class RepoFileContent(BaseModel):
    """Full content of a .repo file."""

    filename: str
    path: str
    content: str


class RepoFileCreateRequest(BaseModel):
    """Request to create a new .repo file."""

    filename: str = Field(
        ...,
        description="Filename (e.g. 'my-repo.repo'). '.repo' suffix is appended if missing.",
    )
    content: str = Field(..., description="Full content of the .repo file")


class RepoFileUpdateRequest(BaseModel):
    """Request to update an existing .repo file."""

    filename: str = Field(..., description="Name of the .repo file to update")
    content: str = Field(..., description="New content for the .repo file")


class RepoBackupResult(BaseModel):
    """Result of a repository backup operation."""

    success: bool
    backup_path: str
    file_count: int
    message: str


# ---------------------------------------------------------------------------
# Package
# ---------------------------------------------------------------------------


class YumPackageAction(str, Enum):
    """Yum package actions."""

    INSTALL = "install"
    REMOVE = "remove"
    UPGRADE = "upgrade"


class YumPackageRequest(BaseModel):
    """Request to install/remove/upgrade a package via yum."""

    name: str = Field(..., description="Package name")
    action: YumPackageAction = Field(..., description="Action to perform")


class YumPackageResult(BaseModel):
    """Result of a yum package operation."""

    success: bool
    package: str
    action: YumPackageAction
    exit_code: int
    output: str


class YumPackageInfo(BaseModel):
    """Information about an installed yum/rpm package."""

    name: str
    version: str
    release: str
    architecture: str
    summary: str = ""


class YumPackageDetail(BaseModel):
    """Detailed metadata for a single package (yum info)."""

    name: str
    version: str
    release: str
    architecture: str
    size: str = ""
    repo: str = ""
    summary: str = ""
    description: str = ""
    license: str = ""
    url: str = ""
    raw: str = ""


class YumPackageFiles(BaseModel):
    """Files owned by a package."""

    package: str
    files: list[str]


class YumPackageSearchResult(BaseModel):
    """Result of a yum search."""

    name: str
    version: str
    summary: str = ""


# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------


class OperationResult(BaseModel):
    """Generic success/failure result."""

    success: bool
    message: str
