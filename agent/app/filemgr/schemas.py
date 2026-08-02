"""File and directory management schemas."""

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------


class OperationResult(BaseModel):
    """Generic operation result."""

    success: bool
    message: str = ""


class FileInfo(BaseModel):
    """File or directory metadata."""

    path: str
    name: str
    is_dir: bool
    is_link: bool = False
    link_target: str | None = None
    size: int = 0
    owner: str = ""
    group: str = ""
    permissions: str = ""
    modified: str = ""


# ---------------------------------------------------------------------------
# Directory operations
# ---------------------------------------------------------------------------


class DirCreateRequest(BaseModel):
    """Directory creation request."""

    path: str = Field(..., description="Absolute path of the directory to create")
    parents: bool = Field(default=True, description="Create parent directories if needed")
    mode: str | None = Field(default=None, description="Permissions (e.g. '755')")


class DirDeleteRequest(BaseModel):
    """Directory deletion request."""

    path: str = Field(..., description="Absolute path of the directory to delete")
    recursive: bool = Field(default=False, description="Delete recursively (rm -rf)")


# ---------------------------------------------------------------------------
# Ownership / permissions
# ---------------------------------------------------------------------------


class ChownRequest(BaseModel):
    """Change ownership request (file or directory)."""

    path: str = Field(..., description="Absolute path")
    owner: str | None = Field(default=None, description="New owner username")
    group: str | None = Field(default=None, description="New group name")
    recursive: bool = Field(default=False, description="Apply recursively")


class ChmodRequest(BaseModel):
    """Change permissions request (file or directory)."""

    path: str = Field(..., description="Absolute path")
    mode: str = Field(..., description="Permission mode (e.g. '755', '644')")
    recursive: bool = Field(default=False, description="Apply recursively")


# ---------------------------------------------------------------------------
# Symlink
# ---------------------------------------------------------------------------


class LinkCreateRequest(BaseModel):
    """Symbolic link creation request."""

    target: str = Field(..., description="Target path (the existing file/directory)")
    link_path: str = Field(..., description="Path of the symbolic link to create")


# ---------------------------------------------------------------------------
# File upload / download
# ---------------------------------------------------------------------------


class FileUploadRequest(BaseModel):
    """File upload request (content as base64 or text)."""

    path: str = Field(..., description="Destination absolute path")
    content: str = Field(..., description="File content (text or base64-encoded)")
    is_base64: bool = Field(default=False, description="True if content is base64-encoded")
    mode: str | None = Field(default=None, description="File permissions (e.g. '644')")


class FileDownloadResponse(BaseModel):
    """File download response."""

    path: str
    name: str
    size: int
    content: str = Field(..., description="File content (base64-encoded)")


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Directory listing
# ---------------------------------------------------------------------------


class DirListResponse(BaseModel):
    """Directory listing response."""

    path: str
    entries: list[FileInfo] = Field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


class ExecRequest(BaseModel):
    """Program execution request."""

    command: str = Field(..., description="Command to execute")
    cwd: str | None = Field(default=None, description="Working directory (optional)")
    timeout: int | None = Field(
        default=None,
        description="Timeout in seconds (optional, uses config default if not specified)",
    )


class ExecResult(BaseModel):
    """Program execution result."""

    success: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    message: str = ""


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


class ArchiveCreateRequest(BaseModel):
    """Archive creation request."""

    source_path: str = Field(..., description="Directory path to compress")
    dest_path: str = Field(..., description="Destination archive file path")
    format: str = Field(
        default="zip",
        description="Archive format: zip, tar, tar.gz, tar.bz2",
    )
