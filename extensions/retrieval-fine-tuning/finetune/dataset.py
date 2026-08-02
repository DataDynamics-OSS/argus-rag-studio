# SPDX-License-Identifier: Apache-2.0
"""Argus 가 내보낸 데이터셋(JSONL) 로더·검증·학습 예시 빌더.

JSONL 파싱·검증은 표준 라이브러리만 쓴다. 학습 예시(InputExample) 빌드는
``build_input_examples`` 에서 sentence-transformers 를 지연 임포트한다.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from finetune.schema import Manifest, load_manifest, validate_record

logger = logging.getLogger(__name__)


@dataclass
class Record:
    query: str
    positive: str
    negatives: list[str]
    meta: dict


def _read_jsonl(path: str) -> list[tuple[int, dict]]:
    rows: list[tuple[int, dict]] = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            rows.append((i, json.loads(line)))
    return rows


def load_split(dataset_dir: str, split: str) -> list[Record]:
    """``train``/``valid`` 스플릿을 읽어 검증된 Record 목록으로 반환한다."""
    path = os.path.join(dataset_dir, f"{split}.jsonl")
    if not os.path.exists(path):
        if split == "valid":
            logger.warning("valid.jsonl 이 없습니다 — 검증 평가를 건너뜁니다: %s", path)
            return []
        raise FileNotFoundError(f"{split}.jsonl 이 없습니다: {path}")

    errors: list[str] = []
    records: list[Record] = []
    for line_no, rec in _read_jsonl(path):
        errs = validate_record(rec, line_no)
        if errs:
            errors.extend(errs)
            continue
        records.append(
            Record(
                query=rec["query"].strip(),
                positive=rec["positive"].strip(),
                negatives=[n.strip() for n in rec.get("negatives", []) if n.strip()],
                meta=rec.get("meta") or {},
            )
        )
    if errors:
        raise ValueError(f"{split}.jsonl 검증 실패 ({len(errors)}건):\n  " + "\n  ".join(errors[:20]))
    return records


def apply_prompt(text: str, kind: str, prompt_format: str) -> str:
    """모델별 입력 접두 처리. e5 계열은 query:/passage: 접두가 필요하다."""
    if prompt_format == "e5":
        return f"{'query' if kind == 'query' else 'passage'}: {text}"
    return text


def build_input_examples(records: list[Record], manifest: Manifest, max_negatives: int = 1):
    """sentence-transformers 학습용 InputExample 목록을 만든다(지연 임포트).

    스마트 배칭은 한 배치 내 예시의 텍스트 개수가 같아야 하므로, 데이터셋 전체에서
    하드네거티브 사용 여부를 일관되게 결정한다.
      - 모든 레코드가 네거티브를 1개 이상 가지면 → [query, positive, negative] (하드네거티브 1개)
      - 그렇지 않으면 → [query, positive] (in-batch 네거티브만 사용)
    """
    try:
        from sentence_transformers import InputExample
    except ImportError as e:  # pragma: no cover - 학습 의존성 미설치 환경
        raise ImportError(
            "sentence-transformers 가 필요합니다. `pip install -r requirements.txt` 후 사용하세요."
        ) from e

    pf = manifest.prompt_format
    use_hard = max_negatives >= 1 and all(r.negatives for r in records)
    if max_negatives >= 1 and not use_hard:
        logger.warning("일부 레코드에 네거티브가 없어 하드네거티브를 끄고 (query, positive) 쌍으로 학습합니다.")

    examples = []
    for r in records:
        texts = [apply_prompt(r.query, "query", pf), apply_prompt(r.positive, "passage", pf)]
        if use_hard:
            texts.append(apply_prompt(r.negatives[0], "passage", pf))
        examples.append(InputExample(texts=texts))
    logger.info("학습 예시 %d건 구성 (하드네거티브=%s)", len(examples), use_hard)
    return examples


__all__ = ["Record", "load_split", "load_manifest", "apply_prompt", "build_input_examples"]
