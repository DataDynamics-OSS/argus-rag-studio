# SPDX-License-Identifier: Apache-2.0
"""데이터셋 로더·검증 스모크 테스트 — 학습 의존성(torch) 없이 동작해야 한다.

실행: cd extensions/retrieval-fine-tuning && python -m pytest -q
"""

import os

import pytest

from finetune.dataset import load_split
from finetune.schema import Manifest, load_manifest, validate_record

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "samples", "dataset")


def test_manifest_loads():
    m = load_manifest(SAMPLE)
    assert m.base_model == "intfloat/multilingual-e5-large"
    assert m.embedding_dim == 1024
    assert m.task == "embedding"
    assert m.prompt_format == "e5"


def test_manifest_missing_keys():
    with pytest.raises(ValueError):
        Manifest.from_dict({"name": "x"})


def test_train_split_loads_and_validates():
    records = load_split(SAMPLE, "train")
    assert len(records) == 6
    assert all(r.query and r.positive for r in records)
    assert all(r.negatives for r in records)  # 샘플은 전부 하드네거티브 보유


def test_valid_split_loads():
    records = load_split(SAMPLE, "valid")
    assert len(records) == 3


@pytest.mark.parametrize(
    "rec,expect_err",
    [
        ({"query": "q", "positive": "p", "negatives": ["n"]}, False),
        ({"query": "", "positive": "p", "negatives": []}, True),
        ({"query": "q", "positive": "p", "negatives": "not-a-list"}, True),
        ({"query": "q"}, True),
    ],
)
def test_validate_record(rec, expect_err):
    errs = validate_record(rec, 1)
    assert bool(errs) == expect_err
