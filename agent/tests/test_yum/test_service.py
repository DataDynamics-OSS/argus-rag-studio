"""Tests for yum service - repository file operations."""

import zipfile
from unittest.mock import patch

import pytest

from app.yum import service


@pytest.fixture
def repo_dir(tmp_path):
    """Create a temporary yum.repos.d directory with sample files."""
    d = tmp_path / "yum.repos.d"
    d.mkdir()
    (d / "base.repo").write_text("[base]\nname=Base\nbaseurl=http://mirror/base\nenabled=1\n")
    (d / "epel.repo").write_text("[epel]\nname=EPEL\nbaseurl=http://mirror/epel\nenabled=1\n")
    return d


@pytest.fixture(autouse=True)
def _patch_repo_dir(repo_dir):
    """Patch REPO_DIR to use the temporary directory."""
    with patch.object(service, "REPO_DIR", repo_dir):
        yield


# ---------------------------------------------------------------------------
# Repo file operations
# ---------------------------------------------------------------------------


def test_list_repo_files(repo_dir):
    result = service.list_repo_files()
    names = [r.filename for r in result]
    assert "base.repo" in names
    assert "epel.repo" in names
    assert len(result) == 2


def test_create_repo_file(repo_dir):
    content = "[myrepo]\nname=My Repo\nbaseurl=http://example.com/repo\nenabled=1\n"
    result = service.create_repo_file("myrepo.repo", content)
    assert result.success is True
    assert (repo_dir / "myrepo.repo").read_text() == content


def test_create_repo_file_appends_suffix(repo_dir):
    result = service.create_repo_file("custom", "content")
    assert result.success is True
    assert (repo_dir / "custom.repo").exists()


def test_create_repo_file_already_exists(repo_dir):
    result = service.create_repo_file("base.repo", "new content")
    assert result.success is False
    assert "already exists" in result.message


def test_update_repo_file(repo_dir):
    new_content = "[base]\nname=Updated\nbaseurl=http://new/base\nenabled=0\n"
    result = service.update_repo_file("base.repo", new_content)
    assert result.success is True
    assert (repo_dir / "base.repo").read_text() == new_content


def test_update_repo_file_not_found(repo_dir):
    result = service.update_repo_file("nonexistent.repo", "content")
    assert result.success is False
    assert "not found" in result.message


def test_read_repo_file(repo_dir):
    result = service.read_repo_file("base.repo")
    assert result.filename == "base.repo"
    assert "[base]" in result.content


def test_read_repo_file_not_found(repo_dir):
    with pytest.raises(FileNotFoundError):
        service.read_repo_file("nonexistent.repo")


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def test_backup_repo_files(repo_dir, tmp_path):
    backup_dir = tmp_path / "backups"
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.backup_dir = backup_dir
        result = service.backup_repo_files()

    assert result.success is True
    assert result.file_count == 2
    assert zipfile.is_zipfile(result.backup_path)

    with zipfile.ZipFile(result.backup_path) as zf:
        names = zf.namelist()
        assert "base.repo" in names
        assert "epel.repo" in names
