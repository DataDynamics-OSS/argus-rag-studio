"""Process management CLI.

Usage:
    python -m app.processmgr.cli <command> [options]

Commands:
    list                              List running processes
        [--sort pid|cpu_percent|memory_rss|name]
        [--limit N] [--user USERNAME]
    detail <pid>                      Show detailed process info
    signal <pid> [--signal SIGTERM]   Send signal to process
    restart <pid>                     Restart process (SIGHUP)
    zombies                           List zombie processes
    kill-user <username>              Kill all processes of a user
        [--signal SIGKILL]
    too-many-open-files               List processes near open file limit
        [--threshold 90]
    cpu                               List processes by CPU usage
        [--limit 50]
"""

import argparse
import json
import sys

from app.processmgr import service


def _to_json(obj) -> str:
    """Convert a pydantic model to JSON string."""
    return json.dumps(obj.model_dump(), indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace) -> None:
    result = service.list_processes(sort_by=args.sort, limit=args.limit, username=args.user)
    print(_to_json(result))


def cmd_detail(args: argparse.Namespace) -> None:
    try:
        result = service.get_process_detail(args.pid)
        print(_to_json(result))
    except ProcessLookupError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_signal(args: argparse.Namespace) -> None:
    result = service.send_signal(args.pid, args.signal)
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_restart(args: argparse.Namespace) -> None:
    result = service.restart_process(args.pid)
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_zombies(_args: argparse.Namespace) -> None:
    result = service.list_zombies()
    print(_to_json(result))


def cmd_kill_user(args: argparse.Namespace) -> None:
    result = service.kill_user_processes(args.username, args.signal)
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_too_many_open_files(args: argparse.Namespace) -> None:
    result = service.list_too_many_open_files(threshold=args.threshold)
    print(_to_json(result))


def cmd_cpu(args: argparse.Namespace) -> None:
    result = service.list_process_cpu(limit=args.limit)
    print(_to_json(result))


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="argus-rag-studio-process",
        description="Argus RAG Studio Agent - Process management",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    list_p = sub.add_parser("list", help="List running processes")
    list_p.add_argument(
        "--sort",
        default="pid",
        choices=["pid", "cpu_percent", "memory_rss", "name", "username"],
        help="Sort field (default: pid)",
    )
    list_p.add_argument("--limit", type=int, default=0, help="Limit results (0=all)")
    list_p.add_argument("--user", default=None, help="Filter by username")

    # detail
    detail_p = sub.add_parser("detail", help="Show detailed process info")
    detail_p.add_argument("pid", type=int, help="Process ID")

    # signal
    signal_p = sub.add_parser("signal", help="Send signal to process")
    signal_p.add_argument("pid", type=int, help="Process ID")
    signal_p.add_argument(
        "--signal", "-s", default="SIGTERM", help="Signal name (default: SIGTERM)"
    )

    # restart
    restart_p = sub.add_parser("restart", help="Restart process (SIGHUP)")
    restart_p.add_argument("pid", type=int, help="Process ID")

    # zombies
    sub.add_parser("zombies", help="List zombie processes")

    # kill-user
    kill_user_p = sub.add_parser("kill-user", help="Kill all processes of a user")
    kill_user_p.add_argument("username", help="Username")
    kill_user_p.add_argument(
        "--signal", "-s", default="SIGKILL", help="Signal name (default: SIGKILL)"
    )

    # too-many-open-files
    tmof_p = sub.add_parser("too-many-open-files", help="List processes near open file limit")
    tmof_p.add_argument(
        "--threshold", type=float, default=90.0, help="Threshold percent (default: 90)"
    )

    # cpu
    cpu_p = sub.add_parser("cpu", help="List processes by CPU usage")
    cpu_p.add_argument("--limit", type=int, default=50, help="Limit results (default: 50)")

    return parser


_DISPATCH = {
    "list": cmd_list,
    "detail": cmd_detail,
    "signal": cmd_signal,
    "restart": cmd_restart,
    "zombies": cmd_zombies,
    "kill-user": cmd_kill_user,
    "too-many-open-files": cmd_too_many_open_files,
    "cpu": cmd_cpu,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    handler = _DISPATCH.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)
    handler(args)


if __name__ == "__main__":
    main()
