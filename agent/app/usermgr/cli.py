"""User management CLI.

Usage:
    python -m app.usermgr.cli <command> [options]

Commands:
    backup                                Backup /etc/passwd, shadow, group, gshadow
    sudo <username>                       Grant sudo privileges to a user

    users list                            List all users
    users info <username>                 Show user detail with groups
    users create <username> [options]     Create a new user
    users delete <username> [--remove-home]  Delete a user

    ssh keygen <username>                 Generate SSH key pair
    ssh read-key <username>               Read SSH key files (id_rsa, .pub)
    ssh delete-key <username>             Delete .ssh directory
    ssh passwordless <username>           Configure passwordless login
    ssh read-authorized <username>        Read authorized_keys
    ssh add-authorized <username> <key>   Add key to authorized_keys

    groups list                           List all groups
"""

import argparse
import asyncio
import json
import sys

from app.usermgr import service


def _to_json(obj) -> str:
    """Convert a pydantic model (or list) to JSON string."""
    if isinstance(obj, list):
        return json.dumps([o.model_dump() for o in obj], indent=2, ensure_ascii=False)
    return json.dumps(obj.model_dump(), indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def cmd_backup(_args: argparse.Namespace) -> None:
    result = service.backup_user_files()
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Sudo
# ---------------------------------------------------------------------------


def cmd_sudo(args: argparse.Namespace) -> None:
    result = asyncio.run(service.grant_sudo(args.username))
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def cmd_users_list(_args: argparse.Namespace) -> None:
    result = service.list_users()
    print(_to_json(result))


def cmd_users_info(args: argparse.Namespace) -> None:
    result = service.get_user_detail(args.username)
    if result is None:
        print(f"Error: User not found: {args.username}", file=sys.stderr)
        sys.exit(1)
    print(_to_json(result))


def cmd_users_create(args: argparse.Namespace) -> None:
    result = asyncio.run(
        service.create_user(
            username=args.username,
            group=args.group,
            shell=args.shell,
            create_home=not args.no_home,
            home=args.home,
            comment=args.comment or "",
        )
    )
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_users_delete(args: argparse.Namespace) -> None:
    result = asyncio.run(service.delete_user(args.username, remove_home=args.remove_home))
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


# ---------------------------------------------------------------------------
# SSH
# ---------------------------------------------------------------------------


def cmd_ssh_keygen(args: argparse.Namespace) -> None:
    result = asyncio.run(
        service.generate_ssh_key(
            username=args.username,
            key_type=args.type,
            bits=args.bits,
            comment=args.comment or "",
        )
    )
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_ssh_read_key(args: argparse.Namespace) -> None:
    try:
        result = service.read_ssh_keys(args.username)
        print(_to_json(result))
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_ssh_delete_key(args: argparse.Namespace) -> None:
    result = service.delete_ssh_keys(args.username)
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_ssh_passwordless(args: argparse.Namespace) -> None:
    result = asyncio.run(service.set_passwordless_login(args.username))
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


def cmd_ssh_read_authorized(args: argparse.Namespace) -> None:
    try:
        result = service.read_authorized_keys(args.username)
        print(_to_json(result))
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_ssh_add_authorized(args: argparse.Namespace) -> None:
    result = service.add_authorized_key(args.username, args.key)
    print(_to_json(result))
    if not result.success:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def cmd_groups_list(_args: argparse.Namespace) -> None:
    result = service.list_groups()
    print(_to_json(result))


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="argus-user",
        description="Argus RAG Studio Agent - User management",
    )
    sub = parser.add_subparsers(dest="group", required=True)

    # --- backup ---
    sub.add_parser("backup", help="Backup user/group files")

    # --- sudo ---
    sudo_p = sub.add_parser("sudo", help="Grant sudo privileges")
    sudo_p.add_argument("username", help="Username to grant sudo")

    # --- users ---
    users_parser = sub.add_parser("users", help="User management")
    users_sub = users_parser.add_subparsers(dest="action", required=True)

    users_sub.add_parser("list", help="List all users")

    info_p = users_sub.add_parser("info", help="Show user detail")
    info_p.add_argument("username", help="Username")

    create_p = users_sub.add_parser("create", help="Create a new user")
    create_p.add_argument("username", help="Username to create")
    create_p.add_argument("-g", "--group", help="Primary group (default: same as username)")
    create_p.add_argument("-s", "--shell", default="/bin/bash", help="Login shell")
    create_p.add_argument("--no-home", action="store_true", help="Do not create home directory")
    create_p.add_argument("-d", "--home", help="Home directory path")
    create_p.add_argument("-c", "--comment", help="User comment (GECOS)")

    delete_p = users_sub.add_parser("delete", help="Delete a user")
    delete_p.add_argument("username", help="Username to delete")
    delete_p.add_argument("-r", "--remove-home", action="store_true", help="Remove home directory")

    # --- ssh ---
    ssh_parser = sub.add_parser("ssh", help="SSH key and access management")
    ssh_sub = ssh_parser.add_subparsers(dest="action", required=True)

    keygen_p = ssh_sub.add_parser("keygen", help="Generate SSH key pair")
    keygen_p.add_argument("username", help="Username")
    keygen_p.add_argument("-t", "--type", default="rsa", help="Key type (rsa, ed25519, ecdsa)")
    keygen_p.add_argument("-b", "--bits", type=int, default=4096, help="Key size in bits")
    keygen_p.add_argument("-c", "--comment", help="Key comment")

    read_key_p = ssh_sub.add_parser("read-key", help="Read SSH key files")
    read_key_p.add_argument("username", help="Username")

    del_key_p = ssh_sub.add_parser("delete-key", help="Delete .ssh directory")
    del_key_p.add_argument("username", help="Username")

    pwless_p = ssh_sub.add_parser("passwordless", help="Configure passwordless login")
    pwless_p.add_argument("username", help="Username")

    read_auth_p = ssh_sub.add_parser("read-authorized", help="Read authorized_keys")
    read_auth_p.add_argument("username", help="Username")

    add_auth_p = ssh_sub.add_parser("add-authorized", help="Add key to authorized_keys")
    add_auth_p.add_argument("username", help="Username")
    add_auth_p.add_argument("key", help="Public key string")

    # --- groups ---
    groups_parser = sub.add_parser("groups", help="Group management")
    groups_sub = groups_parser.add_subparsers(dest="action", required=True)

    groups_sub.add_parser("list", help="List all groups")

    return parser


_DISPATCH = {
    ("backup", None): cmd_backup,
    ("sudo", None): cmd_sudo,
    ("users", "list"): cmd_users_list,
    ("users", "info"): cmd_users_info,
    ("users", "create"): cmd_users_create,
    ("users", "delete"): cmd_users_delete,
    ("ssh", "keygen"): cmd_ssh_keygen,
    ("ssh", "read-key"): cmd_ssh_read_key,
    ("ssh", "delete-key"): cmd_ssh_delete_key,
    ("ssh", "passwordless"): cmd_ssh_passwordless,
    ("ssh", "read-authorized"): cmd_ssh_read_authorized,
    ("ssh", "add-authorized"): cmd_ssh_add_authorized,
    ("groups", "list"): cmd_groups_list,
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
