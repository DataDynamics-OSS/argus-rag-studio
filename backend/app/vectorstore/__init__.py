# SPDX-License-Identifier: Apache-2.0
"""벡터 저장/검색 추상화 — pgvector ↔ 외부 벡터DB(Qdrant 등) 교체 가능 계층.

설계: design/vector-store.md
원칙: PostgreSQL 을 벡터 정본(source of truth)으로 두고, 외부 스토어는 재구축 가능한 ANN 색인.
"""

from app.vectorstore.base import CollectionSpec, VectorHit, VectorItem, VectorStore
from app.vectorstore.factory import get_vector_store

__all__ = ["CollectionSpec", "VectorHit", "VectorItem", "VectorStore", "get_vector_store"]
