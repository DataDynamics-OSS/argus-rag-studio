# SPDX-License-Identifier: Apache-2.0
"""리랭킹 엔진 (sentence-transformers CrossEncoder / torch) — GPU(CUDA) 가속용 대체 백엔드.

FastEmbed(ONNX) 백엔드(``engine.py``)와 동일한 인터페이스를 제공하되, torch +
sentence-transformers ``CrossEncoder`` 로 (query, document) 쌍을 채점한다. torch cu128 휠은
CUDA 런타임을 포함해 aarch64 + Blackwell(sm_120/sm_121)에서도 GPU 로 동작한다(onnxruntime-gpu
는 aarch64 휠이 없어 FastEmbed GPU 가 불가능한 환경의 대안).

``RERANK_BACKEND=sentence_transformers`` 일 때 main 이 이 모듈을 ``engine`` 으로 임포트한다.
"""

import asyncio
import logging
import threading

logger = logging.getLogger("reranker_server.engine_st")

_models: dict[str, object] = {}
_locks: dict[str, threading.Lock] = {}
_registry_lock = threading.Lock()
_device: str | None = None

# 노출/검증용 큐레이션 목록. RERANK_MODELS 화이트리스트가 있으면 그쪽이 우선한다.
# ST CrossEncoder 는 HF 모델을 동적으로 로드하므로 자주 쓰는 모델만 보여준다.
_CURATED = [
    "cross-encoder/ms-marco-MiniLM-L-6-v2",          # 경량(영어 중심)
    "BAAI/bge-reranker-v2-m3",                        # 다국어(한국어 포함, 무거움)
    "jinaai/jina-reranker-v2-base-multilingual",      # 다국어
]


def device_str() -> str:
    """실제 사용 디바이스('cuda' | 'cpu'). config.device=cuda 라도 GPU 가 없으면 cpu."""
    global _device
    if _device is None:
        try:
            import torch

            from reranker_server.config import config

            want_cuda = str(config.device).lower() == "cuda"
            _device = "cuda" if (want_cuda and torch.cuda.is_available()) else "cpu"
            if want_cuda and _device == "cpu":
                logger.warning("RERANK_DEVICE=cuda 이지만 torch 가 GPU 를 못 봄 → CPU 로 동작")
        except Exception as e:  # noqa: BLE001 — torch 미설치 등
            logger.warning("디바이스 판별 실패 → cpu: %s", e)
            _device = "cpu"
    return _device


def supported_model_ids() -> list[str]:
    """노출 리랭커 모델 ID(큐레이션)."""
    return sorted(_CURATED)


def _lock_for(name: str) -> threading.Lock:
    with _registry_lock:
        return _locks.setdefault(name, threading.Lock())


def _build_model(name: str):
    from sentence_transformers import CrossEncoder

    from reranker_server.config import config

    dev = device_str()
    logger.info("ST CrossEncoder 로딩(최초 1회 다운로드 가능): %s [device=%s]", name, dev)
    return CrossEncoder(name, device=dev, cache_folder=config.cache_dir)


def _load(name: str):
    """모델을 캐시에서 가져오거나 로딩한다(double-checked locking)."""
    model = _models.get(name)
    if model is not None:
        return model
    with _lock_for(name):
        model = _models.get(name)
        if model is None:
            model = _build_model(name)
            _models[name] = model
            logger.info("리랭커 모델 준비 완료: %s", name)
    return model


def _rerank_sync(name: str, query: str, documents: list[str]) -> list[float]:
    model = _load(name)
    # CrossEncoder.predict 는 (query, doc) 쌍의 관련도 점수를 documents 순서대로 반환한다.
    scores = model.predict([[query, d] for d in documents])
    return [float(s) for s in scores]


async def rerank(name: str, query: str, documents: list[str]) -> list[float]:
    """query 와 각 document 의 관련도 점수 리스트(documents 순서대로)."""
    if not documents:
        return []
    return await asyncio.to_thread(_rerank_sync, name, query, documents)


def preload(name: str) -> None:
    """모델 로딩 + 더미 1회 추론(워밋업) — 첫 실제 요청 지연 제거."""
    _load(name)
    try:
        _rerank_sync(name, "warmup", ["warmup passage"])
        logger.info("리랭커 워밋업 완료: %s [device=%s]", name, device_str())
    except Exception as e:  # noqa: BLE001
        logger.warning("리랭커 워밋업 실패(무시): %s", e)


def models_info() -> dict:
    """현재 메모리에 로딩된 리랭커 모델 요약(메트릭/모니터링용)."""
    return {"count": len(_models), "loaded": sorted(_models.keys()), "warmup_ready": len(_models) > 0}
