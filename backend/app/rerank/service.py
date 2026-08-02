# SPDX-License-Identifier: Apache-2.0
"""리랭킹 서비스 — 하이브리드 검색 결과 top-N 을 정밀 재정렬한다.

provider(설정 rerank.provider):
    - ``none``: 재정렬 없이 입력 순서 유지(RRF 융합 순서 그대로)
    - ``llm``: 생성 LLM 으로 각 후보의 관련도를 판단해 재정렬(추가 서버 불필요)
    - ``cross_encoder``: 외부 리랭크 서버(TEI ``/rerank`` 등) 호출

실패 시 입력 순서로 graceful fallback 한다(검색이 죽지 않도록).
"""

import asyncio
import json
import logging
import re
import threading

import httpx

from app.core.config import settings
from app.core.http import auth_headers
from app.retrieval.schemas import ChunkHit

logger = logging.getLogger(__name__)

# 로컬(in-process) FastEmbed cross-encoder 캐시
_LOCAL_DEFAULT_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
_local_models: dict[str, object] = {}
_local_locks: dict[str, threading.Lock] = {}
_local_registry_lock = threading.Lock()


def list_local_rerank_models() -> list[dict]:
    """FastEmbed 가 지원하는 로컬 cross-encoder(리랭커) 모델 목록(서버 불필요)."""
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
    except ImportError:
        return []
    out = [
        {"model": m["model"], "size_gb": m.get("size_in_GB")}
        for m in TextCrossEncoder.list_supported_models()
    ]
    return sorted(out, key=lambda x: x["model"])


def _load_local_reranker(name: str):
    """로컬 cross-encoder 모델을 캐시에서 가져오거나 1회 로딩(락으로 중복 방지)."""
    model = _local_models.get(name)
    if model is not None:
        return model
    with _local_registry_lock:
        lock = _local_locks.setdefault(name, threading.Lock())
    with lock:
        model = _local_models.get(name)
        if model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            logger.info("로컬 리랭커 모델 로딩(최초 1회 다운로드 가능): %s", name)
            model = TextCrossEncoder(model_name=name)
            _local_models[name] = model
    return model


def _rerank_local_sync(name: str, query: str, texts: list[str]) -> list[float]:
    model = _load_local_reranker(name)
    return [float(s) for s in model.rerank(query, texts)]


async def list_rerank_models(server_url: str | None = None) -> list[str]:
    """리랭커 서버의 ``GET /v1/models`` 로 제공 cross-encoder 모델 목록을 가져온다.

    ``server_url`` 미지정 시 설정값(``rerank.server_url``)을 쓴다(예: http://host:8081/rerank).
    호스트를 유도해 ``/v1/models`` 를 호출하므로 연결 테스트에도 재사용한다."""
    from urllib.parse import urlparse

    p = urlparse(server_url or settings.rerank_server_url)
    if not p.netloc:
        raise RuntimeError("rerank.server_url 이 올바르지 않습니다.")
    url = f"{p.scheme}://{p.netloc}/v1/models"
    headers = auth_headers(
        settings.rerank_api_key, settings.rerank_auth_header, settings.rerank_auth_scheme
    )
    async with httpx.AsyncClient(timeout=10, headers=headers) as client:
        resp = await client.get(url)
    if resp.status_code != 200:
        raise RuntimeError(f"리랭커 모델 목록 조회 실패({resp.status_code}): {resp.text[:160]} @ {url}")
    data = resp.json()
    items = data.get("data") if isinstance(data, dict) else data
    return sorted(it.get("id") for it in (items or []) if isinstance(it, dict) and it.get("id"))


def _truncate(text: str, n: int = 500) -> str:
    return text[:n]


