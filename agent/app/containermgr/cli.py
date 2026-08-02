"""Container management CLI (Docker/Podman).

Usage:
    python -m app.containermgr.cli <command> [options]

Commands:
    create <spec.json>     Create/run a container from a ContainerSpec JSON ('-' for stdin)
    render <spec.json>     Print the run argv without applying (dry-run)
    start <name>           Start a managed container
    stop <name>            Stop a managed container
    restart <name>         Restart a managed container
    status <name>          Show a managed container status
    list                   List all managed containers
    logs <name> [--tail N] Show container logs
    remove <name>          Stop and remove a container
"""

import argparse
import asyncio
import json
import sys

from app.containermgr import service
from app.containermgr.schemas import ContainerSpec


def _to_json(obj) -> str:
    if isinstance(obj, list):
        return json.dumps([o.model_dump() for o in obj], indent=2, ensure_ascii=False)
    return json.dumps(obj.model_dump(), indent=2, ensure_ascii=False)


def _read_spec(file_path: str) -> ContainerSpec:
    raw = sys.stdin.read() if file_path == "-" else open(file_path, encoding="utf-8").read()
    return ContainerSpec.model_validate_json(raw)


def cmd_create(args: argparse.Namespace) -> None:
    print(_to_json(asyncio.run(service.create_or_run(_read_spec(args.spec)))))


def cmd_render(args: argparse.Namespace) -> None:
    spec = _read_spec(args.spec)
    print(" ".join([service.CONTAINER_CMD, *service.render_run_args(spec)]))


def cmd_start(args: argparse.Namespace) -> None:
    print(_to_json(asyncio.run(service.start(args.name))))


def cmd_stop(args: argparse.Namespace) -> None:
    print(_to_json(asyncio.run(service.stop(args.name))))


def cmd_restart(args: argparse.Namespace) -> None:
    print(_to_json(asyncio.run(service.restart(args.name))))


def cmd_status(args: argparse.Namespace) -> None:
    print(_to_json(asyncio.run(service.status(args.name))))


def cmd_list(_args: argparse.Namespace) -> None:
    print(_to_json(asyncio.run(service.list_managed())))


def cmd_logs(args: argparse.Namespace) -> None:
    print(asyncio.run(service.logs(args.name, tail=args.tail)))


def cmd_remove(args: argparse.Namespace) -> None:
    result = asyncio.run(service.remove(args.name))
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="argus-rag-studio-container",
        description="Manage Argus RAG Studio containers (Docker/Podman).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create_p = sub.add_parser("create", help="Create/run from ContainerSpec JSON")
    create_p.add_argument("spec", help="Path to ContainerSpec JSON ('-' for stdin)")

    render_p = sub.add_parser("render", help="Print run argv without applying")
    render_p.add_argument("spec", help="Path to ContainerSpec JSON ('-' for stdin)")

    for name in ("start", "stop", "restart", "status", "remove"):
        p = sub.add_parser(name, help=f"{name} a managed container")
        p.add_argument("name", help="Container name (e.g. argus-rag-embedding-1)")

    logs_p = sub.add_parser("logs", help="Show container logs")
    logs_p.add_argument("name", help="Container name")
    logs_p.add_argument("--tail", type=int, default=200, help="Lines to show (default 200)")

    sub.add_parser("list", help="List all managed containers")
    return parser


_DISPATCH = {
    "create": cmd_create,
    "render": cmd_render,
    "start": cmd_start,
    "stop": cmd_stop,
    "restart": cmd_restart,
    "status": cmd_status,
    "list": cmd_list,
    "logs": cmd_logs,
    "remove": cmd_remove,
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
