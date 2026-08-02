# SPDX-License-Identifier: Apache-2.0
"""리랭커 평가 로직 테스트 — 스텁 모델로 torch 없이 순위 계산을 검증한다."""

from finetune.dataset import Record
from finetune.reranker import evaluate_reranker


class StubCrossEncoder:
    """후보 텍스트→점수 매핑으로 predict 를 흉내내는 스텁."""

    def __init__(self, scores: dict):
        self.scores = scores

    def predict(self, pairs):
        return [self.scores[cand] for _query, cand in pairs]


def _rec(positive, negatives):
    return Record(query="q", positive=positive, negatives=negatives, meta={})


def test_positive_ranked_first():
    rec = _rec("정답", ["오답1", "오답2"])
    model = StubCrossEncoder({"정답": 0.9, "오답1": 0.2, "오답2": 0.1})
    m = evaluate_reranker(model, [rec], k=5)
    assert m["hit_rate@5"] == 1.0
    assert m["mrr@5"] == 1.0
    assert m["n"] == 1


def test_positive_ranked_second():
    rec = _rec("정답", ["오답1", "오답2"])
    model = StubCrossEncoder({"정답": 0.5, "오답1": 0.9, "오답2": 0.1})
    m = evaluate_reranker(model, [rec], k=5)
    assert m["mrr@5"] == 0.5  # 2위 → 1/2


def test_skips_records_without_candidates():
    rec = _rec("정답", [])  # 비교 대상 없음
    m = evaluate_reranker(StubCrossEncoder({"정답": 1.0}), [rec], k=5)
    assert m == {}


def test_empty_records():
    assert evaluate_reranker(StubCrossEncoder({}), [], k=5) == {}
