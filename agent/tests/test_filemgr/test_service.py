"""Tests for filemgr service - file and directory management."""

import base64
import zipfile
from unittest.mock import AsyncMock, patch

import pytest

from app.filemgr import service
from app.filemgr.schemas import ArchiveCreateRequest

# ---------------------------------------------------------------------------
# Directory create / delete
# ---------------------------------------------------------------------------


def test_create_directory(tmp_path):
    target = tmp_path / "newdir"
    result = service.create_directory(str(target))
    assert result.success is True
    assert target.is_dir()


def test_create_directory_with_mode(tmp_path):
    target = tmp_path / "modedir"
    result = service.create_directory(str(target), mode="700")
    assert result.success is True
    assert target.is_dir()


def test_create_directory_already_exists(tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    result = service.create_directory(str(target))
    assert result.success is False
    assert "Already exists" in result.message


def test_create_directory_with_parents(tmp_path):
    target = tmp_path / "a" / "b" / "c"
    result = service.create_directory(str(target), parents=True)
    assert result.success is True
    assert target.is_dir()


def test_create_directory_no_parents(tmp_path):
    target = tmp_path / "x" / "y"
    result = service.create_directory(str(target), parents=False)
    assert result.success is False


def test_delete_directory(tmp_path):
    target = tmp_path / "deldir"
    target.mkdir()
    result = service.delete_directory(str(target))
    assert result.success is True
    assert not target.exists()


def test_delete_directory_recursive(tmp_path):
    target = tmp_path / "tree"
    (target / "sub").mkdir(parents=True)
    (target / "sub" / "file.txt").write_text("hello")
    result = service.delete_directory(str(target), recursive=True)
    assert result.success is True
    assert not target.exists()


def test_delete_directory_not_empty_without_recursive(tmp_path):
    target = tmp_path / "notempty"
    target.mkdir()
    (target / "file.txt").write_text("content")
    result = service.delete_directory(str(target), recursive=False)
    assert result.success is False


def test_delete_directory_not_found(tmp_path):
    result = service.delete_directory(str(tmp_path / "nope"))
    assert result.success is False
    assert "Not found" in result.message


def test_delete_directory_is_file(tmp_path):
    f = tmp_path / "afile"
    f.write_text("data")
    result = service.delete_directory(str(f))
    assert result.success is False
    assert "Not a directory" in result.message


# ---------------------------------------------------------------------------
# Chown
# ---------------------------------------------------------------------------


async def test_chown_success(tmp_path):
    target = tmp_path / "owned"
    target.write_text("data")
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, "", "")
        result = await service.chown(str(target), owner="root", group="root")
    assert result.success is True
    assert "root:root" in result.message


async def test_chown_owner_only(tmp_path):
    target = tmp_path / "owned2"
    target.write_text("data")
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, "", "")
        result = await service.chown(str(target), owner="alice", group=None)
    assert result.success is True
    mock_run.assert_called_once()
    assert "alice" in mock_run.call_args[0][0]


async def test_chown_group_only(tmp_path):
    target = tmp_path / "owned3"
    target.write_text("data")
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, "", "")
        result = await service.chown(str(target), owner=None, group="staff")
    assert result.success is True
    assert ":staff" in mock_run.call_args[0][0]


async def test_chown_no_owner_no_group(tmp_path):
    target = tmp_path / "owned4"
    target.write_text("data")
    result = await service.chown(str(target), owner=None, group=None)
    assert result.success is False


async def test_chown_not_found():
    result = await service.chown("/nonexistent/path", owner="root", group=None)
    assert result.success is False


async def test_chown_recursive(tmp_path):
    target = tmp_path / "rdir"
    target.mkdir()
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, "", "")
        result = await service.chown(str(target), owner="root", group=None, recursive=True)
    assert result.success is True
    assert "-R" in mock_run.call_args[0][0]


async def test_chown_fails(tmp_path):
    target = tmp_path / "owned5"
    target.write_text("data")
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (1, "", "Operation not permitted")
        result = await service.chown(str(target), owner="root", group=None)
    assert result.success is False


# ---------------------------------------------------------------------------
# Chmod
# ---------------------------------------------------------------------------


async def test_chmod_success(tmp_path):
    target = tmp_path / "perms"
    target.write_text("data")
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, "", "")
        result = await service.chmod(str(target), "755")
    assert result.success is True


