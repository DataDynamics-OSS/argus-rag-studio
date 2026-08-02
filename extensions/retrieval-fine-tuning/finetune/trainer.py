# SPDX-License-Identifier: Apache-2.0
"""임베딩 모델 파인튜닝 — sentence-transformers + MultipleNegativesRankingLoss.

대조 학습(contrastive): (query, positive)[, hard_negative] 를 가까이/멀리 배치하도록
베이스 모델을 추가 학습한다. torch/sentence-transformers 는 지연 임포트한다.
"""

from __future__ import annotations

import logging

from finetune.dataset import Record, build_input_examples
from finetune.schema import Manifest

logger = logging.getLogger(__name__)


def train(
    records: list[Record],
    manifest: Manifest,
    *,
    base_model: str | None = None,
    epochs: int = 3,
    batch_size: int = 32,
    lr: float = 2e-5,
    max_negatives: int = 1,
    warmup_ratio: float = 0.1,
    device: str | None = None,
    use_amp: bool | None = None,
    checkpoint_steps: int = 0,
    checkpoint_path: str | None = None,
):
    """학습을 수행하고 (model, info) 를 반환한다.

    info 에는 학습 설정·스텝 수 등 metadata.json 에 기록할 값이 담긴다.

    대량 학습 옵션:
      - ``use_amp``: fp16 혼합정밀(GPU 속도↑·메모리↓). None 이면 CUDA 일 때만 자동 활성.
      - ``checkpoint_steps``>0 + ``checkpoint_path``: 장시간 학습 중 주기적 체크포인트 저장.
    """
    try:
        from sentence_transformers import SentenceTransformer, losses
        from torch.utils.data import DataLoader
    except ImportError as e:  # pragma: no cover - 학습 의존성 미설치 환경
        raise ImportError(
            "sentence-transformers·torch 가 필요합니다. `pip install -r requirements.txt` 후 사용하세요."
        ) from e

    base = base_model or manifest.base_model
    logger.info("베이스 모델 로드: %s (device=%s)", base, device or "auto")
    model = SentenceTransformer(base, device=device)

    # fp16 자동 결정 — 지정 없으면 CUDA 환경에서만 켠다(CPU 에선 AMP 가 오히려 손해/오류).
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

    examples = build_input_examples(records, manifest, max_negatives=max_negatives)
    loader = DataLoader(examples, shuffle=True, batch_size=batch_size)
    loss = losses.MultipleNegativesRankingLoss(model)

    steps_per_epoch = max(1, len(loader))
    warmup_steps = int(steps_per_epoch * epochs * warmup_ratio)
    logger.info(
        "학습 시작: epochs=%d batch=%d lr=%g steps/epoch=%d warmup=%d amp=%s",
        epochs, batch_size, lr, steps_per_epoch, warmup_steps, use_amp,
    )

    fit_kw: dict = dict(
        train_objectives=[(loader, loss)],
        epochs=epochs,
        warmup_steps=warmup_steps,
        optimizer_params={"lr": lr},
        show_progress_bar=True,
        use_amp=use_amp,
    )
    if checkpoint_path and checkpoint_steps > 0:
        fit_kw.update(
            checkpoint_path=checkpoint_path,
            checkpoint_save_steps=checkpoint_steps,
            checkpoint_save_total_limit=3,
        )
    model.fit(**fit_kw)

    info = {
        "base_model": base,
        "loss": "MultipleNegativesRankingLoss",
        "epochs": epochs,
        "batch_size": batch_size,
        "lr": lr,
        "max_negatives": max_negatives,
        "use_amp": use_amp,
        "steps": steps_per_epoch * epochs,
        "train_examples": len(examples),
    }
    return model, info
