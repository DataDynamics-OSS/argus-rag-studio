"""User management API routes."""

from fastapi import APIRouter, HTTPException

from app.usermgr.schemas import (
    AuthorizedKeyAddRequest,
    AuthorizedKeysContent,
    BackupResult,
    GroupInfo,
    OperationResult,
    SshKeyContent,
    SshKeyGenRequest,
    SshKeyResult,
    SudoGrantRequest,
    UserCreateRequest,
    UserDetail,
    UserInfo,
)
from app.usermgr.service import (
    add_authorized_key,
    backup_user_files,
    create_user,
    delete_ssh_keys,
    delete_user,
    generate_ssh_key,
    get_user_detail,
    grant_sudo,
    list_groups,
    list_users,
    read_authorized_keys,
    read_ssh_keys,
    set_passwordless_login,
)

router = APIRouter(prefix="/user", tags=["user"])


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


@router.post("/backup", response_model=BackupResult)
async def user_backup() -> BackupResult:
    """Backup /etc/passwd, /etc/shadow, /etc/group, /etc/gshadow."""
    return backup_user_files()


# ---------------------------------------------------------------------------
# Sudo
# ---------------------------------------------------------------------------


@router.put("/sudo", response_model=OperationResult)
async def user_sudo_grant(request: SudoGrantRequest) -> OperationResult:
    """Grant sudo privileges to a user."""
    return await grant_sudo(request.username)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@router.get("/users", response_model=list[UserInfo])
async def user_list() -> list[UserInfo]:
    """List all users from /etc/passwd."""
    return list_users()


@router.get("/users/{username}", response_model=UserDetail)
async def user_detail(username: str) -> UserDetail:
    """Get detailed user info including group membership."""
    detail = get_user_detail(username)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"User not found: {username}")
    return detail


@router.post("/users", response_model=OperationResult)
async def user_create(request: UserCreateRequest) -> OperationResult:
    """Create a new system user."""
    return await create_user(
        username=request.username,
        group=request.group,
        shell=request.shell,
        create_home=request.create_home,
        home=request.home,
        comment=request.comment,
    )


@router.delete("/users/{username}", response_model=OperationResult)
async def user_delete(username: str, remove_home: bool = False) -> OperationResult:
    """Delete a system user."""
    return await delete_user(username, remove_home=remove_home)


# ---------------------------------------------------------------------------
# SSH Keys
# ---------------------------------------------------------------------------


@router.post("/users/{username}/ssh-key", response_model=SshKeyResult)
async def user_ssh_keygen(username: str, request: SshKeyGenRequest) -> SshKeyResult:
    """Generate SSH key pair for a user."""
    return await generate_ssh_key(
        username=username,
        key_type=request.key_type,
        bits=request.bits,
        comment=request.comment,
    )


@router.get("/users/{username}/ssh-key", response_model=SshKeyContent)
async def user_ssh_key_read(username: str) -> SshKeyContent:
    """Read SSH key files (id_rsa, id_rsa.pub) for a user."""
    try:
        return read_ssh_keys(username)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/users/{username}/ssh-key", response_model=OperationResult)
async def user_ssh_key_delete(username: str) -> OperationResult:
    """Delete .ssh directory for a user."""
    return delete_ssh_keys(username)


# ---------------------------------------------------------------------------
# Passwordless login
# ---------------------------------------------------------------------------


@router.put("/users/{username}/passwordless", response_model=OperationResult)
async def user_passwordless(username: str) -> OperationResult:
    """Configure passwordless login for a user."""
    return await set_passwordless_login(username)


# ---------------------------------------------------------------------------
# Authorized Keys
# ---------------------------------------------------------------------------


@router.get("/users/{username}/authorized-keys", response_model=AuthorizedKeysContent)
async def user_authorized_keys_read(username: str) -> AuthorizedKeysContent:
    """Read authorized_keys file for a user."""
    try:
        return read_authorized_keys(username)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/users/{username}/authorized-keys", response_model=OperationResult)
async def user_authorized_keys_add(
    username: str, request: AuthorizedKeyAddRequest
) -> OperationResult:
    """Add a public key to a user's authorized_keys."""
    return add_authorized_key(username, request.public_key)


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


@router.get("/groups", response_model=list[GroupInfo])
async def group_list() -> list[GroupInfo]:
    """List all groups from /etc/group."""
    return list_groups()
