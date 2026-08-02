"""Service management CLI (systemd).

Usage:
    python -m app.servicemgr.cli <command> [options]

Commands:
    create <spec.json>            Create/update a unit from a ServiceSpec JSON file ('-' for stdin)
    start <name>                  Start a managed service
    stop <name>                   Stop a managed service
    restart <name>               Restart a managed service
    status <name>                Show a managed service status
    list                         List all managed services
    enable <name>                Enable a service on boot
    disable <name>               Disable a service on boot
    remove <name>                Stop, disable, and remove a service
    render <spec.json>           Render the unit file without applying (dry-run)
"""

import argparse
import asyncio
import json
import sys

from app.servicemgr import service
from app.servicemgr.schemas import ServiceSpec


def _to_json(obj) -> str:
    """Convert a pydantic model (or list of them) to a JSON string."""
    if isinstance(obj, list):
        return json.dumps([o.model_dump() for o in obj], indent=2, ensure_ascii=False)
    return json.dumps(obj.model_dump(), indent=2, ensure_ascii=False)


def _read_spec(file_path: str) -> ServiceSpec:
    """Load a ServiceSpec from a JSON file path or stdin ('-')."""
    raw = sys.stdin.read() if file_path == "-" else open(file_path, encoding="utf-8").read()
    return ServiceSpec.model_validate_json(raw)


def cmd_create(args: argparse.Namespace) -> None:
    spec = _read_spec(args.spec)
    result = asyncio.run(service.create_or_update(spec))
    print(_to_json(result))


def cmd_render(args: argparse.Namespace) -> None:
    spec = _read_spec(args.spec)
    print(service.render_unit(spec))


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


def cmd_enable(args: argparse.Namespace) -> None:
    result = asyncio.run(service.set_enabled(args.name, True))
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_disable(args: argparse.Namespace) -> None:
    result = asyncio.run(service.set_enabled(args.name, False))
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_remove(args: argparse.Namespace) -> None:
    result = asyncio.run(service.remove(args.name))
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="argus-rag-studio-service",
        description="Manage Argus RAG Studio systemd services.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create_p = sub.add_parser("create", help="Create/update a unit from a ServiceSpec JSON")
    create_p.add_argument("spec", help="Path to ServiceSpec JSON ('-' for stdin)")

    render_p = sub.add_parser("render", help="Render unit file without applying")
    render_p.add_argument("spec", help="Path to ServiceSpec JSON ('-' for stdin)")

    for name in ("start", "stop", "restart", "status", "enable", "disable", "remove"):
        p = sub.add_parser(name, help=f"{name} a managed service")
        p.add_argument("name", help="Unit name (e.g. argus-rag-worker-1)")

    sub.add_parser("list", help="List all managed services")
    return parser


_DISPATCH = {
    "create": cmd_create,
    "render": cmd_render,
    "start": cmd_start,
    "stop": cmd_stop,
    "restart": cmd_restart,
    "status": cmd_status,
    "list": cmd_list,
    "enable": cmd_enable,
    "disable": cmd_disable,
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
