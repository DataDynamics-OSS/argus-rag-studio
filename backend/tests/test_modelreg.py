# SPDX-License-Identifier: Apache-2.0
"""모델 레지스트리 테스트 — 시드 정합성·스키마 검증·응답 변환(design/model-registry.md)."""

import json

import pytest
from pydantic import ValidationError

from app.modelreg.models import RagModelRegistry
from app.modelreg.schemas import ModelCreateRequest, ModelUpdateRequest
from app.modelreg.seeds import DEFAULT_VLM_NAME, KIND_TARGETS, SEED_MODELS, seed_entry
from app.modelreg.service import entry_dict

# ── 시드 ─────────────────────────────────────────────────────────────────────

def test_seeds_unique_and_complete():
    keys = [(m["kind"], m["name"]) for m in SEED_MODELS]
    assert len(keys) == len(set(keys))  # (kind, name) 중복 없음
    kinds = {m["kind"] for m in SEED_MODELS}
    assert kinds == {"vlm", "embedding", "reranker", "detection"}
    assert any(m["name"] == DEFAULT_VLM_NAME for m in SEED_MODELS if m["kind"] == "vlm")


def test_seed_entry_fills_defaults_by_kind():
    e = seed_entry({"kind": "embedding", "name": "x", "repo": "org/x"})
    assert e["source"] == "hf" and e["target"] == "hf-cache" and e["revision"] == "main"
    v = seed_entry({"kind": "vlm", "name": "y", "repo": "org/y"})
    assert v["target"] == "flat"  # vLLM 로컬 경로 서빙
    assert KIND_TARGETS["reranker"] == "hf-cache" and KIND_TARGETS["detection"] == "flat"


def test_vlm_seeds_have_max_len():
    for m in SEED_MODELS:
        if m["kind"] == "vlm":
            assert m["params"].get("max_len"), m["name"]  # 서빙 인자 필수


# ── 스키마 검증 ───────────────────────────────────────────────────────────────

def test_create_request_validates_kind_and_name():
    ok = ModelCreateRequest(kind="embedding", name="my-model", repo="org/My-Model")
    assert ok.revision == "main" and ok.enabled

    with pytest.raises(ValidationError):
        ModelCreateRequest(kind="llm", name="x", repo="org/x")  # 없는 kind
    with pytest.raises(ValidationError):
        ModelCreateRequest(kind="vlm", name="a/b", repo="org/x")  # 버킷 키 오염('/')
    with pytest.raises(ValidationError):
        ModelCreateRequest(kind="vlm", name=" ", repo="org/x")  # 빈 이름
    with pytest.raises(ValidationError):
        ModelCreateRequest(kind="vlm", name="x", repo="  ")  # 빈 repo


def test_update_request_partial_semantics():
    req = ModelUpdateRequest(note="메모만 변경")
    data = req.model_dump(exclude_unset=True)
    assert data == {"note": "메모만 변경"}  # None 필드는 건드리지 않음
    with pytest.raises(ValidationError):
        ModelUpdateRequest(name="한/글")


# ── 응답 변환 ─────────────────────────────────────────────────────────────────

def _row(**kw) -> RagModelRegistry:
    base = dict(
        model_id="m-1", kind="embedding", name="bge", repo="BAAI/bge", revision="main",
        source="hf", target="hf-cache", params_json="{}", note=None,
        enabled=True, builtin=False,
    )
    base.update(kw)
    return RagModelRegistry(**base)


def test_entry_dict_flattens_params():
    e = _row(kind="vlm", target="flat",
             params_json=json.dumps({"max_len": 4096, "approx_gb": 16}))
    d = entry_dict(e)
    assert d["max_len"] == 4096 and d["approx_gb"] == 16 and d["note"] == ""


def test_entry_dict_vlm_max_len_default_and_bad_json():
    d = entry_dict(_row(kind="vlm", params_json="깨진 json"))
    assert d["max_len"] == 8192  # vlm 기본 서빙 인자
    d2 = entry_dict(_row(kind="embedding"))
    assert d2["max_len"] is None and d2["approx_gb"] is None
