"""Yum repository and package management service."""

import asyncio
import logging
import os
import zipfile
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.yum.schemas import (
    OperationResult,
    RepoBackupResult,
    RepoFileContent,
    RepoFileInfo,
    YumPackageAction,
    YumPackageDetail,
    YumPackageFiles,
    YumPackageInfo,
    YumPackageResult,
    YumPackageSearchResult,
)

logger = logging.getLogger(__name__)

REPO_DIR = Path("/etc/yum.repos.d")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _run(cmd: str, timeout: int = 120) -> tuple[int, str, str]:
    """Run a shell command and return (exit_code, stdout, stderr)."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "", f"Command timed out after {timeout}s"
    return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")


def _sanitize_filename(filename: str) -> str:
    """Ensure filename ends with .repo and has no path separators."""
    name = os.path.basename(filename)
    if not name.endswith(".repo"):
        name += ".repo"
    return name


# ---------------------------------------------------------------------------
# 1. Repository file list
# ---------------------------------------------------------------------------


def list_repo_files() -> list[RepoFileInfo]:
    """List all .repo files in /etc/yum.repos.d/."""
    if not REPO_DIR.is_dir():
        return []
    results = []
    for f in sorted(REPO_DIR.iterdir()):
        if f.is_file() and f.suffix == ".repo":
            results.append(
                RepoFileInfo(
                    filename=f.name,
                    path=str(f),
                    size_bytes=f.stat().st_size,
                )
            )
    return results


# ---------------------------------------------------------------------------
# 2. Create repo file
# ---------------------------------------------------------------------------


def create_repo_file(filename: str, content: str) -> OperationResult:
    """Create a new .repo file."""
    safe_name = _sanitize_filename(filename)
    target = REPO_DIR / safe_name
    if target.exists():
        return OperationResult(
            success=False,
            message=f"Repository file already exists: {safe_name}",
        )
    try:
        target.write_text(content, encoding="utf-8")
        logger.info("Created repo file: %s", target)
        return OperationResult(success=True, message=f"Created {safe_name}")
    except OSError as e:
        return OperationResult(success=False, message=str(e))


# ---------------------------------------------------------------------------
# 3. Update repo file
# ---------------------------------------------------------------------------


def update_repo_file(filename: str, content: str) -> OperationResult:
    """Update an existing .repo file."""
    safe_name = _sanitize_filename(filename)
    target = REPO_DIR / safe_name
    if not target.exists():
        return OperationResult(
            success=False,
            message=f"Repository file not found: {safe_name}",
        )
    try:
        target.write_text(content, encoding="utf-8")
        logger.info("Updated repo file: %s", target)
        return OperationResult(success=True, message=f"Updated {safe_name}")
    except OSError as e:
        return OperationResult(success=False, message=str(e))


# ---------------------------------------------------------------------------
# 4. Read repo file
# ---------------------------------------------------------------------------


def read_repo_file(filename: str) -> RepoFileContent:
    """Read the content of a .repo file."""
    safe_name = _sanitize_filename(filename)
    target = REPO_DIR / safe_name
    if not target.is_file():
        raise FileNotFoundError(f"Repository file not found: {safe_name}")
    return RepoFileContent(
        filename=safe_name,
        path=str(target),
        content=target.read_text(encoding="utf-8"),
    )


# ---------------------------------------------------------------------------
# 5. Backup repo files
# ---------------------------------------------------------------------------


def backup_repo_files() -> RepoBackupResult:
    """Backup all .repo files to a zip archive."""
    backup_dir = settings.backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y%m%d%H%M%S")
    zip_name = f"yum_{date_str}.zip"
    zip_path = backup_dir / zip_name

    if not REPO_DIR.is_dir():
        return RepoBackupResult(
            success=False,
            backup_path=str(zip_path),
            file_count=0,
            message=f"Repository directory not found: {REPO_DIR}",
        )

    repo_files = [f for f in REPO_DIR.iterdir() if f.is_file() and f.suffix == ".repo"]
    if not repo_files:
        return RepoBackupResult(
            success=False,
            backup_path=str(zip_path),
            file_count=0,
            message="No .repo files to backup",
        )

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in repo_files:
                zf.write(f, f.name)

        logger.info("Backed up %d repo files to %s", len(repo_files), zip_path)
        return RepoBackupResult(
            success=True,
            backup_path=str(zip_path),
            file_count=len(repo_files),
            message=f"Backed up {len(repo_files)} files to {zip_name}",
        )
    except OSError as e:
        return RepoBackupResult(
            success=False,
            backup_path=str(zip_path),
            file_count=0,
            message=str(e),
        )


# ---------------------------------------------------------------------------
# 6. Install package
# 7. Remove package
# 8. Upgrade package
# ---------------------------------------------------------------------------


async def manage_yum_package(name: str, action: YumPackageAction) -> YumPackageResult:
    """Install, remove, or upgrade a package via yum."""
    cmd_map = {
        YumPackageAction.INSTALL: f"yum install -y {name}",
        YumPackageAction.REMOVE: f"yum remove -y {name}",
        YumPackageAction.UPGRADE: f"yum upgrade -y {name}",
    }
    cmd = cmd_map[action]
    logger.info("Yum package operation: %s %s", action.value, name)

    exit_code, stdout, stderr = await _run(cmd, timeout=settings.command_timeout)
    output = stdout + stderr
    return YumPackageResult(
        success=exit_code == 0,
        package=name,
        action=action,
        exit_code=exit_code,
        output=output[-4096:] if len(output) > 4096 else output,
    )


# ---------------------------------------------------------------------------
# 9. Package file list (rpm -ql)
# ---------------------------------------------------------------------------


async def list_package_files(name: str) -> YumPackageFiles:
    """List files owned by an installed package."""
    exit_code, stdout, stderr = await _run(f"rpm -ql {name}")
    if exit_code != 0:
        raise RuntimeError(f"Package not found or error: {stderr.strip()}")
    files = [line for line in stdout.strip().splitlines() if line]
    return YumPackageFiles(package=name, files=files)


# ---------------------------------------------------------------------------
# 10. Package metadata (yum info)
# ---------------------------------------------------------------------------


async def get_package_info(name: str) -> YumPackageDetail:
    """Get detailed metadata for a package."""
    exit_code, stdout, stderr = await _run(f"yum info {name}")
    if exit_code != 0:
        raise RuntimeError(f"Package not found or error: {stderr.strip()}")

    info: dict[str, str] = {}
    current_key = ""
    for line in stdout.splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()
            current_key = key
            info[key] = value
        elif current_key and line.startswith(" "):
            info[current_key] += " " + line.strip()

    return YumPackageDetail(
        name=info.get("name", name),
        version=info.get("version", ""),
        release=info.get("release", ""),
        architecture=info.get("arch", info.get("architecture", "")),
        size=info.get("size", ""),
        repo=info.get("repo", info.get("from repo", "")),
        summary=info.get("summary", ""),
        description=info.get("description", ""),
        license=info.get("license", ""),
        url=info.get("url", ""),
        raw=stdout,
    )


# ---------------------------------------------------------------------------
# 11. Installed packages list (rpm -qa)
# ---------------------------------------------------------------------------


async def list_installed_packages() -> list[YumPackageInfo]:
    """List all installed RPM packages."""
    fmt = r"%{NAME}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SUMMARY}\n"
    exit_code, stdout, stderr = await _run(f"rpm -qa --queryformat '{fmt}'")
    if exit_code != 0:
        raise RuntimeError(f"Failed to list packages: {stderr.strip()}")

    packages = []
    for line in stdout.strip().splitlines():
        parts = line.split("\t", 4)
        if len(parts) >= 4:
            packages.append(
                YumPackageInfo(
                    name=parts[0],
                    version=parts[1],
                    release=parts[2],
                    architecture=parts[3],
                    summary=parts[4] if len(parts) > 4 else "",
                )
            )
    packages.sort(key=lambda p: p.name.lower())
    return packages


# ---------------------------------------------------------------------------
# 12. Search packages (yum search)
# ---------------------------------------------------------------------------


async def search_packages(keyword: str) -> list[YumPackageSearchResult]:
    """Search installed packages by keyword."""
    fmt = r"%{NAME}\t%{VERSION}-%{RELEASE}\t%{SUMMARY}\n"
    exit_code, stdout, _ = await _run(f"rpm -qa --queryformat '{fmt}' | grep -i {keyword}")
    results = []
    for line in stdout.strip().splitlines():
        parts = line.split("\t", 2)
        if len(parts) >= 2:
            results.append(
                YumPackageSearchResult(
                    name=parts[0],
                    version=parts[1],
                    summary=parts[2] if len(parts) > 2 else "",
                )
            )
    results.sort(key=lambda r: r.name.lower())
    return results
