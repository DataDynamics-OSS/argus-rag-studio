"""File and directory management CLI.

Usage:
    python -m app.filemgr.cli <command> [options]

Commands:
    dir create <path>                  Create a directory
        [--mode 755] [--no-parents]
    dir delete <path>                  Delete a directory
        [--recursive]
    dir info <path>                    Show directory info

    chown <path> [-o owner] [-g group] Change ownership
        [--recursive]
    chmod <path> <mode>                Change permissions
        [--recursive]

    link <target> <link-path>          Create a symbolic link

    file upload <path> <source-file>   Upload a file
        [--mode 644]
    file download <path>               Download a file (base64 to stdout)
    file delete <path>                 Delete a file
    file info <path>                   Show file info

    archive <source-dir> <dest-file>   Compress a directory
        [--format zip|tar|tar.gz|tar.bz2]
"""

import argparse
import asyncio
import base64
import json
import sys

from app.filemgr import service
from app.filemgr.schemas import ArchiveCreateRequest


def _to_json(obj) -> str:
    """Convert a pydantic model to JSON string."""
    return json.dumps(obj.model_dump(), indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Directory commands
# ---------------------------------------------------------------------------


def cmd_dir_create(args: argparse.Namespace) -> None:
    result = service.create_directory(args.path, parents=not args.no_parents, mode=args.mode)
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_dir_delete(args: argparse.Namespace) -> None:
    result = service.delete_directory(args.path, recursive=args.recursive)
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_dir_info(args: argparse.Namespace) -> None:
    try:
        result = service.get_file_info(args.path)
        print(_to_json(result))
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_dir_list(args: argparse.Namespace) -> None:
    try:
        result = service.list_directory(args.path)
        print(_to_json(result))
    except (FileNotFoundError, NotADirectoryError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Ownership / permissions commands
# ---------------------------------------------------------------------------


def cmd_chown(args: argparse.Namespace) -> None:
    result = asyncio.run(
        service.chown(args.path, owner=args.owner, group=args.group, recursive=args.recursive)
    )
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_chmod(args: argparse.Namespace) -> None:
    result = asyncio.run(service.chmod(args.path, args.mode, recursive=args.recursive))
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Link command
# ---------------------------------------------------------------------------


def cmd_link(args: argparse.Namespace) -> None:
    result = service.create_link(args.target, args.link_path)
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


# ---------------------------------------------------------------------------
# File commands
# ---------------------------------------------------------------------------


def cmd_file_upload(args: argparse.Namespace) -> None:
    with open(args.source, "rb") as f:
        data = f.read()
    content = base64.b64encode(data).decode("ascii")
    result = service.upload_file(args.path, content, is_base64=True, mode=args.mode)
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_file_download(args: argparse.Namespace) -> None:
    try:
        result = service.download_file(args.path)
        if args.output:
            data = base64.b64decode(result.content)
            with open(args.output, "wb") as f:
                f.write(data)
            print(f"Downloaded to {args.output} ({result.size} bytes)")
        else:
            print(_to_json(result))
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_file_delete(args: argparse.Namespace) -> None:
    result = service.delete_file(args.path)
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_file_info(args: argparse.Namespace) -> None:
    try:
        result = service.get_file_info(args.path)
        print(_to_json(result))
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Archive command
# ---------------------------------------------------------------------------


def cmd_archive(args: argparse.Namespace) -> None:
    request = ArchiveCreateRequest(
        source_path=args.source,
        dest_path=args.dest,
        format=args.format,
    )
    result = asyncio.run(service.create_archive(request))
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Exec command
# ---------------------------------------------------------------------------


def cmd_exec(args: argparse.Namespace) -> None:
    timeout = args.timeout if args.timeout else None
    result = asyncio.run(service.execute_command(args.command, cwd=args.cwd, timeout=timeout))
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="argus-rag-studio-file",
        description="Argus RAG Studio Agent - File and directory management",
    )
    sub = parser.add_subparsers(dest="group", required=True)

    # --- dir ---
    dir_parser = sub.add_parser("dir", help="Directory management")
    dir_sub = dir_parser.add_subparsers(dest="action", required=True)

    dir_create_p = dir_sub.add_parser("create", help="Create a directory")
    dir_create_p.add_argument("path", help="Directory path")
    dir_create_p.add_argument("--mode", default=None, help="Permissions (e.g. 755)")
    dir_create_p.add_argument(
        "--no-parents", action="store_true", help="Do not create parent directories"
    )

    dir_delete_p = dir_sub.add_parser("delete", help="Delete a directory")
    dir_delete_p.add_argument("path", help="Directory path")
    dir_delete_p.add_argument("--recursive", "-r", action="store_true", help="Delete recursively")

    dir_info_p = dir_sub.add_parser("info", help="Show directory info")
    dir_info_p.add_argument("path", help="Directory path")

    dir_list_p = dir_sub.add_parser("list", help="List directory contents")
    dir_list_p.add_argument("path", help="Directory path")

    # --- chown ---
    chown_p = sub.add_parser("chown", help="Change ownership")
    chown_p.add_argument("path", help="File or directory path")
    chown_p.add_argument("-o", "--owner", default=None, help="New owner")
    chown_p.add_argument("-g", "--group", default=None, help="New group")
    chown_p.add_argument("--recursive", "-r", action="store_true", help="Apply recursively")

    # --- chmod ---
    chmod_p = sub.add_parser("chmod", help="Change permissions")
    chmod_p.add_argument("path", help="File or directory path")
    chmod_p.add_argument("mode", help="Permission mode (e.g. 755)")
    chmod_p.add_argument("--recursive", "-r", action="store_true", help="Apply recursively")

    # --- link ---
    link_p = sub.add_parser("link", help="Create a symbolic link")
    link_p.add_argument("target", help="Target path (existing file/directory)")
    link_p.add_argument("link_path", help="Symbolic link path")

    # --- file ---
    file_parser = sub.add_parser("file", help="File management")
    file_sub = file_parser.add_subparsers(dest="action", required=True)

    upload_p = file_sub.add_parser("upload", help="Upload a file")
    upload_p.add_argument("path", help="Destination path")
    upload_p.add_argument("source", help="Source file to upload")
    upload_p.add_argument("--mode", default=None, help="File permissions (e.g. 644)")

    download_p = file_sub.add_parser("download", help="Download a file")
    download_p.add_argument("path", help="File path to download")
    download_p.add_argument("-o", "--output", default=None, help="Output file path")

    delete_p = file_sub.add_parser("delete", help="Delete a file")
    delete_p.add_argument("path", help="File path")

    info_p = file_sub.add_parser("info", help="Show file info")
    info_p.add_argument("path", help="File path")

    # --- archive ---
    archive_p = sub.add_parser("archive", help="Compress a directory")
    archive_p.add_argument("source", help="Source directory")
    archive_p.add_argument("dest", help="Destination archive file")
    archive_p.add_argument(
        "--format", "-f", default="zip", help="Format: zip, tar, tar.gz, tar.bz2 (default: zip)"
    )

    # --- exec ---
    exec_p = sub.add_parser("exec", help="Execute a program")
    exec_p.add_argument("command", help="Command to execute")
    exec_p.add_argument("--cwd", default=None, help="Working directory")
    exec_p.add_argument(
        "--timeout", "-t", type=int, default=0, help="Timeout in seconds (default: config value)"
    )

    return parser


_DISPATCH = {
    ("dir", "create"): cmd_dir_create,
    ("dir", "delete"): cmd_dir_delete,
    ("dir", "info"): cmd_dir_info,
    ("dir", "list"): cmd_dir_list,
    ("chown", None): cmd_chown,
    ("chmod", None): cmd_chmod,
    ("link", None): cmd_link,
    ("file", "upload"): cmd_file_upload,
    ("file", "download"): cmd_file_download,
    ("file", "delete"): cmd_file_delete,
    ("file", "info"): cmd_file_info,
    ("archive", None): cmd_archive,
    ("exec", None): cmd_exec,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    action = getattr(args, "action", None)
    handler = _DISPATCH.get((args.group, action))
    if handler is None:
        parser.print_help()
        sys.exit(1)
    handler(args)


if __name__ == "__main__":
    main()
