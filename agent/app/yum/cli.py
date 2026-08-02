"""Yum repository and package management CLI.

Provides command-line access to all yum module operations.

Usage:
    python -m app.yum.cli <command> [options]

Commands:
    repo list                         List .repo files
    repo read <filename>              Read a .repo file
    repo create <filename> <file>     Create a .repo file (content from file or stdin)
    repo update <filename> <file>     Update a .repo file (content from file or stdin)
    repo backup                       Backup all .repo files

    package list                      List all installed packages
    package search <keyword>          Search installed packages
    package install <name>            Install a package
    package remove <name>             Remove a package
    package upgrade <name>            Upgrade a package
    package info <name>               Show package metadata
    package files <name>              List files owned by a package
"""

import argparse
import asyncio
import json
import sys

from app.yum import service
from app.yum.schemas import YumPackageAction


def _to_json(obj) -> str:
    """Convert a pydantic model or list of models to JSON string."""
    if isinstance(obj, list):
        return json.dumps([item.model_dump() for item in obj], indent=2, ensure_ascii=False)
    return json.dumps(obj.model_dump(), indent=2, ensure_ascii=False)


def _read_content(file_path: str | None) -> str:
    """Read content from a file path or stdin."""
    if file_path and file_path != "-":
        with open(file_path, encoding="utf-8") as f:
            return f.read()
    return sys.stdin.read()


# ---------------------------------------------------------------------------
# Repository commands
# ---------------------------------------------------------------------------


def cmd_repo_list(_args: argparse.Namespace) -> None:
    result = service.list_repo_files()
    print(_to_json(result))


def cmd_repo_read(args: argparse.Namespace) -> None:
    try:
        result = service.read_repo_file(args.filename)
        print(result.content)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_repo_create(args: argparse.Namespace) -> None:
    content = _read_content(args.file)
    result = service.create_repo_file(args.filename, content)
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_repo_update(args: argparse.Namespace) -> None:
    content = _read_content(args.file)
    result = service.update_repo_file(args.filename, content)
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_repo_backup(_args: argparse.Namespace) -> None:
    result = service.backup_repo_files()
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Package commands
# ---------------------------------------------------------------------------


def cmd_package_list(_args: argparse.Namespace) -> None:
    result = asyncio.run(service.list_installed_packages())
    print(_to_json(result))


def cmd_package_search(args: argparse.Namespace) -> None:
    result = asyncio.run(service.search_packages(args.keyword))
    print(_to_json(result))


def cmd_package_install(args: argparse.Namespace) -> None:
    result = asyncio.run(service.manage_yum_package(args.name, YumPackageAction.INSTALL))
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_package_remove(args: argparse.Namespace) -> None:
    result = asyncio.run(service.manage_yum_package(args.name, YumPackageAction.REMOVE))
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_package_upgrade(args: argparse.Namespace) -> None:
    result = asyncio.run(service.manage_yum_package(args.name, YumPackageAction.UPGRADE))
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_package_info(args: argparse.Namespace) -> None:
    try:
        result = asyncio.run(service.get_package_info(args.name))
        print(_to_json(result))
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_package_files(args: argparse.Namespace) -> None:
    try:
        result = asyncio.run(service.list_package_files(args.name))
        print(_to_json(result))
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="argus-yum",
        description="Argus RAG Studio Agent - Yum repository & package management",
    )
    sub = parser.add_subparsers(dest="group", required=True)

    # --- repo ---
    repo_parser = sub.add_parser("repo", help="Repository file management")
    repo_sub = repo_parser.add_subparsers(dest="action", required=True)

    repo_sub.add_parser("list", help="List .repo files")

    read_p = repo_sub.add_parser("read", help="Read a .repo file")
    read_p.add_argument("filename", help="Name of the .repo file")

    create_p = repo_sub.add_parser("create", help="Create a .repo file")
    create_p.add_argument("filename", help="Name of the .repo file")
    create_p.add_argument("file", nargs="?", default="-", help="Content file (default: stdin)")

    update_p = repo_sub.add_parser("update", help="Update a .repo file")
    update_p.add_argument("filename", help="Name of the .repo file")
    update_p.add_argument("file", nargs="?", default="-", help="Content file (default: stdin)")

    repo_sub.add_parser("backup", help="Backup all .repo files")

    # --- package ---
    pkg_parser = sub.add_parser("package", help="Package management")
    pkg_sub = pkg_parser.add_subparsers(dest="action", required=True)

    pkg_sub.add_parser("list", help="List installed packages")

    search_p = pkg_sub.add_parser("search", help="Search installed packages")
    search_p.add_argument("keyword", help="Search keyword")

    install_p = pkg_sub.add_parser("install", help="Install a package")
    install_p.add_argument("name", help="Package name")

    remove_p = pkg_sub.add_parser("remove", help="Remove a package")
    remove_p.add_argument("name", help="Package name")

    upgrade_p = pkg_sub.add_parser("upgrade", help="Upgrade a package")
    upgrade_p.add_argument("name", help="Package name")

    info_p = pkg_sub.add_parser("info", help="Show package metadata")
    info_p.add_argument("name", help="Package name")

    files_p = pkg_sub.add_parser("files", help="List package files")
    files_p.add_argument("name", help="Package name")

    return parser


_DISPATCH = {
    ("repo", "list"): cmd_repo_list,
    ("repo", "read"): cmd_repo_read,
    ("repo", "create"): cmd_repo_create,
    ("repo", "update"): cmd_repo_update,
    ("repo", "backup"): cmd_repo_backup,
    ("package", "list"): cmd_package_list,
    ("package", "search"): cmd_package_search,
    ("package", "install"): cmd_package_install,
    ("package", "remove"): cmd_package_remove,
    ("package", "upgrade"): cmd_package_upgrade,
    ("package", "info"): cmd_package_info,
    ("package", "files"): cmd_package_files,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    handler = _DISPATCH.get((args.group, args.action))
    if handler is None:
        parser.print_help()
        sys.exit(1)
    handler(args)


if __name__ == "__main__":
    main()
