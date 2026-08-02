"""File and directory management service."""

import asyncio
import base64
import grp
import logging
import os
import pwd
import shutil
import stat
import zipfile
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.filemgr.schemas import (
    ArchiveCreateRequest,
    DirListResponse,
    ExecResult,
    FileDownloadResponse,
    FileInfo,
    OperationResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _run(cmd: str) -> tuple[int, str, str]:
    """Run a shell command and return (exit_code, stdout, stderr)."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout.decode(errors="replace").strip(),
        stderr.decode(errors="replace").strip(),
    )


def _file_info(path: Path) -> FileInfo:
    """Build FileInfo from a Path object."""
    st = path.lstat()
    is_link = path.is_symlink()

    # Owner/group
    try:
        owner = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        owner = str(st.st_uid)
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        group = str(st.st_gid)

    # Permissions as octal string (e.g. "755")
    perms = stat.S_IMODE(st.st_mode)
    perm_str = f"{perms:o}"

    modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

    return FileInfo(
        path=str(path),
        name=path.name,
        is_dir=path.is_dir(),
        is_link=is_link,
        link_target=str(os.readlink(path)) if is_link else None,
        size=st.st_size,
        owner=owner,
        group=group,
        permissions=perm_str,
        modified=modified,
    )


# ---------------------------------------------------------------------------
# 1. Directory create
# ---------------------------------------------------------------------------


def create_directory(path: str, parents: bool = True, mode: str | None = None) -> OperationResult:
    """Create a directory."""
    p = Path(path)
    try:
        if p.exists():
            return OperationResult(success=False, message=f"Already exists: {path}")
        p.mkdir(parents=parents, exist_ok=False)
        if mode:
            p.chmod(int(mode, 8))
        logger.info("Created directory: %s", path)
        return OperationResult(success=True, message=f"Created directory: {path}")
    except OSError as e:
        return OperationResult(success=False, message=str(e))


# ---------------------------------------------------------------------------
# 2. Directory delete
# ---------------------------------------------------------------------------


def delete_directory(path: str, recursive: bool = False) -> OperationResult:
    """Delete a directory."""
    p = Path(path)
    if not p.exists():
        return OperationResult(success=False, message=f"Not found: {path}")
    if not p.is_dir():
        return OperationResult(success=False, message=f"Not a directory: {path}")

    try:
        if recursive:
            shutil.rmtree(p)
        else:
            p.rmdir()
        logger.info("Deleted directory: %s (recursive=%s)", path, recursive)
        return OperationResult(success=True, message=f"Deleted directory: {path}")
    except OSError as e:
        return OperationResult(success=False, message=str(e))


# ---------------------------------------------------------------------------
# 3. Change ownership (chown)
# ---------------------------------------------------------------------------


async def chown(
    path: str, owner: str | None, group: str | None, recursive: bool = False
) -> OperationResult:
    """Change ownership of a file or directory."""
    p = Path(path)
    if not p.exists():
        return OperationResult(success=False, message=f"Not found: {path}")

    if not owner and not group:
        return OperationResult(success=False, message="Owner or group must be specified")

    ownership = ""
    if owner and group:
        ownership = f"{owner}:{group}"
    elif owner:
        ownership = owner
    else:
        ownership = f":{group}"

    cmd = "chown"
    if recursive:
        cmd += " -R"
    cmd += f" {ownership} {path}"

    exit_code, _, stderr = await _run(cmd)
    if exit_code != 0:
        return OperationResult(success=False, message=f"chown failed: {stderr}")

    logger.info("Changed ownership of %s to %s", path, ownership)
    return OperationResult(success=True, message=f"Changed ownership of {path} to {ownership}")


# ---------------------------------------------------------------------------
# 4. Change permissions (chmod)
# ---------------------------------------------------------------------------


async def chmod(path: str, mode: str, recursive: bool = False) -> OperationResult:
    """Change permissions of a file or directory."""
    p = Path(path)
    if not p.exists():
        return OperationResult(success=False, message=f"Not found: {path}")

    cmd = "chmod"
    if recursive:
        cmd += " -R"
    cmd += f" {mode} {path}"

    exit_code, _, stderr = await _run(cmd)
    if exit_code != 0:
        return OperationResult(success=False, message=f"chmod failed: {stderr}")

    logger.info("Changed permissions of %s to %s", path, mode)
    return OperationResult(success=True, message=f"Changed permissions of {path} to {mode}")


# ---------------------------------------------------------------------------
# 5. Create symbolic link
# ---------------------------------------------------------------------------


def create_link(target: str, link_path: str) -> OperationResult:
    """Create a symbolic link."""
    t = Path(target)
    lp = Path(link_path)

    if not t.exists():
        return OperationResult(success=False, message=f"Target not found: {target}")
    if lp.exists() or lp.is_symlink():
        return OperationResult(success=False, message=f"Link path already exists: {link_path}")

    try:
        lp.symlink_to(t)
        logger.info("Created symlink %s -> %s", link_path, target)
        return OperationResult(success=True, message=f"Created symlink {link_path} -> {target}")
    except OSError as e:
        return OperationResult(success=False, message=str(e))


# ---------------------------------------------------------------------------
# 6. File info
# ---------------------------------------------------------------------------


def get_file_info(path: str) -> FileInfo:
    """Get file or directory metadata."""
    p = Path(path)
    if not p.exists() and not p.is_symlink():
        raise FileNotFoundError(f"Not found: {path}")
    return _file_info(p)


# ---------------------------------------------------------------------------
# 7. File upload
# ---------------------------------------------------------------------------


def upload_file(
    path: str, content: str, is_base64: bool = False, mode: str | None = None
) -> OperationResult:
    """Upload file content to the specified path."""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)

        if is_base64:
            data = base64.b64decode(content)
            p.write_bytes(data)
        else:
            p.write_text(content, encoding="utf-8")

        if mode:
            p.chmod(int(mode, 8))

        logger.info("Uploaded file: %s (%d bytes)", path, p.stat().st_size)
        return OperationResult(success=True, message=f"Uploaded file: {path}")
    except (OSError, ValueError) as e:
        return OperationResult(success=False, message=str(e))


# ---------------------------------------------------------------------------
# 8. File download
# ---------------------------------------------------------------------------


def download_file(path: str) -> FileDownloadResponse:
    """Read file content and return as base64."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    data = p.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return FileDownloadResponse(
        path=str(p),
        name=p.name,
        size=len(data),
        content=encoded,
    )


