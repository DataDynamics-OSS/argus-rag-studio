"""Tests for usermgr service - users, groups, sudo, SSH keys, backup."""

import zipfile
from unittest.mock import AsyncMock, patch

import pytest

from app.usermgr import service

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sample_passwd(tmp_path):
    """Generate sample /etc/passwd with tmp_path-based home directories."""
    alice_home = tmp_path / "home" / "alice"
    bob_home = tmp_path / "home" / "bob"
    alice_home.mkdir(parents=True, exist_ok=True)
    bob_home.mkdir(parents=True, exist_ok=True)
    return (
        f"root:x:0:0:root:/root:/bin/bash\n"
        f"daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"
        f"alice:x:1000:1000:Alice Kim:{alice_home}:/bin/bash\n"
        f"bob:x:1001:1001:Bob Lee:{bob_home}:/bin/zsh\n"
    )


SAMPLE_GROUP = """\
root:x:0:
daemon:x:1:
alice:x:1000:
bob:x:1001:
wheel:x:10:alice
sudo:x:27:
developers:x:2000:alice,bob
"""


@pytest.fixture
def passwd_file(tmp_path):
    f = tmp_path / "passwd"
    f.write_text(_sample_passwd(tmp_path))
    return f


@pytest.fixture
def group_file(tmp_path):
    f = tmp_path / "group"
    f.write_text(SAMPLE_GROUP)
    return f


@pytest.fixture
def shadow_file(tmp_path):
    f = tmp_path / "shadow"
    f.write_text("root:!:19000:0:99999:7:::\nalice:$6$hash:19000:0:99999:7:::\n")
    return f


@pytest.fixture
def sudoers_dir(tmp_path):
    d = tmp_path / "sudoers.d"
    d.mkdir()
    return d


@pytest.fixture(autouse=True)
def _patch_paths(passwd_file, group_file, shadow_file, sudoers_dir, tmp_path):
    gshadow = tmp_path / "gshadow"
    gshadow.write_text("root:::root\n")
    with (
        patch.object(service, "PASSWD_FILE", passwd_file),
        patch.object(service, "GROUP_FILE", group_file),
        patch.object(service, "SHADOW_FILE", shadow_file),
        patch.object(service, "GSHADOW_FILE", gshadow),
        patch.object(service, "SUDOERS_DIR", sudoers_dir),
    ):
        yield


# ---------------------------------------------------------------------------
# List users
# ---------------------------------------------------------------------------


def test_list_users():
    users = service.list_users()
    names = [u.username for u in users]
    assert "root" in names
    assert "alice" in names
    assert "bob" in names
    assert len(users) == 4


def test_list_users_missing_file(tmp_path):
    with patch.object(service, "PASSWD_FILE", tmp_path / "nonexistent"):
        assert service.list_users() == []


# ---------------------------------------------------------------------------
# List groups
# ---------------------------------------------------------------------------


def test_list_groups():
    groups = service.list_groups()
    names = [g.groupname for g in groups]
    assert "root" in names
    assert "wheel" in names
    assert "developers" in names


def test_list_groups_members():
    groups = service.list_groups()
    devs = next(g for g in groups if g.groupname == "developers")
    assert "alice" in devs.members
    assert "bob" in devs.members


# ---------------------------------------------------------------------------
# User detail
# ---------------------------------------------------------------------------


def test_get_user_detail():
    detail = service.get_user_detail("alice")
    assert detail is not None
    assert detail.username == "alice"
    assert detail.uid == 1000
    assert detail.primary_group == "alice"
    assert "wheel" in detail.groups
    assert "developers" in detail.groups
    assert detail.has_sudo is True  # alice is in wheel group


def test_get_user_detail_no_sudo():
    detail = service.get_user_detail("bob")
    assert detail is not None
    assert detail.has_sudo is False


def test_get_user_detail_not_found():
    assert service.get_user_detail("nonexistent") is None


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def test_backup_user_files(tmp_path):
    backup_dir = tmp_path / "backups"
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.backup_dir = backup_dir
        result = service.backup_user_files()

    assert result.success is True
    assert zipfile.is_zipfile(result.backup_path)

    with zipfile.ZipFile(result.backup_path) as zf:
        names = zf.namelist()
        assert "passwd" in names
        assert "shadow" in names
        assert "group" in names
        assert "gshadow" in names


