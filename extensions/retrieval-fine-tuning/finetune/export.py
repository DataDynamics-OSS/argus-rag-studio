# SPDX-License-Identifier: Apache-2.0
"""학습 결과 내보내기 — 모델 아티팩트 + metadata.json.

모델 가져오기 계약:
    <output_dir>/
        model/          # sentence-transformers SavedModel
        metadata.json   # Argus 모델 레지스트리가 읽는 메타데이터
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from finetune.schema import Manifest

logger = logging.getLogger(__name__)


def export_model(
    model, output_dir: str, manifest: Manifest, train_info: dict, valid_metrics: dict, task: str = "embedding"
) -> str:
    """모델과 metadata.json 을 output_dir 에 저장하고 metadata 경로를 반환한다.

    task 가 ``reranker`` 이면 cross-encoder 로 간주하고 차원 대신 점수 모델 메타를 기록한다.
    """
    model_dir = os.path.join(output_dir, "model")
    os.makedirs(model_dir, exist_ok=True)
    model.save(model_dir)

    metadata = {
        "base_model": train_info.get("base_model", manifest.base_model),
        "task": task,
        "dataset_id": manifest.dataset_id,
        "dataset_name": manifest.name,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "train": train_info,
        "valid_metrics": valid_metrics,
    }

    if task == "reranker":
        # cross-encoder 는 벡터가 아니라 관련도 점수를 출력 — 차원 개념이 없다.
        metadata["format"] = "sentence-transformers-cross-encoder"
        metadata["num_labels"] = 1
    else:
        metadata["format"] = "sentence-transformers"
        metadata["prompt_format"] = manifest.prompt_format
        try:
            dim = int(model.get_sentence_embedding_dimension())
        except Exception:  # pragma: no cover
            dim = manifest.embedding_dim
        metadata["embedding_dim"] = dim
        if dim != manifest.embedding_dim:
            logger.warning(
                "주의: 학습 모델 차원(%d) 이 매니페스트 차원(%d) 과 다릅니다. "
                "Argus 등록 시 컬렉션 차원과 호환되는지 확인하세요.",
                dim, manifest.embedding_dim,
            )

    meta_path = os.path.join(output_dir, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    logger.info("내보내기 완료: %s", output_dir)
    return meta_path
