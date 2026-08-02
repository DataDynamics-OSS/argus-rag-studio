# SPDX-License-Identifier: Apache-2.0
"""임베딩 프로바이더 추상화.

provider 종류:
    - ``OpenAICompatibleProvider``: ``POST {server_url}/embeddings`` (TEI / Ollama-proxy /
      vLLM / OpenAI 등 OpenAI 호환 엔드포인트). bge-m3 는 보통 HF TEI 로 서빙한다.
    - ``HashProvider``: 외부 서버 없이 텍스트 해시로 결정적 더미 벡터를 만든다. 의미적
      품질은 없지만 인제스천/검색 배선을 오프라인·에어갭·CI 에서 검증할 수 있다.

모든 프로바이더는 ``embed(texts) -> list[list[float]]`` 단일 메서드를 구현한다.
차원(dim)은 컬렉션의 ``embedding_dim`` 과 일치해야 하며, 검증은 호출 측(service)에서 한다.
"""

import hashlib
import logging
import math
import struct
from abc import ABC, abstractmethod

import httpx

from app.core.config import settings
from app.core.http import auth_headers

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """임베딩 프로바이더 인터페이스."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """텍스트 리스트를 임베딩 벡터 리스트로 변환한다(순서 보존)."""
        ...

    async def aclose(self) -> None:
        """리소스 정리(선택)."""
        return


class OpenAICompatibleProvider(EmbeddingProvider):
    """OpenAI 호환 ``/embeddings`` 엔드포인트 클라이언트.

    server_url/model 은 컬렉션별로 다를 수 있어 명시 인자로 받는다. api_key/timeout 은
    미지정 시 전역 설정값을 사용한다(시크릿은 DB 가 아니라 서버 설정에서 관리)."""

    def __init__(
        self,
        server_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
    ) -> None:
        base = (server_url or settings.embedding_server_url).rstrip("/")
        self._model = model or settings.embedding_model
        # 엔드포인트 URL 규약은 기반 환경 프로파일에 위임(기본은 {base}/embeddings).
        from app.platform.factory import get_platform_profile
        self._url = get_platform_profile().embedding_endpoint_url(base, self._model)
        key = api_key if api_key is not None else settings.embedding_api_key
        headers = {"Content-Type": "application/json"}
        headers.update(auth_headers(
            key, settings.embedding_auth_header, settings.embedding_auth_scheme
        ))
        self._client = httpx.AsyncClient(
            timeout=timeout or settings.embedding_timeout, headers=headers
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = await self._client.post(self._url, json={"model": self._model, "input": texts})
        if resp.status_code != 200:
            raise RuntimeError(
                f"임베딩 서버 오류({resp.status_code}): {resp.text[:200]} @ {self._url}"
            )
        data = resp.json()
        # OpenAI 형식: {"data": [{"index": i, "embedding": [...]}, ...]}
        items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
        return [item["embedding"] for item in items]

    async def aclose(self) -> None:
        await self._client.aclose()


class HashProvider(EmbeddingProvider):
    """결정적 해시 기반 더미 임베딩(외부 서버 불필요).

    각 토큰을 SHA-256 으로 해시해 차원 버킷에 누적하고 L2 정규화한다. 같은 텍스트는
    항상 같은 벡터를 내며, 외부 의존 없이 파이프라인 전체를 검증할 수 있다.
    """

    def __init__(self, dim: int | None = None) -> None:
        self._dim = dim or settings.embedding_default_dim

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        tokens = text.lower().split() or [text.lower()]
        for tok in tokens:
            digest = hashlib.sha256(tok.encode("utf-8")).digest()
            # 8바이트씩 잘라 (bucket, weight) 쌍으로 사용
            for i in range(0, len(digest) - 4, 4):
                bucket = struct.unpack(">I", digest[i : i + 4])[0] % self._dim
                sign = 1.0 if (digest[i] & 1) else -1.0
                vec[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


class LocalFastEmbedProvider(EmbeddingProvider):
    """FastEmbed(ONNX) 기반 자체(in-process) 임베딩 — 외부 서버 불필요.

    모델 파일을 프로세스에 직접 로딩해 벡터를 계산한다(최초 1회 다운로드 후 캐시).
    지원 모델은 ``list_local_models()`` 로 확인하며, 출력 차원은 모델별로 고정된다.
    FastEmbed 의 ``embed`` 는 동기·CPU 작업이라 ``asyncio.to_thread`` 로 이벤트 루프를 막지 않는다.
    """

    def __init__(self, model: str) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as e:  # 의존성 미설치
            raise RuntimeError(
                "로컬 임베딩(FastEmbed) 의존성이 없습니다. `pip install fastembed` 후 사용하세요."
            ) from e
        self._name = model
        self._model = TextEmbedding(model_name=model)

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(list(texts))]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        import asyncio
        return await asyncio.to_thread(self._embed_sync, texts)


def list_local_models(target_dim: int | None = None) -> list[dict]:
    """FastEmbed 가 지원하는 임베딩 모델 목록(선택적으로 target_dim 으로 필터).

    벡터 컬럼 차원과 맞는 모델만 노출해 차원 불일치를 원천 차단하는 용도다.
    FastEmbed 미설치 시 빈 리스트를 반환한다(엔드포인트가 안전하게 빈 목록 응답)."""
    try:
        from fastembed import TextEmbedding
    except ImportError:
        return []
    out: list[dict] = []
    for m in TextEmbedding.list_supported_models():
        dim = m.get("dim")
        if target_dim is not None and dim != target_dim:
            continue
        out.append({
            "model": m["model"],
            "dim": dim,
            "size_gb": m.get("size_in_GB"),
            "description": (m.get("description") or "")[:300],
        })
    return sorted(out, key=lambda x: x["model"])


def create_provider() -> EmbeddingProvider:
    """settings.embedding_provider 에 따라 전역 기본 프로바이더를 생성한다."""
    return create_provider_from(
        settings.embedding_provider, settings.embedding_server_url,
        settings.embedding_model, settings.embedding_default_dim,
    )


def create_provider_from(
    provider: str, server_url: str | None, model: str, dim: int,
) -> EmbeddingProvider:
    """명시 설정(컬렉션별)으로 프로바이더를 생성한다.

    - ``hash``: 외부 서버 불필요(오프라인). dim 으로 더미 벡터 차원을 맞춘다.
    - ``local``: FastEmbed 로 프로세스 내에서 직접 임베딩(서버 불필요, 실제 의미 벡터).
    - 그 외(openai_compatible): server_url/model 로 OpenAI 호환 엔드포인트에 연결.
    """
    kind = (provider or "openai_compatible").lower()
    if kind == "hash":
        logger.info("임베딩 프로바이더 생성: hash (오프라인 더미, dim=%d)", dim)
        return HashProvider(dim)
    if kind == "local":
        logger.info("임베딩 프로바이더 생성: local FastEmbed (model=%s, dim=%d)", model, dim)
        return LocalFastEmbedProvider(model)
    logger.info(
        "임베딩 프로바이더 생성: openai_compatible (%s, model=%s, dim=%d)",
        server_url or settings.embedding_server_url, model, dim,
    )
    return OpenAICompatibleProvider(server_url=server_url, model=model)
