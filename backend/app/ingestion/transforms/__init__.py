# SPDX-License-Identifier: Apache-2.0
"""인제스천 보강 transform 레지스트리 + 기본 파이프라인.

step1: 기본 파이프라인은 정적 상수(현행 동작 보존 — 표 빈칸 정리 always-on).
step2: 컬렉션별 버전 가능 프로파일로 대체 예정.
"""

from app.ingestion.transforms import builtins as _builtins  # noqa: F401 (등록 트리거)
from app.ingestion.transforms import image_captions as _image_captions  # noqa: F401 (등록 트리거)
from app.ingestion.transforms import pii as _pii  # noqa: F401 (등록 트리거)
from app.ingestion.transforms.base import (
    PHASES,
    REGISTRY,
    Transform,
    list_transforms,
    normalize_pipeline,
    register_transform,
    run_transforms,
    validate_pipeline,
)

# 기본 인제스천 파이프라인 — 컬렉션 프로파일 미지정 시 적용(현행 동작 = 표 빈칸 정리).
DEFAULT_PIPELINE: dict[str, list[dict]] = {
    "post_parse": [{"id": "table_row_cleanup"}],
    "post_chunk": [],
}

__all__ = [
    "PHASES", "REGISTRY", "Transform", "list_transforms", "normalize_pipeline",
    "register_transform", "run_transforms", "validate_pipeline", "DEFAULT_PIPELINE",
]
