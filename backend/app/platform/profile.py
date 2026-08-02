# SPDX-License-Identifier: Apache-2.0
"""기반 환경(Platform Profile) 어댑터.

`platform.base` 설정에 따라 임베딩/LLM(이후 단계: 벡터스토어/스토리지)의 기본값과 동작을
한 곳에서 공급한다. 호출부에 `if databricks` 분기를 흩뿌리지 않고 프로파일 클래스로 격리하는
것이 목적이다(StandardProfile = 현행 동작, DatabricksProfile = Databricks 규약).

프로파일은 두 역할만 한다:
  1) 기본값 resolver — 미설정/신규 생성 시 채울 모델·엔드포인트·차원 기본값(``*_defaults``).
  2) 동작 훅 — 쿼리 instruction(임베딩), 엔드포인트 URL 규약 등.

명시값(컬렉션·설정 override)이 항상 프로파일 기본값보다 우선한다. 프로파일은 settings 를
직접 참조하지 않고 필요한 값(예: 쿼리 instruction)을 생성 시점에 주입받아 단위 테스트가
쉽도록 한다(주입은 ``factory.get_platform_profile`` 이 담당).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class PlatformProfile(ABC):
    """기반 환경 프로파일 인터페이스."""

    name: str = "base"

    # ── 임베딩 ───────────────────────────────────────────────────────────────
    @abstractmethod
    def embedding_query_text(self, text: str) -> str:
        """검색 쿼리 텍스트를 임베딩 직전 변환한다(instruction-aware 모델용 지시문 부착 등)."""
        ...

    @abstractmethod
    def embedding_doc_text(self, text: str) -> str:
        """문서(청크) 텍스트를 임베딩 직전 변환한다. 보통 원문 그대로."""
        ...

    def embedding_endpoint_url(self, base_url: str, model: str) -> str:
        """OpenAI 호환 임베딩 엔드포인트 URL. 기본은 ``{base}/embeddings``."""
        return f"{base_url.rstrip('/')}/embeddings"

    def embedding_defaults(self) -> dict:
        """신규 컬렉션·미설정 시 채울 임베딩 기본값({model, dim, metric} 일부/전체)."""
        return {}

    # ── LLM ─────────────────────────────────────────────────────────────────
    def llm_endpoint_url(self, base_url: str) -> str:
        """OpenAI 호환 채팅 엔드포인트 URL. 기본은 ``{base}/chat/completions``."""
        return f"{base_url.rstrip('/')}/chat/completions"

    def llm_defaults(self) -> dict:
        """미설정 시 채울 LLM 기본값({server_url, model} 일부/전체)."""
        return {}

    # ── 벡터스토어 ─────────────────────────────────────────────────────────────
    def vector_store_defaults(self) -> dict:
        """이 기반 환경에서 권장하는 벡터스토어 기본값({provider, ...})."""
        return {}

    # ── 스토리지 ───────────────────────────────────────────────────────────────
    def storage_kind(self) -> str:
        """이 기반 환경에서 권장하는 스토리지 백엔드(s3 | uc_volumes)."""
        return "s3"


class StandardProfile(PlatformProfile):
    """기본(self-host / OpenAI 호환) 프로파일 — 기존 동작을 그대로 유지한다.

    쿼리/문서 모두 원문 그대로 임베딩한다(bge-m3 등은 지시문 불필요)."""

    name = "standard"

    def embedding_query_text(self, text: str) -> str:
        return text

    def embedding_doc_text(self, text: str) -> str:
        return text


class DatabricksProfile(PlatformProfile):
    """Databricks 기반 환경 프로파일.

    Databricks Foundation Model API / Mosaic AI Model Serving 은 OpenAI 호환
    ``/serving-endpoints`` 를 제공하므로 엔드포인트 규약은 기본(``/embeddings``,
    ``/chat/completions``)을 그대로 쓰되, **쿼리 instruction 비대칭**을 적용한다.

    Qwen3-Embedding 류 instruction-aware 모델은 쿼리에만 지시문을 붙여야 검색 성능이 나오고,
    Databricks 서빙이 적용하는 규약과 글자 단위로 일치해야 같은 벡터 공간에 들어간다. 따라서
    지시문은 운영자가 ``embedding.query_instruction`` 으로 정확히 지정할 수 있고, 미지정 시
    아래 기본값을 쓴다.
    """

    name = "databricks"

    # Qwen3-Embedding 권장 검색 지시문(쿼리 측). 운영 시 Databricks 서빙 규약에 맞춰 override 가능.
    DEFAULT_QUERY_INSTRUCTION = (
        "Instruct: Given a search query, retrieve relevant passages that answer the query\nQuery: "
    )
    # 기반 환경=databricks 의 임베딩 기본 모델(신규 컬렉션 기본값). 차원은 bge-m3 와 동일한 1024.
    DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
    DEFAULT_EMBEDDING_DIM = 1024

    def __init__(self, query_instruction: str | None = None) -> None:
        # 빈 문자열/None 이면 기본 지시문 사용. 명시값이 있으면 그대로(글자 단위 일치 목적).
        self._query_instruction = query_instruction or self.DEFAULT_QUERY_INSTRUCTION

    def embedding_query_text(self, text: str) -> str:
        return f"{self._query_instruction}{text}"

    def embedding_doc_text(self, text: str) -> str:
        return text

    def embedding_defaults(self) -> dict:
        return {
            "model": self.DEFAULT_EMBEDDING_MODEL,
            "dim": self.DEFAULT_EMBEDDING_DIM,
            "metric": "cosine",
        }

    def vector_store_defaults(self) -> dict:
        # Databricks 기반 환경의 권장 벡터스토어 = Mosaic AI Vector Search.
        return {"provider": "databricks"}

    def storage_kind(self) -> str:
        # Databricks 기반 환경의 권장 스토리지 = Unity Catalog Volumes.
        return "uc_volumes"