def test_backup_user_files_no_files(tmp_path):
    backup_dir = tmp_path / "backups"
    with (
        patch.object(service, "PASSWD_FILE", tmp_path / "nope1"),
        patch.object(service, "SHADOW_FILE", tmp_path / "nope2"),
        patch.object(service, "GROUP_FILE", tmp_path / "nope3"),
        patch.object(service, "GSHADOW_FILE", tmp_path / "nope4"),
        patch("app.core.config.settings") as mock_settings,
    ):
        mock_settings.backup_dir = backup_dir
        result = service.backup_user_files()

    assert result.success is False


# ---------------------------------------------------------------------------
# Grant sudo
# ---------------------------------------------------------------------------


async def test_grant_sudo(sudoers_dir):
    with patch.object(service, "_run", new_callable=AsyncMock):
        result = await service.grant_sudo("bob")

    assert result.success is True
    sudoers_file = sudoers_dir / "bob"
    assert sudoers_file.is_file()
    assert "bob ALL=" in sudoers_file.read_text()


async def test_grant_sudo_already_has(sudoers_dir):
    # alice is in wheel group, so already has sudo
    result = await service.grant_sudo("alice")
    assert result.success is True
    assert "already" in result.message


async def test_grant_sudo_user_not_found():
    result = await service.grant_sudo("nonexistent")
    assert result.success is False
    assert "not found" in result.message.lower()


# ---------------------------------------------------------------------------
# Create user
# ---------------------------------------------------------------------------


async def test_create_user_success():
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        # groupadd succeeds, then useradd succeeds
        mock_run.side_effect = [
            (0, "", ""),  # groupadd
            (0, "", ""),  # useradd
        ]
        result = await service.create_user("newuser")

    assert result.success is True
    assert "newuser" in result.message


async def test_create_user_already_exists():
    result = await service.create_user("alice")
    assert result.success is False
    assert "already exists" in result.message


async def test_create_user_with_options():
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = [
            (0, "", ""),  # groupadd
            (0, "", ""),  # useradd
        ]
        result = await service.create_user(
            "newuser",
            group="devs",
            shell="/bin/zsh",
            create_home=True,
            comment="New User",
        )

    assert result.success is True
    # Check the useradd command includes expected flags
    useradd_call = mock_run.call_args_list[1][0][0]
    assert "-g devs" in useradd_call
    assert "-s /bin/zsh" in useradd_call
    assert "-m" in useradd_call


async def test_create_user_useradd_fails():
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = [
            (0, "", ""),  # groupadd
            (1, "", "useradd: Permission denied"),  # useradd fails
        ]
        result = await service.create_user("newuser")

    assert result.success is False
    assert "Failed" in result.message


# ---------------------------------------------------------------------------
# Delete user
# ---------------------------------------------------------------------------


async def test_delete_user_success():
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, "", "")
        result = await service.delete_user("alice")

    assert result.success is True


async def test_delete_user_not_found():
    result = await service.delete_user("nonexistent")
    assert result.success is False
    assert "not found" in result.message.lower()


async def test_delete_user_removes_sudoers(sudoers_dir):
    # Create a sudoers entry for bob
    (sudoers_dir / "bob").write_text("bob ALL=(ALL) NOPASSWD:ALL\n")

    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, "", "")
        result = await service.delete_user("bob")

    assert result.success is True
    assert not (sudoers_dir / "bob").exists()


async def test_delete_user_with_remove_home():
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, "", "")
        result = await service.delete_user("alice", remove_home=True)

    assert result.success is True
    cmd = mock_run.call_args[0][0]
    assert "-r" in cmd


# ---------------------------------------------------------------------------
# SSH key generation
# ---------------------------------------------------------------------------


async def test_generate_ssh_key(tmp_path):
    alice_home = tmp_path / "home" / "alice"
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, "", "")
        # ssh-keygen is mocked, so we create the files manually to simulate
        ssh_dir = alice_home / ".ssh"
        ssh_dir.mkdir(parents=True, exist_ok=True)
        result = await service.generate_ssh_key("alice")

    assert result.success is True
    assert "alice" in result.message


async def test_generate_ssh_key_already_exists(tmp_path):
    alice_home = tmp_path / "home" / "alice"
    ssh_dir = alice_home / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    (ssh_dir / "id_rsa").write_text("existing key")

    result = await service.generate_ssh_key("alice")
    assert result.success is False
    assert "already exists" in result.message