async def test_chmod_recursive(tmp_path):
    target = tmp_path / "permdir"
    target.mkdir()
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, "", "")
        result = await service.chmod(str(target), "700", recursive=True)
    assert result.success is True
    assert "-R" in mock_run.call_args[0][0]


async def test_chmod_not_found():
    result = await service.chmod("/nonexistent", "644")
    assert result.success is False


async def test_chmod_fails(tmp_path):
    target = tmp_path / "perms2"
    target.write_text("data")
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (1, "", "failed")
        result = await service.chmod(str(target), "777")
    assert result.success is False


# ---------------------------------------------------------------------------
# Symlink
# ---------------------------------------------------------------------------


def test_create_link(tmp_path):
    target = tmp_path / "real"
    target.write_text("content")
    link = tmp_path / "mylink"
    result = service.create_link(str(target), str(link))
    assert result.success is True
    assert link.is_symlink()
    assert link.read_text() == "content"


def test_create_link_target_not_found(tmp_path):
    result = service.create_link(str(tmp_path / "nope"), str(tmp_path / "link"))
    assert result.success is False
    assert "Target not found" in result.message


def test_create_link_already_exists(tmp_path):
    target = tmp_path / "real2"
    target.write_text("data")
    link = tmp_path / "existing"
    link.write_text("other")
    result = service.create_link(str(target), str(link))
    assert result.success is False
    assert "already exists" in result.message


def test_create_link_dir(tmp_path):
    target = tmp_path / "realdir"
    target.mkdir()
    link = tmp_path / "dirlink"
    result = service.create_link(str(target), str(link))
    assert result.success is True
    assert link.is_symlink()


# ---------------------------------------------------------------------------
# File info
# ---------------------------------------------------------------------------


def test_get_file_info(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    info = service.get_file_info(str(f))
    assert info.name == "test.txt"
    assert info.is_dir is False
    assert info.size == 11
    assert info.permissions != ""


def test_get_file_info_dir(tmp_path):
    info = service.get_file_info(str(tmp_path))
    assert info.is_dir is True


def test_get_file_info_symlink(tmp_path):
    target = tmp_path / "real"
    target.write_text("data")
    link = tmp_path / "sl"
    link.symlink_to(target)
    info = service.get_file_info(str(link))
    assert info.is_link is True
    assert info.link_target == str(target)


def test_get_file_info_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        service.get_file_info(str(tmp_path / "nope"))


# ---------------------------------------------------------------------------
# Directory listing
# ---------------------------------------------------------------------------


def test_list_directory(tmp_path):
    (tmp_path / "file1.txt").write_text("a")
    (tmp_path / "file2.txt").write_text("b")
    (tmp_path / "subdir").mkdir()
    result = service.list_directory(str(tmp_path))
    assert result.path == str(tmp_path)
    assert result.total == 3
    names = [e.name for e in result.entries]
    assert "file1.txt" in names
    assert "file2.txt" in names
    assert "subdir" in names


def test_list_directory_empty(tmp_path):
    result = service.list_directory(str(tmp_path))
    assert result.total == 0
    assert result.entries == []


def test_list_directory_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        service.list_directory(str(tmp_path / "nope"))


def test_list_directory_not_a_directory(tmp_path):
    f = tmp_path / "afile.txt"
    f.write_text("data")
    with pytest.raises(NotADirectoryError):
        service.list_directory(str(f))


def test_list_directory_sorted(tmp_path):
    (tmp_path / "c.txt").write_text("c")
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    result = service.list_directory(str(tmp_path))
    names = [e.name for e in result.entries]
    assert names == ["a.txt", "b.txt", "c.txt"]


def test_list_directory_with_symlink(tmp_path):
    target = tmp_path / "real.txt"
    target.write_text("data")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    result = service.list_directory(str(tmp_path))
    assert result.total == 2
    link_entry = next(e for e in result.entries if e.name == "link.txt")
    assert link_entry.is_link is True


# ---------------------------------------------------------------------------
# File upload / download / delete
# ---------------------------------------------------------------------------


def test_upload_file_text(tmp_path):
    dest = tmp_path / "uploaded.txt"
    result = service.upload_file(str(dest), "hello world")
    assert result.success is True
    assert dest.read_text() == "hello world"


def test_upload_file_base64(tmp_path):
    dest = tmp_path / "uploaded.bin"
    data = b"\x00\x01\x02\x03"
    encoded = base64.b64encode(data).decode("ascii")
    result = service.upload_file(str(dest), encoded, is_base64=True)
    assert result.success is True
    assert dest.read_bytes() == data


def test_upload_file_with_mode(tmp_path):
    dest = tmp_path / "moded.txt"
    result = service.upload_file(str(dest), "content", mode="600")
    assert result.success is True
    assert dest.is_file()


def test_upload_file_creates_parent(tmp_path):
    dest = tmp_path / "sub" / "deep" / "file.txt"
    result = service.upload_file(str(dest), "content")
    assert result.success is True
    assert dest.is_file()


def test_download_file(tmp_path):
    f = tmp_path / "dl.txt"
    f.write_text("download me")
    result = service.download_file(str(f))
    assert result.name == "dl.txt"
    assert result.size == 11
    decoded = base64.b64decode(result.content)
    assert decoded == b"download me"


def test_download_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        service.download_file(str(tmp_path / "nope"))


def test_delete_file(tmp_path):
    f = tmp_path / "todelete.txt"
    f.write_text("bye")
    result = service.delete_file(str(f))
    assert result.success is True
    assert not f.exists()


def test_delete_file_not_found(tmp_path):
    result = service.delete_file(str(tmp_path / "nope"))
    assert result.success is False


def test_delete_file_is_dir(tmp_path):
    d = tmp_path / "adir"
    d.mkdir()
    result = service.delete_file(str(d))
    assert result.success is False
    assert "directory" in result.message.lower()


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


async def test_create_archive_zip(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "a.txt").write_text("aaa")
    (source / "b.txt").write_text("bbb")

    dest = tmp_path / "out.zip"
    request = ArchiveCreateRequest(source_path=str(source), dest_path=str(dest), format="zip")
    result = await service.create_archive(request)
    assert result.success is True
    assert dest.is_file()
    assert zipfile.is_zipfile(dest)

    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()
        assert "a.txt" in names
        assert "b.txt" in names


async def test_create_archive_tar_gz(tmp_path):
    source = tmp_path / "src2"
    source.mkdir()
    (source / "file.txt").write_text("content")

    dest = tmp_path / "out.tar.gz"
    request = ArchiveCreateRequest(source_path=str(source), dest_path=str(dest), format="tar.gz")
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, "", "")
        # Simulate tar creating the file
        dest.write_bytes(b"fake tar")
        result = await service.create_archive(request)
    assert result.success is True


