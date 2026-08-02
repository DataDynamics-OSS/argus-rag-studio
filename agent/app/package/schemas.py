"""Package management schemas."""

from enum import Enum

from pydantic import BaseModel, Field


class PackageManager(str, Enum):
    """Supported package managers."""

    YUM = "yum"
    DNF = "dnf"
    APT = "apt"


class PackageAction(str, Enum):
    """Package actions."""

    INSTALL = "install"
    REMOVE = "remove"
    UPDATE = "update"


class PackageRequest(BaseModel):
    """Request to manage a package."""

    name: str = Field(..., description="Package name")
    action: PackageAction = Field(..., description="Action to perform")
    manager: PackageManager | None = Field(
        None, description="Package manager to use (auto-detected if not specified)"
    )


class PackageInfo(BaseModel):
    """Information about an installed package."""

    name: str
    version: str
    architecture: str
    description: str = ""


class PackageActionResult(BaseModel):
    """Result of a package action."""

    success: bool
    package: str
    action: PackageAction
    message: str
    exit_code: int
