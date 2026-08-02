"""Package management service."""

import asyncio
import logging
import shutil

from app.package.schemas import (
    PackageAction,
    PackageActionResult,
    PackageInfo,
    PackageManager,
)

logger = logging.getLogger(__name__)


def detect_package_manager() -> PackageManager:
    """Detect the system's package manager."""
    if shutil.which("dnf"):
        return PackageManager.DNF
    if shutil.which("yum"):
        return PackageManager.YUM
    if shutil.which("apt"):
        return PackageManager.APT
    raise RuntimeError("No supported package manager found")


def _build_command(manager: PackageManager, action: PackageAction, name: str) -> str:
    """Build the package management command."""
    cmd_map = {
        PackageManager.DNF: {
            PackageAction.INSTALL: f"dnf install -y {name}",
            PackageAction.REMOVE: f"dnf remove -y {name}",
            PackageAction.UPDATE: f"dnf update -y {name}",
        },
        PackageManager.YUM: {
            PackageAction.INSTALL: f"yum install -y {name}",
            PackageAction.REMOVE: f"yum remove -y {name}",
            PackageAction.UPDATE: f"yum update -y {name}",
        },
        PackageManager.APT: {
            PackageAction.INSTALL: f"apt-get install -y {name}",
            PackageAction.REMOVE: f"apt-get remove -y {name}",
            PackageAction.UPDATE: f"apt-get upgrade -y {name}",
        },
    }
    return cmd_map[manager][action]


async def manage_package(
    name: str,
    action: PackageAction,
    manager: PackageManager | None = None,
) -> PackageActionResult:
    """Install, remove, or update a package."""
    mgr = manager or detect_package_manager()
    cmd = _build_command(mgr, action, name)

    logger.info("Package operation: %s %s (via %s)", action.value, name, mgr.value)

    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    exit_code = process.returncode or 0
    output = stdout.decode(errors="replace") + stderr.decode(errors="replace")

    return PackageActionResult(
        success=exit_code == 0,
        package=name,
        action=action,
        message=output[-2048:] if len(output) > 2048 else output,
        exit_code=exit_code,
    )


async def list_installed_packages(
    manager: PackageManager | None = None,
) -> list[PackageInfo]:
    """List installed packages."""
    mgr = manager or detect_package_manager()

    if mgr in (PackageManager.DNF, PackageManager.YUM):
        cmd = "rpm -qa --queryformat '%{NAME}\\t%{VERSION}-%{RELEASE}\\t%{ARCH}\\t%{SUMMARY}\\n'"
    else:
        cmd = "dpkg-query -W -f='${Package}\\t${Version}\\t${Architecture}\\t${Description}\\n'"

    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await process.communicate()

    packages = []
    for line in stdout.decode(errors="replace").strip().splitlines():
        parts = line.split("\t", 3)
        if len(parts) >= 3:
            packages.append(
                PackageInfo(
                    name=parts[0],
                    version=parts[1],
                    architecture=parts[2],
                    description=parts[3] if len(parts) > 3 else "",
                )
            )
    return packages
