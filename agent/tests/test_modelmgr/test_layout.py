# SPDX-License-Identifier: Apache-2.0
"""modelmgr 전개 레이아웃 테스트 — flat / hf-cache 대상 경로와 재배치."""

import pytest

from app.modelmgr.schemas import ModelInstallRequest
from app.modelmgr.service import _MARKER, _finalize_layout, _target_dir

SHA = "a" * 64


def req(**kw) -> ModelInstallRequest:
    base = dict(
        volume="vol", subdir="bge-small-en-v1.5", archive_url="http://x/model.tar.zst",
        archive="model.tar.zst", sha256=SHA,
    )
    base.update(kw)
    return ModelInstallRequest(**base)


def test_target_dir_flat(tmp_path):
    assert _target_dir(tmp_path, req()) == tmp_path / "bge-small-en-v1.5"


def test_target_dir_hf_cache(tmp_path):
    r = req(layout="hf-cache", repo="BAAI/bge-small-en-v1.5")
    assert _target_dir(tmp_path, r) == tmp_path / "models--BAAI--bge-small-en-v1.5"


def test_target_dir_hf_cache_requires_repo(tmp_path):
    with pytest.raises(RuntimeError, match="repo"):
        _target_dir(tmp_path, req(layout="hf-cache"))


def test_finalize_layout_flat_noop(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    (work / "config.json").write_text("{}")
    _finalize_layout(work, req())
    assert (work / "config.json").exists()
    assert not (work / "snapshots").exists()


def test_finalize_layout_hf_cache(tmp_path):
    work = tmp_path / "w"
    (work / "sub").mkdir(parents=True)
    (work / "config.json").write_text("{}")
    (work / "sub" / "f.bin").write_text("x")
    r = req(layout="hf-cache", repo="BAAI/bge-small-en-v1.5", revision="main")
    _finalize_layout(work, r)
    snap = work / "snapshots" / "main"
    assert (snap / "config.json").exists()
    assert (snap / "sub" / "f.bin").exists()
    assert (work / "refs" / "main").read_text() == "main"
    # 마커는 루트에 남는다(멱등 체크 위치) — 스냅샷으로 이동하지 않음.
    (work / _MARKER).write_text("{}")
    assert not (snap / _MARKER).exists()
