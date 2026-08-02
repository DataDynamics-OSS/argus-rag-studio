"""Certificate management CLI.

Usage:
    python -m app.certmgr.cli <command> [options]

Commands:
    ca upload <key-file> <crt-file>    Upload CA key and certificate
    ca info                            Show CA certificate information
    ca delete                          Delete all CA certificate files

    host generate --domain <domain>    Generate host certificate
        [-C <country>] [-ST <state>] [-L <locality>]
        [-O <organization>] [-OU <org-unit>]
    host info                          Show host certificate information
    host files                         List host certificate files
    host delete                        Delete all host certificate files
"""

import argparse
import asyncio
import json
import sys

from app.certmgr import service
from app.certmgr.schemas import HostCertRequest


def _to_json(obj) -> str:
    """Convert a pydantic model to JSON string."""
    return json.dumps(obj.model_dump(), indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CA commands
# ---------------------------------------------------------------------------


def cmd_ca_upload(args: argparse.Namespace) -> None:
    with open(args.key_file, encoding="utf-8") as f:
        key_content = f.read()
    with open(args.crt_file, encoding="utf-8") as f:
        crt_content = f.read()

    result = asyncio.run(service.upload_ca(key_content, crt_content))
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_ca_info(_args: argparse.Namespace) -> None:
    result = asyncio.run(service.get_ca_info())
    print(_to_json(result))


def cmd_ca_delete(_args: argparse.Namespace) -> None:
    result = service.delete_ca()
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Host certificate commands
# ---------------------------------------------------------------------------


def cmd_host_generate(args: argparse.Namespace) -> None:
    request = HostCertRequest(
        domain=args.domain,
        country=args.country or "KR",
        state=args.state or "",
        locality=args.locality or "",
        organization=args.organization or "",
        org_unit=args.org_unit or "",
    )
    result = asyncio.run(service.generate_host_cert(request))
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_host_info(_args: argparse.Namespace) -> None:
    result = asyncio.run(service.get_host_cert_info())
    print(_to_json(result))


def cmd_host_files(_args: argparse.Namespace) -> None:
    result = service.list_host_cert_files()
    print(_to_json(result))


def cmd_host_delete(_args: argparse.Namespace) -> None:
    result = service.delete_host_cert()
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="argus-rag-studio-cert",
        description="Argus RAG Studio Agent - Certificate management",
    )
    sub = parser.add_subparsers(dest="group", required=True)

    # --- ca ---
    ca_parser = sub.add_parser("ca", help="CA certificate management")
    ca_sub = ca_parser.add_subparsers(dest="action", required=True)

    upload_p = ca_sub.add_parser("upload", help="Upload CA key and certificate")
    upload_p.add_argument("key_file", help="Path to CA private key file (.key)")
    upload_p.add_argument("crt_file", help="Path to CA certificate file (.crt)")

    ca_sub.add_parser("info", help="Show CA certificate information")
    ca_sub.add_parser("delete", help="Delete all CA certificate files")

    # --- host ---
    host_parser = sub.add_parser("host", help="Host certificate management")
    host_sub = host_parser.add_subparsers(dest="action", required=True)

    gen_p = host_sub.add_parser("generate", help="Generate host certificate")
    gen_p.add_argument("--domain", "-d", required=True, help="Domain name")
    gen_p.add_argument("-C", "--country", default="KR", help="Country code (default: KR)")
    gen_p.add_argument("-ST", "--state", default="", help="State or province")
    gen_p.add_argument("-L", "--locality", default="", help="Locality / city")
    gen_p.add_argument("-O", "--organization", default="", help="Organization name")
    gen_p.add_argument("-OU", "--org-unit", default="", help="Organizational unit")

    host_sub.add_parser("info", help="Show host certificate information")
    host_sub.add_parser("files", help="List host certificate files")
    host_sub.add_parser("delete", help="Delete all host certificate files")

    return parser


_DISPATCH = {
    ("ca", "upload"): cmd_ca_upload,
    ("ca", "info"): cmd_ca_info,
    ("ca", "delete"): cmd_ca_delete,
    ("host", "generate"): cmd_host_generate,
    ("host", "info"): cmd_host_info,
    ("host", "files"): cmd_host_files,
    ("host", "delete"): cmd_host_delete,
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
