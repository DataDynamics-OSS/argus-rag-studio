# SPDX-License-Identifier: Apache-2.0
"""스토리지 백엔드 추상화 테스트.

- S3 백엔드: URI 규약·키 규칙이 기존 동작과 동일한지(회귀 방지).
- UC Volumes 백엔드: databricks-sdk(WorkspaceClient.files)를 가짜로 주입해 경로 규약·
  put/get/exists/delete/copy·미지원(presigned/rename) 동작을 검증한다(실제 workspace 불필요).
- 팩토리: object_storage.backend 설정에 따라 올바른 백엔드를 캐시·재생성하는지.
"""

import sys
import types

import pytest

from app.core.config import settings


# ── S3 백엔드(회귀) ──────────────────────────────────────────────────────────
def test_s3_uri_roundtrip_matches_legacy():
    from app.storage.s3_backend import S3StorageBackend

    b = S3StorageBackend()
    uri = b.build_uri("collections/c/d/a.pdf")
    assert uri == f"s3://{settings.os_bucket}/collections/c/d/a.pdf"
    bucket, key = b.parse_uri(uri)
    assert bucket == settings.os_bucket
    assert key == "collections/c/d/a.pdf"


def test_s3_parse_uri_without_scheme():
    from app.storage.s3_backend import S3StorageBackend

    bucket, key = S3StorageBackend().parse_uri("/loose/key.txt")
    assert bucket == settings.os_bucket
    assert key == "loose/key.txt"


def test_client_build_object_key_is_pure():
    from app.storage import client

    assert client.build_object_key("cuuid", "duuid", "a/b.pdf") == "collections/cuuid/duuid/a_b.pdf"


# ── 가짜 databricks-sdk ──────────────────────────────────────────────────────
class _FakeContents:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakeDownload:
    def __init__(self, data: bytes):
        self.contents = _FakeContents(data)


class FakeFiles:
    def __init__(self):
        self.store: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.created_dirs: list[str] = []

    def upload(self, path, contents, overwrite=False):
        self.store[path] = contents.read()

    def download(self, path):
        return _FakeDownload(self.store[path])

    def get_metadata(self, path):
        if path not in self.store:
            raise RuntimeError("NotFound")
        return {"path": path}

    def get_directory_metadata(self, path):
        return {"path": path}

    def delete(self, path):
        self.deleted.append(path)
        self.store.pop(path, None)

    def delete_directory(self, path):
        self.deleted.append(path + "/")

    def create_directory(self, path):
        self.created_dirs.append(path)


class FakeWorkspaceClient:
    last: "FakeWorkspaceClient | None" = None

    def __init__(self, host=None, token=None):
        self.host = host
        self.token = token
        self.files = FakeFiles()
        FakeWorkspaceClient.last = self


@pytest.fixture(autouse=True)
def _fake_sdk(monkeypatch):
    pkg = types.ModuleType("databricks")
    sdk = types.ModuleType("databricks.sdk")
    sdk.WorkspaceClient = FakeWorkspaceClient
    monkeypatch.setitem(sys.modules, "databricks", pkg)
    monkeypatch.setitem(sys.modules, "databricks.sdk", sdk)
    FakeWorkspaceClient.last = None
    yield


def _uc():
    from app.storage.uc_volumes_backend import UCVolumesStorageBackend

    return UCVolumesStorageBackend(
        host="https://dbc.cloud.databricks.com", token="dapi-x",
        catalog="main", schema="argus", volume="documents",
    )


# ── UC Volumes 백엔드 ────────────────────────────────────────────────────────
def test_uc_requires_host_token_location():
    from app.storage.uc_volumes_backend import UCVolumesStorageBackend

    with pytest.raises(ValueError):
        UCVolumesStorageBackend(host="", token="t", catalog="c", schema="s", volume="v")
    with pytest.raises(ValueError):
        UCVolumesStorageBackend(host="h", token="t", catalog="", schema="s", volume="v")


def test_uc_uri_and_path():
    b = _uc()
    assert b.build_uri("c/d/a.pdf") == "dbfs:/Volumes/main/argus/documents/c/d/a.pdf"
    root, key = b.parse_uri("dbfs:/Volumes/main/argus/documents/c/d/a.pdf")
    assert root == "/Volumes/main/argus/documents"
    assert key == "c/d/a.pdf"


@pytest.mark.asyncio
async def test_uc_put_get_roundtrip():
    b = _uc()
    uri = await b.put_object("c/d/a.txt", b"hello", "text/plain")
    assert uri == "dbfs:/Volumes/main/argus/documents/c/d/a.txt"
    # 절대 경로로 저장됐는지
    assert "/Volumes/main/argus/documents/c/d/a.txt" in FakeWorkspaceClient.last.files.store
    data = await b.get_object(uri)
    assert data == b"hello"


@pytest.mark.asyncio
async def test_uc_exists_and_delete():
    b = _uc()
    await b.put_object("k.txt", b"x")
    assert await b.object_exists("k.txt") is True
    assert await b.object_exists("missing.txt") is False
    await b.delete_object("k.txt")
    assert "/Volumes/main/argus/documents/k.txt" in FakeWorkspaceClient.last.files.deleted


@pytest.mark.asyncio
async def test_uc_copy_object():
    b = _uc()
    await b.put_object("src.txt", b"payload")
    await b.copy_object("src.txt", "dst.txt")
    store = FakeWorkspaceClient.last.files.store
    assert store["/Volumes/main/argus/documents/dst.txt"] == b"payload"


@pytest.mark.asyncio
async def test_uc_read_object_by_path():
    b = _uc()
    await b.put_object("c/x.bin", b"\x00\x01")
    data, ctype = await b.read_object_by_path("c/x.bin")
    assert data == b"\x00\x01"
    assert ctype is None  # UC Volumes 는 content-type 미제공


@pytest.mark.asyncio
async def test_uc_presigned_and_rename_unsupported():
    b = _uc()
    with pytest.raises(NotImplementedError):
        await b.presigned_download_url("c/x")
    with pytest.raises(NotImplementedError):
        await b.rename_path("a", "b")


# ── 팩토리 ──────────────────────────────────────────────────────────────────
def test_factory_default_is_s3():
    from app.storage.factory import get_storage_backend, reset_storage_backend
    from app.storage.s3_backend import S3StorageBackend

    settings.storage_backend = "s3"
    reset_storage_backend()
    assert isinstance(get_storage_backend(), S3StorageBackend)


def test_factory_switches_to_uc_volumes():
    from app.storage.factory import get_storage_backend, reset_storage_backend
    from app.storage.uc_volumes_backend import UCVolumesStorageBackend

    saved = (settings.storage_backend, settings.databricks_host, settings.databricks_token)
    try:
        settings.storage_backend = "uc_volumes"
        settings.databricks_host = "https://dbc.cloud.databricks.com"
        settings.databricks_token = "dapi-x"
        reset_storage_backend()
        assert isinstance(get_storage_backend(), UCVolumesStorageBackend)
    finally:
        settings.storage_backend, settings.databricks_host, settings.databricks_token = saved
        reset_storage_backend()