# ---------------------------------------------------------------------------
# 9. File delete
# ---------------------------------------------------------------------------


def delete_file(path: str) -> OperationResult:
    """Delete a file."""
    p = Path(path)
    if not p.exists():
        return OperationResult(success=False, message=f"Not found: {path}")
    if p.is_dir():
        return OperationResult(success=False, message=f"Is a directory, not a file: {path}")

    try:
        p.unlink()
        logger.info("Deleted file: %s", path)
        return OperationResult(success=True, message=f"Deleted file: {path}")
    except OSError as e:
        return OperationResult(success=False, message=str(e))


# ---------------------------------------------------------------------------
# 10. Directory listing
# ---------------------------------------------------------------------------


def list_directory(path: str) -> DirListResponse:
    """List files and directories in the given path."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Not found: {path}")
    if not p.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")

    entries = []
    for child in sorted(p.iterdir()):
        try:
            entries.append(_file_info(child))
        except OSError:
            continue

    return DirListResponse(
        path=str(p),
        entries=entries,
        total=len(entries),
    )


# ---------------------------------------------------------------------------
# 11. Archive (compress directory)
# ---------------------------------------------------------------------------


async def create_archive(request: ArchiveCreateRequest) -> OperationResult:
    """Compress a directory into an archive file."""
    source = Path(request.source_path)
    dest = Path(request.dest_path)

    if not source.is_dir():
        return OperationResult(success=False, message=f"Source directory not found: {source}")

    dest.parent.mkdir(parents=True, exist_ok=True)

    fmt = request.format.lower()

    try:
        if fmt == "zip":
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
                for file in sorted(source.rglob("*")):
                    zf.write(file, file.relative_to(source))
            logger.info("Created zip archive: %s", dest)
        elif fmt in ("tar", "tar.gz", "tar.bz2"):
            tar_mode = {"tar": "", "tar.gz": "z", "tar.bz2": "j"}[fmt]
            cmd = f"tar -c{tar_mode}f {dest} -C {source.parent} {source.name}"
            exit_code, _, stderr = await _run(cmd)
            if exit_code != 0:
                return OperationResult(success=False, message=f"tar failed: {stderr}")
            logger.info("Created %s archive: %s", fmt, dest)
        else:
            return OperationResult(
                success=False,
                message=f"Unsupported format: {fmt}. Use zip, tar, tar.gz, or tar.bz2",
            )

        return OperationResult(
            success=True,
            message=f"Created archive: {dest} ({dest.stat().st_size} bytes)",
        )
    except OSError as e:
        return OperationResult(success=False, message=str(e))


# ---------------------------------------------------------------------------
# 12. Execute program
# ---------------------------------------------------------------------------


async def execute_command(
    command: str, cwd: str | None = None, timeout: int | None = None
) -> ExecResult:
    """Execute a program and collect output."""
    effective_timeout = timeout if timeout is not None else settings.filemgr_exec_timeout

    if cwd and not Path(cwd).is_dir():
        return ExecResult(
            success=False,
            exit_code=-1,
            message=f"Working directory not found: {cwd}",
        )

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=effective_timeout)
        exit_code = proc.returncode or 0
        stdout_str = stdout.decode(errors="replace")
        stderr_str = stderr.decode(errors="replace")

        logger.info("Executed command: %s (exit_code=%d, cwd=%s)", command, exit_code, cwd)
        return ExecResult(
            success=exit_code == 0,
            exit_code=exit_code,
            stdout=stdout_str,
            stderr=stderr_str,
            message=f"Command completed with exit code {exit_code}",
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logger.warning("Command timed out after %ds: %s", effective_timeout, command)
        return ExecResult(
            success=False,
            exit_code=-1,
            timed_out=True,
            message=f"Command timed out after {effective_timeout} seconds",
        )
    except OSError as e:
        return ExecResult(
            success=False,
            exit_code=-1,
            message=str(e),
        )