async def _rerank_llm(query: str, hits: list[ChunkHit], top_n: int) -> list[ChunkHit]:
    """LLM 에게 후보 패시지의 관련도 순서를 매기게 한다(추가 서버 불필요)."""
    from app.llm.service import complete

    passages = "\n".join(f"[{i}] {_truncate(h.text)}" for i, h in enumerate(hits))
    prompt = (
        "다음은 사용자 질문과 후보 패시지 목록입니다. 질문에 답하는 데 가장 관련 있는 순서대로 "
        "패시지 번호를 나열하세요. JSON 배열로만 답하세요(예: [2,0,1]).\n\n"
        f"질문: {query}\n\n패시지:\n{passages}\n\n관련도 순서(JSON 배열):"
    )
    out = await complete([
        {"role": "system", "content": "당신은 검색 결과를 관련도순으로 재정렬하는 도우미입니다."},
        {"role": "user", "content": prompt},
    ])
    match = re.search(r"\[[\d,\s]*\]", out)
    if not match:
        raise RuntimeError(f"리랭크 응답 파싱 실패: {out[:120]}")
    order = json.loads(match.group(0))
    seen = set()
    ranked: list[ChunkHit] = []
    for idx in order:
        if isinstance(idx, int) and 0 <= idx < len(hits) and idx not in seen:
            seen.add(idx)
            ranked.append(hits[idx])
    # 누락된 후보는 원래 순서로 뒤에 붙인다
    for i, h in enumerate(hits):
        if i not in seen:
            ranked.append(h)
    # LLM 은 수치 점수가 없으므로 순위 기반 내림차순 점수를 부여(순서=점수 일치).
    total = len(ranked) or 1
    ranked = [h.model_copy(update={"score": round(1.0 - i / total, 6)}) for i, h in enumerate(ranked)]
    return ranked[:top_n]


async def _rerank_cross_encoder(
    query: str, hits: list[ChunkHit], top_n: int, model: str | None = None
) -> list[ChunkHit]:
    """외부 cross-encoder 리랭크 서버 호출 (TEI ``/rerank`` 형식). model 지정 시 함께 전송."""
    payload: dict = {"query": query, "texts": [h.text for h in hits]}
    if model:
        payload["model"] = model
    headers = {"Content-Type": "application/json"}
    headers.update(auth_headers(
        settings.rerank_api_key, settings.rerank_auth_header, settings.rerank_auth_scheme
    ))
    async with httpx.AsyncClient(timeout=settings.llm_timeout, headers=headers) as client:
        resp = await client.post(settings.rerank_server_url, json=payload)
    if resp.status_code != 200:
        raise RuntimeError(f"리랭크 서버 오류({resp.status_code}): {resp.text[:160]}")
    # [{"index": i, "score": s}, ...] 형식 가정 — 리랭커 점수를 score 로 노출(순서=점수 일치).
    results = sorted(resp.json(), key=lambda r: r.get("score", 0), reverse=True)
    out: list[ChunkHit] = []
    for r in results:
        idx = r.get("index", -1)
        if 0 <= idx < len(hits):
            out.append(hits[idx].model_copy(update={"score": round(float(r.get("score", 0.0)), 6)}))
    return out[:top_n]


async def _rerank_local(query: str, hits: list[ChunkHit], top_n: int, model: str | None) -> list[ChunkHit]:
    """로컬(in-process) FastEmbed cross-encoder 로 재정렬(서버 불필요)."""
    name = model or _LOCAL_DEFAULT_MODEL
    scores = await asyncio.to_thread(_rerank_local_sync, name, query, [h.text for h in hits])
    order = sorted(range(len(hits)), key=lambda i: scores[i], reverse=True)
    # 리랭커 점수를 score 로 노출(순서=점수 일치).
    return [hits[i].model_copy(update={"score": round(float(scores[i]), 6)}) for i in order][:top_n]


async def rerank(
    query: str, hits: list[ChunkHit], top_n: int | None = None, *,
    provider: str | None = None, model: str | None = None,
) -> list[ChunkHit]:
    """설정된(또는 override 된) provider 로 재정렬한다. provider=none/실패 시 입력 순서 유지.

    - ``local``: FastEmbed cross-encoder 인프로세스(서버 불필요)
    - ``cross_encoder``: 외부 리랭커 서버. model 지정 시 서버에 그 모델을 요청(비면 서버 기본)"""
    top_n = top_n or settings.rerank_top_n
    provider = (provider or settings.rerank_provider).lower()
    if provider == "none" or not hits:
        return hits[:top_n]
    try:
        if provider == "llm":
            return await _rerank_llm(query, hits, top_n)
        if provider == "local":
            return await _rerank_local(query, hits, top_n, model)
        if provider == "cross_encoder":
            return await _rerank_cross_encoder(query, hits, top_n, model)
    except Exception as e:
        logger.warning("리랭크 실패(%s) — 융합 순서로 폴백: %s", provider, e)
    return hits[:top_n]