async def test_create_archive_source_not_found(tmp_path):
    request = ArchiveCreateRequest(
        source_path=str(tmp_path / "nope"),
        dest_path=str(tmp_path / "out.zip"),
        format="zip",
    )
    result = await service.create_archive(request)
    assert result.success is False
    assert "not found" in result.message.lower()


async def test_create_archive_unsupported_format(tmp_path):
    source = tmp_path / "src3"
    source.mkdir()
    request = ArchiveCreateRequest(
        source_path=str(source),
        dest_path=str(tmp_path / "out.rar"),
        format="rar",
    )
    result = await service.create_archive(request)
    assert result.success is False
    assert "Unsupported" in result.message


# ---------------------------------------------------------------------------
# Execute program
# ---------------------------------------------------------------------------


async def test_execute_command_success():
    result = await service.execute_command("echo hello")
    assert result.success is True
    assert result.exit_code == 0
    assert "hello" in result.stdout
    assert result.timed_out is False


async def test_execute_command_failure():
    result = await service.execute_command("false")
    assert result.success is False
    assert result.exit_code != 0


async def test_execute_command_stderr():
    result = await service.execute_command("echo error >&2")
    assert "error" in result.stderr


async def test_execute_command_with_cwd(tmp_path):
    result = await service.execute_command("pwd", cwd=str(tmp_path))
    assert result.success is True
    assert str(tmp_path) in result.stdout


async def test_execute_command_cwd_not_found():
    result = await service.execute_command("echo hi", cwd="/nonexistent/dir")
    assert result.success is False
    assert "not found" in result.message.lower()


async def test_execute_command_with_timeout():
    result = await service.execute_command("echo fast", timeout=10)
    assert result.success is True


async def test_execute_command_timeout_exceeded():
    result = await service.execute_command("sleep 30", timeout=1)
    assert result.success is False
    assert result.timed_out is True
    assert result.exit_code == -1


async def test_execute_command_default_timeout():
    with patch.object(service.settings, "filemgr_exec_timeout", 60):
        result = await service.execute_command("echo ok")
    assert result.success is True


async def test_execute_command_collects_output():
    result = await service.execute_command("echo line1 && echo line2")
    assert result.success is True
    assert "line1" in result.stdout
    assert "line2" in result.stdout
