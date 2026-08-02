# SPDX-License-Identifier: Apache-2.0
"""모델 매니페스트 + 팩 스크립트 테스트 — design/model-packaging.md Phase 1(순수 로직)."""

import json
import tarfile

from app.servermgr.model_catalog import bucket_key, list_models, resolve_model
from scripts.pack_model import build_manifest, make_archive, sha256_of

# ── 매니페스트 ────────────────────────────────────────────────────────────────

def test_manifest_covers_all_kinds():
    kinds = {m["kind"] for m in list_models()}
    assert {"vlm", "embedding", "reranker", "detection"} <= kinds


def test_vlm_entries_come_from_seeds():
    # 사용자 등록·설정 CSV 확장은 DB 레지스트리(app/modelreg)로 이관 — 동기 카탈로그는
    # 외부망 pack_model 폴백용 시드만 노출한다(design/model-registry.md).
    names = [m["name"] for m in list_models("vlm")]
    assert "qwen2-vl-7b" in names


def test_kind_targets_drive_layout():
    # 전개 레이아웃 — embedding/reranker 는 hf-cache(이름 조회), vlm/detection 은 flat.
    by_kind = {m["kind"]: m["target"] for m in list_models()}
    assert by_kind["embedding"] == "hf-cache" and by_kind["reranker"] == "hf-cache"
    assert by_kind["vlm"] == "flat" and by_kind["detection"] == "flat"


def test_resolve_and_source_flags():
    m = resolve_model("embedding", "multilingual-e5-large")
    assert m and m["repo"] == "intfloat/multilingual-e5-large" and m["source"] == "hf"
    det = resolve_model("detection", "paddleocr-det-rec")
    assert det and det["source"] == "paddle"  # pack_model 대상 아님(수동 반입)
    assert resolve_model("vlm", "없음") is None


def test_bucket_key_convention():
    assert bucket_key("vlm", "qwen2-vl-7b", "main") == "vlm/qwen2-vl-7b/main/model.tar.zst"


# ── 팩 스크립트(네트워크 없는 부분) ───────────────────────────────────────────

def test_make_archive_roundtrip(tmp_path):
    src = tmp_path / "snap"
    src.mkdir()
    (src / "config.json").write_text('{"a":1}')
    (src / "weights.bin").write_bytes(b"\x00" * 1024)
    out = make_archive(src, tmp_path / "dest")
    assert out.name in ("model.tar.zst", "model.tar.gz")
    digest = sha256_of(out)
    assert len(digest) == 64
    # 아카이브 루트가 디렉터리 내용물인지(전개 시 바로 풀리는 형태) — gz 는 직접, zst 는 해제 후 확인.
    if out.suffix == ".gz":
        with tarfile.open(out) as tf:
            assert sorted(tf.getnames()) == ["config.json", "weights.bin"]
    else:
        import subprocess
        tar = tmp_path / "check.tar"
        subprocess.run(["zstd", "-q", "-d", str(out), "-o", str(tar)], check=True)
        with tarfile.open(tar) as tf:
            assert sorted(tf.getnames()) == ["config.json", "weights.bin"]


def test_build_manifest_fields():
    m = build_manifest(kind="vlm", name="x", repo="org/X", revision="main",
                       target="hf-cache", archive="model.tar.zst", sha256="ab" * 32, size_bytes=10)
    assert m["format"] == "model-pack/v1"
    assert json.dumps(m)  # 직렬화 가능
