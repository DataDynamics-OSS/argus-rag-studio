# SPDX-License-Identifier: Apache-2.0
"""스토리지 소스(참조 인테이크) 단위 테스트 — 경로 정규화·NAS 어댑터·자격증명 암호화.

설계: design/storage-path-routing.md. 소스 어댑터는 읽기 전용(stat/read/list)이고 모든
진입점이 normalize_source_path + (NAS) realpath 가드를 거친다 — traversal 차단을 여기서 검증한다.
S3 어댑터는 실서버 의존이라 여기서는 경로 조립(_key/_rel)만 검증한다.
"""

import os

import pytest

from app.sources.adapters import (
    NasSourceAdapter,
    S3SourceAdapter,
    SourceObjectNotFound,
    SourcePathError,
    get_source_adapter,
    normalize_source_path,
)
from app.sources.service import decrypt_secret, encrypt_secret, validate_source


# ── 경로 정규화 ────────────────────────────────────────────────────────────────

def test_normalize_source_path_basic():
    assert normalize_source_path("contracts/2026/a.pdf") == "contracts/2026/a.pdf"
    assert normalize_source_path("/contracts//2026/./a.pdf") == "contracts/2026/a.pdf"
    assert normalize_source_path("contracts\\2026\\a.pdf") == "contracts/2026/a.pdf"
    assert normalize_source_path("", allow_empty=True) == ""


def test_normalize_source_path_rejects_traversal_and_empty():
    with pytest.raises(SourcePathError):
        normalize_source_path("../etc/passwd")
    with pytest.raises(SourcePathError):
        normalize_source_path("a/../../b")
    with pytest.raises(SourcePathError):
        normalize_source_path("")
    with pytest.raises(SourcePathError):
        normalize_source_path("/")


# ── NAS 어댑터 ────────────────────────────────────────────────────────────────

@pytest.fixture
def nas_root(tmp_path):
    (tmp_path / "contracts" / "2026").mkdir(parents=True)
    (tmp_path / "contracts" / "2026" / "a.pdf").write_bytes(b"pdf-bytes")
    (tmp_path / "hr").mkdir()
    (tmp_path / "hr" / "policy.txt").write_bytes(b"policy")
    return tmp_path


async def test_nas_stat_read(nas_root):
    a = NasSourceAdapter({"mount_path": str(nas_root)})
    st = await a.stat("contracts/2026/a.pdf")
    assert st.size == 9 and st.mtime is not None
    assert await a.read("contracts/2026/a.pdf") == b"pdf-bytes"
    with pytest.raises(SourceObjectNotFound):
        await a.stat("contracts/none.pdf")
    with pytest.raises(SourceObjectNotFound):
        await a.stat("contracts")  # 디렉터리는 파일이 아님


async def test_nas_list(nas_root):
    a = NasSourceAdapter({"mount_path": str(nas_root)})
    top = await a.list("")
    assert [(e.path, e.is_dir) for e in top.entries] == [("contracts", True), ("hr", True)]
    flat = await a.list("", recursive=True)
    assert {e.path for e in flat.entries} == {"contracts/2026/a.pdf", "hr/policy.txt"}
    assert not flat.truncated
    with pytest.raises(SourceObjectNotFound):
        await a.list("nope")


async def test_nas_base_prefix(nas_root):
    a = NasSourceAdapter({"mount_path": str(nas_root), "base_prefix": "contracts"})
    assert await a.read("2026/a.pdf") == b"pdf-bytes"
    listing = await a.list("")
    assert [e.path for e in listing.entries] == ["2026"]


async def test_nas_blocks_traversal_and_symlink_escape(nas_root, tmp_path_factory):
    a = NasSourceAdapter({"mount_path": str(nas_root)})
    with pytest.raises(SourcePathError):
        await a.read("../outside.txt")
    # 마운트 밖을 가리키는 심링크 — realpath 가드로 차단.
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.txt").write_bytes(b"secret")
    os.symlink(outside / "secret.txt", nas_root / "link.txt")
    with pytest.raises(SourcePathError):
        await a.read("link.txt")


def test_nas_requires_absolute_mount():
    with pytest.raises(SourcePathError):
        NasSourceAdapter({"mount_path": "relative/path"})


# ── S3 어댑터(경로 조립만 — 실서버 비의존) ─────────────────────────────────────

def test_s3_key_mapping_with_base_prefix():
    a = S3SourceAdapter({"bucket": "b", "base_prefix": "/dept/docs/"})
    assert a._key("contracts/a.pdf") == "dept/docs/contracts/a.pdf"
    assert a._rel("dept/docs/contracts/a.pdf") == "contracts/a.pdf"
    plain = S3SourceAdapter({"bucket": "b"})
    assert plain._key("a.pdf") == "a.pdf" and plain._rel("a.pdf") == "a.pdf"


# ── 팩토리/검증/암호화 ─────────────────────────────────────────────────────────

def test_get_source_adapter_kinds(tmp_path):
    assert isinstance(get_source_adapter("s3", {"bucket": "b"}), S3SourceAdapter)
    assert isinstance(get_source_adapter("nas", {"mount_path": str(tmp_path)}), NasSourceAdapter)
    with pytest.raises(ValueError):
        get_source_adapter("ftp", {})


def test_validate_source():
    assert validate_source("s3", {"bucket": "docs"}) == []
    assert any("bucket" in e for e in validate_source("s3", {}))
    assert validate_source("nas", {"mount_path": "/mnt/nas"}) == []
    assert any("mount_path" in e for e in validate_source("nas", {"mount_path": "rel"}))
    assert validate_source("ftp", {})  # 미지원 kind
    assert any("base_prefix" in e for e in validate_source("s3", {"bucket": "b", "base_prefix": "../x"}))


def test_secret_encrypt_roundtrip():
    # 마커는 충분히 길게 — 짧은 문자열("AK")은 base64 암호문에 우연히 나타나 플레이키.
    secret = {"access_key": "AKIA-plain-marker", "secret_key": "SK-plain-marker"}
    enc = encrypt_secret(secret)
    assert "AKIA-plain-marker" not in enc and "SK-plain-marker" not in enc  # 평문 미노출
    assert decrypt_secret(enc) == secret
    assert decrypt_secret(None) is None
    assert decrypt_secret("broken-token") is None  # 키 교체/손상 → None(재입력 유도)
