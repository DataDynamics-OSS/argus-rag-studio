# SPDX-License-Identifier: Apache-2.0
"""Argus 데이터셋·매니페스트·모델 메타데이터 스키마와 검증.

순수 표준 라이브러리만 사용한다(torch/sentence-transformers 불필요).
데이터 검증은 학습 의존성 없이도 수행할 수 있어야 한다.

계약:
    입력  : <dataset_dir>/{manifest.json, train.jsonl, valid.jsonl}
            (test 는 Argus 가 보유, 내보내지 않음)
    레코드: {"query": str, "positive": str, "negatives": [str, ...], "meta": {...}}
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

VALID_TASKS = ("embedding", "reranker")
VALID_PROMPT = ("e5", "none")


@dataclass
class Manifest:
    """데이터셋 매니페스트 — 학습기가 알아야 할 메타데이터."""

    dataset_id: str
    base_model: str
    embedding_dim: int
    name: str = ""
    task: str = "embedding"           # embedding | reranker
    prompt_format: str = "e5"         # e5(query:/passage: 접두) | none
    split_strategy: str = "by_document"
    mining_model: str | None = None   # 하드네거티브 마이닝에 쓴 임베딩 모델
    glossary_version: str | None = None
    counts: dict = field(default_factory=dict)
    created_at: str | None = None

    @staticmethod
    def from_dict(d: dict) -> "Manifest":
        missing = [k for k in ("dataset_id", "base_model", "embedding_dim") if k not in d]
        if missing:
            raise ValueError(f"manifest.json 필수 키 누락: {missing}")
        if d.get("task", "embedding") not in VALID_TASKS:
            raise ValueError(f"task 는 {VALID_TASKS} 중 하나여야 합니다: {d.get('task')!r}")
        if d.get("prompt_format", "e5") not in VALID_PROMPT:
            raise ValueError(f"prompt_format 는 {VALID_PROMPT} 중 하나여야 합니다: {d.get('prompt_format')!r}")
        known = {f for f in Manifest.__dataclass_fields__}
        return Manifest(**{k: v for k, v in d.items() if k in known})


def load_manifest(dataset_dir: str) -> Manifest:
    path = os.path.join(dataset_dir, "manifest.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"매니페스트가 없습니다: {path}")
    with open(path, encoding="utf-8") as f:
        return Manifest.from_dict(json.load(f))


def validate_record(rec: object, line_no: int) -> list[str]:
    """학습 레코드 한 건을 검증하고 오류 메시지 목록을 반환한다(없으면 빈 목록)."""
    errs: list[str] = []
    if not isinstance(rec, dict):
        return [f"line {line_no}: JSON 객체가 아닙니다"]
    q = rec.get("query")
    if not isinstance(q, str) or not q.strip():
        errs.append(f"line {line_no}: 'query' 는 비어 있지 않은 문자열이어야 합니다")
    p = rec.get("positive")
    if not isinstance(p, str) or not p.strip():
        errs.append(f"line {line_no}: 'positive' 는 비어 있지 않은 문자열이어야 합니다")
    negs = rec.get("negatives", [])
    if not isinstance(negs, list) or any(not isinstance(n, str) for n in negs):
        errs.append(f"line {line_no}: 'negatives' 는 문자열 배열이어야 합니다")
    meta = rec.get("meta", {})
    if meta is not None and not isinstance(meta, dict):
        errs.append(f"line {line_no}: 'meta' 는 객체여야 합니다")
    return errs
