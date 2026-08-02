# SPDX-License-Identifier: Apache-2.0
"""리랭커(cross-encoder) 파인튜닝 — sentence-transformers CrossEncoder.

(query, passage) 쌍의 관련도를 점수로 학습한다. positive→1.0, hard negative→0.0 의
이진 라벨로 BCE 학습한다. cross-encoder 는 임베딩과 달리 질의·패시지를 함께 입력하므로
e5 접두(query:/passage:)는 쓰지 않는다.

같은 Argus 데이터셋(query, positive, negatives[])을 그대로 재사용한다 — manifest.task 가
``reranker`` 이거나 CLI 에서 ``--task reranker`` 로 지정하면 이 경로로 학습한다.
torch/sentence-transformers 는 지연 임포트한다.
"""

from __future__ import annotations

import logging

from finetune.dataset import Record
from finetune.schema import Manifest

logger = logging.getLogger(__name__)


def _select_negatives(negs: list[str], max_negatives: int) -> list[str]:
    """max_negatives<=0 이면 전부, 아니면 앞에서 max_negatives 개만 사용."""
    return negs if max_negatives <= 0 else negs[:max_negatives]


def build_pair_examples(records: list[Record], max_negatives: int = 1):
    """CrossEncoder 학습용 (query, passage, label) 예시 목록(지연 임포트).

    positive 는 label 1.0, 각 hard negative 는 label 0.0.
    """
    try:
        from sentence_transformers import InputExample
    except ImportError as e:  # pragma: no cover - 학습 의존성 미설치 환경
        raise ImportError(
            "sentence-transformers 가 필요합니다. `pip install -r requirements.txt` 후 사용하세요."
        ) from e

    examples = []
    n_pos = n_neg = 0
    for r in records:
        examples.append(InputExample(texts=[r.query, r.positive], label=1.0))
        n_pos += 1
        for neg in _select_negatives(r.negatives, max_negatives):
            examples.append(InputExample(texts=[r.query, neg], label=0.0))
            n_neg += 1
    logger.info("리랭커 학습 예시 %d건 구성 (positive=%d, negative=%d)", len(examples), n_pos, n_neg)
    if n_neg == 0:
        logger.warning("네거티브가 없어 cross-encoder 학습이 무의미할 수 있습니다(전부 positive).")
    return examples


def train_reranker(
    records: list[Record],
    manifest: Manifest,
    *,
    base_model: str | None = None,
    epochs: int = 3,
    batch_size: int = 16,
    lr: float = 2e-5,
    max_negatives: int = 1,
    warmup_ratio: float = 0.1,
    device: str | None = None,
    use_amp: bool | None = None,
):
    """cross-encoder 리랭커를 파인튜닝하고 (model, info) 를 반환한다.

    ``use_amp``: fp16 혼합정밀(GPU 속도↑). None 이면 CUDA 환경에서만 자동 활성.
    """
    try:
        from sentence_transformers import CrossEncoder
        from torch.utils.data import DataLoader
    except ImportError as e:  # pragma: no cover - 학습 의존성 미설치 환경
        raise ImportError(
            "sentence-transformers·torch 가 필요합니다. `pip install -r requirements.txt` 후 사용하세요."
        ) from e

    base = base_model or manifest.base_model
    logger.info("베이스 리랭커 로드: %s (device=%s)", base, device or "auto")
    model = CrossEncoder(base, num_labels=1, device=device)

    if use_amp is None:
        dev = (device or "").lower()
        if dev.startswith("cuda"):
            use_amp = True
        elif dev in ("cpu", "mps"):
            use_amp = False
        else:
            try:
                import torch

                use_amp = bool(torch.cuda.is_available())
            except Exception:  # noqa: BLE001
                use_amp = False

    examples = build_pair_examples(records, max_negatives=max_negatives)
    loader = DataLoader(examples, shuffle=True, batch_size=batch_size)

    steps_per_epoch = max(1, len(loader))
    warmup_steps = int(steps_per_epoch * epochs * warmup_ratio)
    logger.info(
        "리랭커 학습 시작: epochs=%d batch=%d lr=%g steps/epoch=%d warmup=%d amp=%s",
        epochs, batch_size, lr, steps_per_epoch, warmup_steps, use_amp,
    )

    model.fit(
        train_dataloader=loader,
        epochs=epochs,
        warmup_steps=warmup_steps,
        optimizer_params={"lr": lr},
        show_progress_bar=True,
        use_amp=use_amp,
    )

    info = {
        "base_model": base,
        "loss": "BCEWithLogitsLoss",
        "epochs": epochs,
        "batch_size": batch_size,
        "lr": lr,
        "max_negatives": max_negatives,
        "use_amp": use_amp,
        "steps": steps_per_epoch * epochs,
        "train_examples": len(examples),
    }
    return model, info


def evaluate_reranker(model, records: list[Record], k: int = 5) -> dict:
    """valid 레코드별로 (positive + 그 레코드의 negatives)를 재정렬해 hit@k / mrr@k 계산.

    각 질의의 후보군은 자신의 positive(정답, index 0)와 hard negative 들로 구성한다.
    cross-encoder 점수가 높은 순으로 정렬해 정답의 순위를 본다.
    """
    if not records:
        return {}
    hits = 0
    rr_sum = 0.0
    evaluated = 0
    for r in records:
        candidates = [r.positive] + r.negatives
        if len(candidates) < 2:
            continue  # 비교 대상이 없으면 순위 무의미
        scores = model.predict([[r.query, c] for c in candidates])
        order = sorted(range(len(candidates)), key=lambda i: -float(scores[i]))
        rank = order.index(0) + 1  # 정답(index 0)의 1-based 순위
        if rank <= k:
            hits += 1
        rr_sum += 1.0 / rank
        evaluated += 1
    if evaluated == 0:
        return {}
    metrics = {f"hit_rate@{k}": round(hits / evaluated, 4), f"mrr@{k}": round(rr_sum / evaluated, 4), "n": evaluated}
    logger.info("리랭커 valid 평가: %s", metrics)
    return metrics
