# SPDX-License-Identifier: Apache-2.0
"""컬렉션 생성 검증 — 벡터 스토어 고정 차원(fail-fast) 테스트.

pgvector 는 rag_chunks.embedding 이 DDL 에서 vector(N) 고정(전 컬렉션 공유)이라, 다른 차원의
컬렉션은 생성 시점에 거부해야 한다(아니면 색인 시점에야 "expected N dimensions" 로 실패).
"""

import pytest

from app.collections.service import _validate_store_dim
from app.core.config import settings


def test_matching_dim_passes():
    _validate_store_dim(settings.embedding_default_dim)  # 예외 없음


def test_mismatched_dim_rejected_on_pgvector():
    assert (settings.vector_store_provider or "pgvector").lower() == "pgvector"
    with pytest.raises(ValueError, match="고정"):
        _validate_store_dim(384)


def test_external_store_allows_any_dim(monkeypatch):
    # 외부 스토어(qdrant 등)는 컬렉션별 차원 생성이 가능하므로 통과해야 한다.
    monkeypatch.setattr(settings, "vector_store_provider", "qdrant")
    _validate_store_dim(384)  # 예외 없음