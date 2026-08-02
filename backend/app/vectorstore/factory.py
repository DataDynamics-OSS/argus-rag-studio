# SPDX-License-Identifier: Apache-2.0
"""VectorStore 팩토리 — 설정(vector_store_provider)에 따라 백엔드 선택(캐시).

설정 변경(설정 화면 저장) 시 reset_vector_store() 로 캐시를 무효화해 다음 호출에서 재생성한다.
외부 어댑터(qdrant/weaviate/milvus)는 lazy import — 해당 클라이언트 라이브러리가 설치돼 있어야 한다.
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.vectorstore.base import VectorStore

logger = logging.getLogger(__name__)

_store: VectorStore | None = None
_store_key: tuple | None = None


def _current_key() -> tuple:
    return (settings.vector_store_provider, settings.vector_store_url)


def reset_vector_store() -> None:
    """캐시 무효화 — 설정 변경 후 호출하면 다음 get_vector_store() 가 새 설정으로 생성."""
    global _store, _store_key
    _store = None
    _store_key = None


def get_vector_store() -> VectorStore:
    """현재 설정의 VectorStore 인스턴스를 반환한다(provider/url 바뀌면 자동 재생성)."""
    global _store, _store_key
    key = _current_key()
    if _store is not None and _store_key == key:
        return _store

    provider = (settings.vector_store_provider or "pgvector").lower()
    if provider == "pgvector":
        from app.vectorstore.pgvector_store import PgVectorStore
        _store = PgVectorStore()
    elif provider == "qdrant":
        from app.vectorstore.qdrant_store import QdrantStore
        _store = QdrantStore(
            url=settings.vector_store_url, api_key=settings.vector_store_api_key or None,
            prefix=settings.vector_store_collection_prefix,
        )
    elif provider == "weaviate":
        from app.vectorstore.weaviate_store import WeaviateStore
        _store = WeaviateStore(
            url=settings.vector_store_url, api_key=settings.vector_store_api_key or None,
            prefix=settings.vector_store_collection_prefix,
        )
    elif provider == "milvus":
        from app.vectorstore.milvus_store import MilvusStore
        _store = MilvusStore(
            uri=settings.vector_store_url, token=settings.vector_store_api_key or None,
            prefix=settings.vector_store_collection_prefix,
        )
    elif provider == "databricks":
        # Mosaic AI Vector Search — 인증은 기반 환경의 databricks_host/token 을 재사용한다.
        from app.vectorstore.databricks_store import DatabricksVectorStore
        _store = DatabricksVectorStore(
            host=settings.databricks_host,
            token=settings.databricks_token,
            endpoint=settings.vector_store_databricks_endpoint,
            catalog=settings.vector_store_databricks_catalog,
            schema=settings.vector_store_databricks_schema,
            prefix=settings.vector_store_collection_prefix,
        )
    else:
        raise ValueError(
            f"지원하지 않는 vector_store_provider='{provider}'. "
            "pgvector | qdrant | weaviate | milvus | databricks 중에서 선택하세요."
        )
    _store_key = key
    logger.info("VectorStore provider=%s url=%s", provider, settings.vector_store_url or "-")
    return _store
