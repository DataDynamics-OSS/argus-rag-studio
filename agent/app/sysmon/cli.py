"""System monitoring CLI.

Provides command-line access to all sysmon operations.
All output is JSON formatted for scripting and piping.

Usage:
    python -m app.sysmon.cli <command> [options]

Commands:
    dmesg [--lines N] [--level LEVEL]    Capture dmesg output
    cpu [--interval N]                    CPU usage (top-style)
    cores [--interval N]                  Per-core CPU usage (htop-style)
    network                               Network usage per interface
    network-errors                        Network error counters
    processes [--sort FIELD] [--limit N]  Process resource usage
    disk                                  Disk partition info
"""

import argparse
import asyncio
import json
import sys

from app.sysmon import service


def _to_json(obj) -> str:
    """Convert a pydantic model to JSON string."""
    return json.dumps(obj.model_dump(), indent=2, ensure_ascii=False)


def cmd_dmesg(args: argparse.Namespace) -> None:
    result = asyncio.run(service.get_dmesg(lines=args.lines, level=args.level))
    print(_to_json(result))


def cmd_cpu(args: argparse.Namespace) -> None:
    result = service.get_cpu_usage(interval=args.interval)
    print(_to_json(result))


def cmd_cores(args: argparse.Namespace) -> None:
    result = service.get_cpu_core_usage(interval=args.interval)
    print(_to_json(result))


def cmd_network(_args: argparse.Namespace) -> None:
    result = service.get_network_usage()
    print(_to_json(result))


def cmd_network_errors(_args: argparse.Namespace) -> None:
    result = asyncio.run(service.get_network_errors())
    print(_to_json(result))


def cmd_processes(args: argparse.Namespace) -> None:
    result = service.get_process_list(sort_by=args.sort, limit=args.limit)
    print(_to_json(result))


def cmd_disk(_args: argparse.Namespace) -> None:
    result = service.get_disk_partitions()
    print(_to_json(result))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="argus-sysmon",
        description="Argus RAG Studio Agent - System monitoring",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # dmesg
    dmesg_p = sub.add_parser("dmesg", help="Capture dmesg output")
    dmesg_p.add_argument("--lines", type=int, default=200, help="Number of lines (default: 200)")
    dmesg_p.add_argument(
        "--level", type=str, default=None, help="Filter by level (err, warn, info)"
    )

    # cpu
    cpu_p = sub.add_parser("cpu", help="CPU usage (top-style)")
    cpu_p.add_argument(
        "--interval", type=float, default=0.5, help="Measurement interval in seconds"
    )

    # cores
    cores_p = sub.add_parser("cores", help="Per-core CPU usage (htop-style)")
    cores_p.add_argument(
        "--interval", type=float, default=0.5, help="Measurement interval in seconds"
    )

    # network
    sub.add_parser("network", help="Network usage per interface")

    # network-errors
    sub.add_parser("network-errors", help="Network error counters per interface")

    # processes
    proc_p = sub.add_parser("processes", help="Process resource usage")
    proc_p.add_argument(
        "--sort",
        type=str,
        default="cpu_percent",
        choices=["cpu_percent", "memory_percent", "rss", "pid"],
        help="Sort field (default: cpu_percent)",
    )
    proc_p.add_argument(
        "--limit", type=int, default=50, help="Max processes to return (default: 50)"
    )

    # disk
    sub.add_parser("disk", help="Disk partition info")

    return parser


_DISPATCH = {
    "dmesg": cmd_dmesg,
    "cpu": cmd_cpu,
    "cores": cmd_cores,
    "network": cmd_network,
    "network-errors": cmd_network_errors,
    "processes": cmd_processes,
    "disk": cmd_disk,
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
