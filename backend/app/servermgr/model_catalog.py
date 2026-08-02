# SPDX-License-Identifier: Apache-2.0
"""모델 카탈로그 — 시드 기반 동기 조회(외부망 스크립트·폴백용).

**주 조회처는 모델 레지스트리(DB, app/modelreg)다** — design/model-registry.md.
이 모듈은 DB 없는 문맥에서만 쓴다:

  - ``scripts/pack_model.py`` — 외부망 머신에서 실행(DB 접근 불가). 시드 목록 + 명시
    ``--repo/--name`` 인자로 동작한다. 레지스트리에 등록한 비시드 모델은 모델 관리
    화면이 복사해 주는 명시 인자 명령으로 팩한다.
  - 버킷 키 규약(``bucket_key``) — 팩/설치/보유 확인이 공유하는 단일 출처.

항목 필드: kind/name/repo/source(hf|paddle)/target(hf-cache|flat)/approx_gb/note.
"""

from __future__ import annotations

from app.modelreg.seeds import SEED_MODELS, seed_entry


def list_models(kind: str | None = None) -> list[dict]:
    """시드 목록(동기) — 외부망 pack_model 폴백. 런타임 목록은 modelreg.list_models 사용."""
    out = []
    for m in SEED_MODELS:
        e = seed_entry(m)
        out.append({
            "kind": e["kind"], "name": e["name"], "repo": e["repo"], "source": e["source"],
            "target": e["target"], "approx_gb": e["params"].get("approx_gb"), "note": e["note"],
        })
    if kind:
        out = [m for m in out if m["kind"] == kind]
    return out


def resolve_model(kind: str, name: str) -> dict | None:
    """kind/name(또는 repo)으로 시드 항목 조회."""
    for m in list_models(kind):
        if m["name"] == name or m["repo"] == name:
            return m
    return None


def bucket_key(kind: str, name: str, revision: str, filename: str = "model.tar.zst") -> str:
    """모델 저장소(argus-models 버킷) 키 규약 — pack/설치/보유 확인이 공유하는 단일 출처."""
    return f"{kind}/{name}/{revision}/{filename}"