async def test_generate_ssh_key_user_not_found():
    result = await service.generate_ssh_key("nonexistent")
    assert result.success is False
    assert "not found" in result.message.lower()


# ---------------------------------------------------------------------------
# Read SSH keys
# ---------------------------------------------------------------------------


def test_read_ssh_keys(tmp_path):
    alice_home = tmp_path / "home" / "alice"
    ssh_dir = alice_home / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    (ssh_dir / "id_rsa").write_text("PRIVATE_KEY_CONTENT")
    (ssh_dir / "id_rsa.pub").write_text("ssh-rsa AAAA... alice@host")

    result = service.read_ssh_keys("alice")
    assert result.username == "alice"
    assert "PRIVATE_KEY_CONTENT" in result.private_key
    assert "ssh-rsa" in result.public_key


def test_read_ssh_keys_no_keys(tmp_path):
    # alice home exists but no .ssh/id_rsa
    with pytest.raises(FileNotFoundError):
        service.read_ssh_keys("alice")


def test_read_ssh_keys_user_not_found():
    with pytest.raises(FileNotFoundError):
        service.read_ssh_keys("nonexistent")


# ---------------------------------------------------------------------------
# Delete SSH keys
# ---------------------------------------------------------------------------


def test_delete_ssh_keys(tmp_path):
    alice_home = tmp_path / "home" / "alice"
    ssh_dir = alice_home / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    (ssh_dir / "id_rsa").write_text("key")
    (ssh_dir / "id_rsa.pub").write_text("pub")

    result = service.delete_ssh_keys("alice")
    assert result.success is True
    assert not ssh_dir.exists()


def test_delete_ssh_keys_no_ssh_dir():
    result = service.delete_ssh_keys("alice")
    assert result.success is False
    assert ".ssh" in result.message


def test_delete_ssh_keys_user_not_found():
    result = service.delete_ssh_keys("nonexistent")
    assert result.success is False


# ---------------------------------------------------------------------------
# Passwordless login
# ---------------------------------------------------------------------------


async def test_set_passwordless_login():
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, "", "")
        result = await service.set_passwordless_login("alice")

    assert result.success is True
    cmd = mock_run.call_args[0][0]
    assert "passwd -d alice" in cmd


async def test_set_passwordless_login_user_not_found():
    result = await service.set_passwordless_login("nonexistent")
    assert result.success is False


async def test_set_passwordless_login_fails():
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (1, "", "passwd: Permission denied")
        result = await service.set_passwordless_login("alice")

    assert result.success is False


# ---------------------------------------------------------------------------
# Read authorized_keys
# ---------------------------------------------------------------------------


def test_read_authorized_keys(tmp_path):
    alice_home = tmp_path / "home" / "alice"
    ssh_dir = alice_home / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    (ssh_dir / "authorized_keys").write_text(
        "ssh-rsa AAAA1 alice@host1\nssh-rsa AAAA2 alice@host2\n"
    )

    result = service.read_authorized_keys("alice")
    assert result.username == "alice"
    assert result.key_count == 2
    assert "AAAA1" in result.content


def test_read_authorized_keys_not_found():
    with pytest.raises(FileNotFoundError):
        service.read_authorized_keys("alice")


def test_read_authorized_keys_user_not_found():
    with pytest.raises(FileNotFoundError):
        service.read_authorized_keys("nonexistent")


# ---------------------------------------------------------------------------
# Add authorized key
# ---------------------------------------------------------------------------


def test_add_authorized_key(tmp_path):
    alice_home = tmp_path / "home" / "alice"

    with patch.object(service, "os") as mock_os:
        mock_os.chown = lambda *a, **k: None
        result = service.add_authorized_key("alice", "ssh-rsa AAAA_NEW alice@new")

    auth_file = alice_home / ".ssh" / "authorized_keys"
    assert result.success is True
    assert "ssh-rsa AAAA_NEW" in auth_file.read_text()


def test_add_authorized_key_duplicate(tmp_path):
    alice_home = tmp_path / "home" / "alice"
    ssh_dir = alice_home / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    (ssh_dir / "authorized_keys").write_text("ssh-rsa EXISTING alice@host\n")

    result = service.add_authorized_key("alice", "ssh-rsa EXISTING alice@host")
    assert result.success is True
    assert "already exists" in result.message


def test_add_authorized_key_user_not_found():
    result = service.add_authorized_key("nonexistent", "ssh-rsa key")
    assert result.success is False
