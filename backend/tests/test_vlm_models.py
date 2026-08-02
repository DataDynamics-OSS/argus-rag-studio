# SPDX-License-Identifier: Apache-2.0
"""VLM 모델 카탈로그 테스트 — 사전 정의 + 설정(extra_models) 병합·파싱·조회."""

from app.core.config import settings
from app.servermgr.vlm_models import (
    DEFAULT_VLM_NAME,
    PREDEFINED_VLM_MODELS,
    list_vlm_models,
    resolve_vlm_model,
)


def test_predefined_only(monkeypatch):
    monkeypatch.setattr(settings, "image_classification_extra_models", "")
    models = list_vlm_models()
    assert [m["name"] for m in models] == [m["name"] for m in PREDEFINED_VLM_MODELS]
    assert all(m["builtin"] for m in models)


def test_extra_models_formats(monkeypatch):
    monkeypatch.setattr(
        settings, "image_classification_extra_models",
        "minicpm-v=openbmb/MiniCPM-V-2_6@4096, google/gemma-3-12b-it, bad@notanum=x",
    )
    models = {m["name"]: m for m in list_vlm_models()}
    assert models["minicpm-v"]["repo"] == "openbmb/MiniCPM-V-2_6"
    assert models["minicpm-v"]["max_len"] == 4096
    # repo 만 준 항목 — name 은 끝 이름 소문자, max_len 기본.
    assert models["gemma-3-12b-it"]["repo"] == "google/gemma-3-12b-it"
    assert models["gemma-3-12b-it"]["max_len"] == 8192


def test_extra_overrides_builtin(monkeypatch):
    monkeypatch.setattr(
        settings, "image_classification_extra_models",
        "qwen2-vl-7b=Qwen/Qwen2-VL-7B-Instruct-AWQ@4096",
    )
    m = resolve_vlm_model("qwen2-vl-7b")
    assert m["repo"].endswith("-AWQ") and m["max_len"] == 4096 and not m["builtin"]


def test_resolve_by_name_repo_and_default(monkeypatch):
    # 폴백 카탈로그 = 최소 시드(기본 VLM 만) — 카탈로그성 모델은 DB 레지스트리가 담당.
    monkeypatch.setattr(settings, "image_classification_extra_models", "")
    assert resolve_vlm_model("qwen2-vl-7b")["repo"] == "Qwen/Qwen2-VL-7B-Instruct"
    assert resolve_vlm_model("Qwen/Qwen2-VL-7B-Instruct")["name"] == "qwen2-vl-7b"
    assert resolve_vlm_model(None)["name"] == DEFAULT_VLM_NAME
    assert resolve_vlm_model("qwen2.5-vl-7b") is None  # 시드 이관분 — 폴백에 없음
    assert resolve_vlm_model("없는모델") is None
