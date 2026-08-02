# SPDX-License-Identifier: Apache-2.0
"""임베딩 서비스 — 컬렉션별 프로바이더 캐시 + 배치 임베딩 + 차원 검증.

컬렉션마다 임베딩 프로바이더/모델/엔드포인트가 다를 수 있으므로, (provider, server_url,
model, dim) 키로 프로바이더를 캐시해 재사용한다. 같은 설정의 컬렉션들은 한 클라이언트를
공유한다. api_key 는 전역 설정에서 관리한다(시크릿을 DB 에 평문 저장하지 않음)."""

import logging

from app.core.config import settings
from app.core.http import auth_headers
from app.embedding.provider import EmbeddingProvider, create_provider_from

logger = logging.getLogger(__name__)

# (provider, server_url, model, dim) -> 프로바이더 인스턴스
_providers: dict[tuple[str, str, str, int], EmbeddingProvider] = {}


def provider_for(*, provider: str, server_url: str | None, model: str, dim: int) -> EmbeddingProvider:
    """설정에 맞는 임베딩 프로바이더를 캐시에서 가져온다(없으면 생성)."""
    key = (
        (provider or "openai_compatible").lower(),
        (server_url or "").rstrip("/"),
        model or "",
        int(dim),
    )
    p = _providers.get(key)
    if p is None:
        p = create_provider_from(provider, server_url, model, dim)
        _providers[key] = p
    return p


async def shutdown_providers() -> None:
    """앱 종료 시 캐시된 모든 프로바이더의 리소스를 정리한다."""
    for p in _providers.values():
        try:
            await p.aclose()
        except Exception as e:  # 정리 실패는 종료를 막지 않는다
            logger.warning("임베딩 프로바이더 정리 실패: %s", e)
    _providers.clear()


# 하위 호환 별칭(main.py lifespan 에서 사용)
shutdown_provider = shutdown_providers


async def embed_texts(
    texts: list[str],
    *,
    provider: str,
    server_url: str | None,
    model: str,
    dim: int,
    is_query: bool = False,
) -> list[list[float]]:
    """텍스트들을 컬렉션 설정의 프로바이더로 임베딩하고 차원을 검증해 반환한다.

    ``is_query`` 는 검색 쿼리 여부. 기반 환경 프로파일이 쿼리/문서를 다르게 전처리하는
    instruction-aware 모델(Databricks=Qwen3-Embedding 등)을 위해 임베딩 직전 텍스트를 변환한다
    (쿼리에만 지시문 부착, 문서는 원문). StandardProfile 에서는 양쪽 모두 원문 그대로다.

    Raises:
        RuntimeError: 임베딩 서버 오류 또는 반환 차원이 ``dim`` 과 불일치할 때.
    """
    if not texts:
        return []

    from app.platform.factory import get_platform_profile
    profile = get_platform_profile()
    fmt = profile.embedding_query_text if is_query else profile.embedding_doc_text

    emb = provider_for(provider=provider, server_url=server_url, model=model, dim=dim)
    out: list[list[float]] = []
    batch_size = max(1, settings.embedding_batch_size)
    for start in range(0, len(texts), batch_size):
        batch = [fmt(t) for t in texts[start : start + batch_size]]
        vectors = await emb.embed(batch)
        if len(vectors) != len(batch):
            raise RuntimeError(
                f"임베딩 개수 불일치: 입력 {len(batch)} != 출력 {len(vectors)}"
            )
        for v in vectors:
            if len(v) != dim:
                raise RuntimeError(
                    f"임베딩 차원 불일치: 컬렉션 dim={dim} != 모델 출력 dim={len(v)}"
                )
        out.extend(vectors)
    return out


async def check_server_health(server_url: str) -> str:
    """임베딩 서버 접속 테스트. 호스트의 ``/health`` 를 먼저 시도하고, 없으면 ``/models`` 로 폴백.

    성공한 URL 을 반환하고, 실패 시 RuntimeError 를 던진다(라우터가 502 로 변환)."""
    from urllib.parse import urlparse

    import httpx

    raw = server_url if "://" in server_url else f"http://{server_url}"
    p = urlparse(raw)
    if not p.netloc:
        raise RuntimeError("올바른 서버 URL 이 아닙니다.")

    health_url = f"{p.scheme}://{p.netloc}/health"
    models_url = f"{raw.rstrip('/')}/models"
    headers = auth_headers(
        settings.embedding_api_key,
        settings.embedding_auth_header,
        settings.embedding_auth_scheme,
    )

    last_err = ""
    async with httpx.AsyncClient(timeout=5) as client:
        for url, hdr in ((health_url, {}), (models_url, headers)):
            try:
                resp = await client.get(url, headers=hdr)
                if resp.status_code == 200:
                    return url
                last_err = f"{resp.status_code} @ {url}"
            except Exception as e:  # 연결 자체 실패
                last_err = f"{e} @ {url}"
    raise RuntimeError(f"서버에 연결할 수 없습니다({last_err}).")


async def list_remote_models(server_url: str | None) -> list[str]:
    """OpenAI 호환 서버의 ``GET /models`` 로 제공 모델 ID 목록을 가져온다.

    사용자가 모델명을 외워 입력하지 않도록, 서버가 실제로 제공하는 모델을 보여주기 위함이다.
    (임베딩/채팅 구분 정보는 표준에 없어 전체 모델 ID 를 반환한다.)"""
    import httpx

    base = (server_url or settings.embedding_server_url).rstrip("/")
    url = f"{base}/models"
    headers = auth_headers(
        settings.embedding_api_key,
        settings.embedding_auth_header,
        settings.embedding_auth_scheme,
    )
    async with httpx.AsyncClient(timeout=settings.embedding_timeout, headers=headers) as client:
        resp = await client.get(url)
    if resp.status_code != 200:
        raise RuntimeError(f"모델 목록 조회 실패({resp.status_code}): {resp.text[:200]} @ {url}")
    data = resp.json()
    items = data.get("data") if isinstance(data, dict) else data
    ids = [it.get("id") for it in (items or []) if isinstance(it, dict) and it.get("id")]
    return sorted(set(ids))


async def probe_dimension(server_url: str | None, model: str) -> int:
    """OpenAI 호환 임베딩 서버에 샘플 텍스트 1개를 보내 반환 벡터의 차원을 알아낸다.

    컬렉션 생성 시 사용자가 차원을 직접 입력하지 않도록(오류 방지) 자동 감지하는 용도.
    캐시를 쓰지 않고 일회용 프로바이더로 호출 후 정리한다."""
    from app.embedding.provider import OpenAICompatibleProvider

    provider = OpenAICompatibleProvider(server_url=server_url, model=model or None)
    try:
        vectors = await provider.embed(["차원 감지용 샘플 텍스트"])
    finally:
        await provider.aclose()
    if not vectors or not vectors[0]:
        raise RuntimeError("임베딩 서버가 빈 응답을 반환했습니다.")
    return len(vectors[0])


async def embed_for_collection(
    texts: list[str], collection, *, is_query: bool = False
) -> list[list[float]]:
    """컬렉션의 임베딩 설정을 적용해 텍스트들을 임베딩한다(인제스천/검색 공용).

    검색 쿼리는 ``is_query=True`` 로 호출해 instruction-aware 모델의 쿼리 전처리를 적용한다.
    인제스천(문서 청크)은 기본값(False)으로 원문을 임베딩한다."""
    return await embed_texts(
        texts,
        provider=collection.embedding_provider,
        server_url=collection.embedding_server_url,
        model=collection.embedding_model,
        dim=collection.embedding_dim,
        is_query=is_query,
    )
