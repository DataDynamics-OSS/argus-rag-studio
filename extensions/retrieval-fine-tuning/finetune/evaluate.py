# SPDX-License-Identifier: Apache-2.0
"""검증(valid) 스플릿에 대한 간이 IR 평가 — 학습 중/직후 모니터링용.

주의: 이것은 학습기가 자체적으로 보는 valid 지표일 뿐이다. 모델의 최종 합격 판정은
Argus 가 보유한 **홀드아웃 골든셋(test)** 으로 내린다.
"""

from __future__ import annotations

import logging

from finetune.dataset import Record, apply_prompt
from finetune.schema import Manifest

logger = logging.getLogger(__name__)


def evaluate_ir(model, records: list[Record], manifest: Manifest, k: int = 5) -> dict:
    """valid 레코드로 hit_rate@k / mrr@k 를 계산한다.

    코퍼스는 valid 의 positive + 모든 negative 로 구성하고, 각 질의의 정답은 자신의
    positive 로 본다(질의-정답 1:1 가정).
    """
    if not records:
        return {}
    try:
        import numpy as np
    except ImportError as e:  # pragma: no cover
        raise ImportError("numpy 가 필요합니다.") from e

    pf = manifest.prompt_format
    # 코퍼스(중복 제거) — 정답 위치 추적
    corpus: list[str] = []
    seen: dict[str, int] = {}

    def add(passage: str) -> int:
        if passage not in seen:
            seen[passage] = len(corpus)
            corpus.append(passage)
        return seen[passage]

    gold_idx: list[int] = []
    for r in records:
        gold_idx.append(add(r.positive))
        for n in r.negatives:
            add(n)

    q_emb = model.encode(
        [apply_prompt(r.query, "query", pf) for r in records],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    c_emb = model.encode(
        [apply_prompt(p, "passage", pf) for p in corpus],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    sims = np.asarray(q_emb) @ np.asarray(c_emb).T  # (Q, C) 코사인(정규화 가정)

    hits = 0
    rr_sum = 0.0
    for i, gi in enumerate(gold_idx):
        order = np.argsort(-sims[i])
        rank = int(np.where(order == gi)[0][0]) + 1  # 1-based
        if rank <= k:
            hits += 1
        rr_sum += 1.0 / rank

    n = len(records)
    metrics = {f"hit_rate@{k}": round(hits / n, 4), f"mrr@{k}": round(rr_sum / n, 4), "n": n}
    logger.info("valid 평가: %s", metrics)
    return metrics
