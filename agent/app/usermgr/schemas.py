"""User management schemas."""

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------


class OperationResult(BaseModel):
    """Generic success/failure result."""

    success: bool
    message: str


class BackupResult(BaseModel):
    """Result of a file backup operation."""

    success: bool
    backup_path: str
    message: str


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class UserInfo(BaseModel):
    """Parsed user entry from /etc/passwd."""

    username: str
    uid: int
    gid: int
    comment: str = ""
    home: str = ""
    shell: str = ""


class UserDetail(BaseModel):
    """Detailed user information including group membership."""

    username: str
    uid: int
    gid: int
    comment: str = ""
    home: str = ""
    shell: str = ""
    primary_group: str = ""
    groups: list[str] = Field(default_factory=list)
    has_sudo: bool = False


class UserCreateRequest(BaseModel):
    """Request to create a new user."""

    username: str = Field(..., description="Username to create")
    group: str | None = Field(None, description="Primary group (default: same as username)")
    shell: str = Field("/bin/bash", description="Login shell")
    create_home: bool = Field(True, description="Create home directory")
    home: str | None = Field(None, description="Home directory path (default: /home/<username>)")
    comment: str = Field("", description="User comment (GECOS field)")


class UserDeleteRequest(BaseModel):
    """Request to delete a user."""

    username: str = Field(..., description="Username to delete")
    remove_home: bool = Field(False, description="Remove home directory and mail spool")


class SudoGrantRequest(BaseModel):
    """Request to grant sudo privileges to a user."""

    username: str = Field(..., description="Username to grant sudo")


# ---------------------------------------------------------------------------
# SSH Key
# ---------------------------------------------------------------------------


class SshKeyResult(BaseModel):
    """Result of SSH key generation."""

    success: bool
    message: str
    private_key_path: str = ""
    public_key_path: str = ""


class SshKeyContent(BaseModel):
    """SSH key file contents."""

    username: str
    private_key: str = Field("", description="id_rsa content")
    public_key: str = Field("", description="id_rsa.pub content")


class SshKeyGenRequest(BaseModel):
    """Request to generate SSH keys for a user."""

    username: str = Field(..., description="Username")
    key_type: str = Field("rsa", description="Key type (rsa, ed25519, ecdsa)")
    bits: int = Field(4096, description="Key size in bits (for RSA)")
    comment: str = Field("", description="Key comment")


class SshKeyDeleteRequest(BaseModel):
    """Request to delete SSH keys for a user."""

    username: str = Field(..., description="Username")


class AuthorizedKeysContent(BaseModel):
    """Content of authorized_keys file."""

    username: str
    content: str
    key_count: int = 0


class AuthorizedKeyAddRequest(BaseModel):
    """Request to add a key to authorized_keys."""

    username: str = Field(..., description="Username")
    public_key: str = Field(..., description="Public key string to add")


class PasswordlessLoginRequest(BaseModel):
    """Request to configure passwordless login for a user."""

    username: str = Field(..., description="Username")


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------


class GroupInfo(BaseModel):
    """Parsed group entry from /etc/group."""

    groupname: str
    gid: int
    members: list[str] = Field(default_factory=list)
