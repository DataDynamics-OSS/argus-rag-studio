# SPDX-License-Identifier: Apache-2.0
"""VLM 모델 카탈로그 — 시드 기반 동기 폴백.

**주 조회처는 모델 레지스트리(DB, app/modelreg)다** — design/model-registry.md.
이 모듈은 DB 를 쓸 수 없는 동기 문맥(컨테이너 스펙 빌더의 폴백)과 구 설정 CSV
(``image_classification.extra_models``) 파싱(레지스트리 마이그레이션용)만 담당한다.

CSV 항목 형식(구 방식 — 신규 등록은 모델 관리 화면 사용)::

    name=repo[@max_len]   예) qwen25-vl-72b=Qwen/Qwen2.5-VL-72B-Instruct@32768
    repo                  예) openbmb/MiniCPM-V-2_6  (name 은 repo 끝 이름 소문자)
"""

from __future__ import annotations

import logging

from app.modelreg.seeds import DEFAULT_VLM_NAME, SEED_MODELS

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_VLM_NAME", "PREDEFINED_VLM_MODELS", "list_vlm_models", "resolve_vlm_model"]

# 시드에서 파생 — 단일 출처는 app/modelreg/seeds.py
PREDEFINED_VLM_MODELS: list[dict] = [
    {"name": m["name"], "repo": m["repo"], "max_len": m["params"]["max_len"],
     "note": m["note"], "builtin": True}
    for m in SEED_MODELS if m["kind"] == "vlm"
]


def _parse_extra(entry: str) -> dict | None:
    """설정 CSV 항목 1개 파싱 — ``name=repo[@max_len]`` 또는 ``repo``. 실패 시 None."""
    entry = entry.strip()
    if not entry:
        return None
    max_len = 8192
    if "@" in entry:
        entry, _, tail = entry.rpartition("@")
        try:
            max_len = int(tail)
        except ValueError:
            logger.warning("extra_models 항목의 max_len 무시(정수 아님): %s", tail)
    if "=" in entry:
        name, _, repo = entry.partition("=")
        name, repo = name.strip(), repo.strip()
    else:
        repo = entry
        name = repo.rsplit("/", 1)[-1].lower()
    if not name or not repo:
        return None
    return {"name": name, "repo": repo, "max_len": max_len, "note": "설정 추가", "builtin": False}


def list_vlm_models() -> list[dict]:
    """사전 정의 + 설정 추가 모델 병합 목록(같은 name 은 설정이 우선)."""
    from app.core.config import settings

    by_name = {m["name"]: dict(m) for m in PREDEFINED_VLM_MODELS}
    raw = getattr(settings, "image_classification_extra_models", "") or ""
    for entry in raw.split(","):
        m = _parse_extra(entry)
        if m:
            by_name[m["name"]] = m
    # 사전 정의 순서 유지 + 추가분은 뒤에.
    ordered = [by_name.pop(m["name"]) for m in PREDEFINED_VLM_MODELS if m["name"] in by_name]
    return ordered + list(by_name.values())


def resolve_vlm_model(key: str | None) -> dict | None:
    """name(served-model-name) 또는 repo 로 카탈로그에서 조회. 미지정이면 기본 모델."""
    models = list_vlm_models()
    if not key or not str(key).strip():
        return next((m for m in models if m["name"] == DEFAULT_VLM_NAME), models[0] if models else None)
    k = str(key).strip()
    return next((m for m in models if m["name"] == k or m["repo"] == k), None)
