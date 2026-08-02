# SPDX-License-Identifier: Apache-2.0
"""임베딩 엔진 (sentence-transformers / torch) — GPU(CUDA) 가속용 대체 백엔드.

FastEmbed(ONNX) 백엔드(``engine.py``)와 동일한 인터페이스를 제공하되, torch +
sentence-transformers 로 추론한다. torch cu128 휠은 CUDA 런타임을 포함해
aarch64 + Blackwell(sm_120/sm_121)에서도 GPU 로 동작한다(onnxruntime-gpu 는 aarch64
휠이 없어 FastEmbed GPU 가 불가능한 환경의 대안).

``EMBED_BACKEND=sentence_transformers`` 일 때 main 이 이 모듈을 ``engine`` 으로 임포트한다.
"""

import asyncio
import logging
import threading

logger = logging.getLogger("embedding_server.engine_st")

_models: dict[str, object] = {}
_locks: dict[str, threading.Lock] = {}
_registry_lock = threading.Lock()
_device: str | None = None

# 노출/검증용 큐레이션 목록(1024차원). EMBED_MODELS 화이트리스트가 있으면 그쪽이 우선한다.
# ST 백엔드는 HF 모델을 동적으로 로드하므로 전체 열거 대신 자주 쓰는 모델만 보여준다.
_CURATED = [
    "mixedbread-ai/mxbai-embed-large-v1",
    "intfloat/multilingual-e5-large",
    "BAAI/bge-m3",
    "BAAI/bge-large-en-v1.5",
]


def device_str() -> str:
    """실제 사용 디바이스('cuda' | 'cpu'). config.device=cuda 라도 GPU 가 없으면 cpu."""
    global _device
    if _device is None:
        try:
            import torch

            from embedding_server.config import config

            want_cuda = str(config.device).lower() == "cuda"
            _device = "cuda" if (want_cuda and torch.cuda.is_available()) else "cpu"
            if want_cuda and _device == "cpu":
                logger.warning("EMBED_DEVICE=cuda 이지만 torch 가 GPU 를 못 봄 → CPU 로 동작")
        except Exception as e:  # noqa: BLE001 — torch 미설치 등
            logger.warning("디바이스 판별 실패 → cpu: %s", e)
            _device = "cpu"
    return _device


def supported_model_ids(dim: int | None = None) -> list[str]:
    """노출 모델 ID(큐레이션). dim 인자는 인터페이스 호환용(정보성)."""
    return sorted(_CURATED)


def _lock_for(name: str) -> threading.Lock:
    with _registry_lock:
        return _locks.setdefault(name, threading.Lock())


def _build_model(name: str):
    from sentence_transformers import SentenceTransformer

    from embedding_server.config import config

    dev = device_str()
    logger.info("ST 모델 로딩(최초 1회 다운로드 가능): %s [device=%s]", name, dev)
    return SentenceTransformer(name, device=dev, cache_folder=config.cache_dir)


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
            logger.info("모델 준비 완료: %s", name)
    return model


def _embed_sync(name: str, texts: list[str]) -> list[list[float]]:
    from embedding_server.config import config

    model = _load(name)
    # normalize_embeddings=True → 코사인용 단위 벡터(FastEmbed 출력과 동일하게 맞춤).
    vecs = model.encode(
        list(texts),
        batch_size=max(1, min(len(texts), config.max_batch)),
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return [v.tolist() for v in vecs]


async def embed(name: str, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return await asyncio.to_thread(_embed_sync, name, texts)


def preload(name: str) -> None:
    """모델 로딩 + 더미 1회 추론(워밋업) — 첫 실제 요청 지연 제거."""
    _load(name)
    try:
        _embed_sync(name, ["warmup"])
        logger.info("워밋업 완료: %s [device=%s]", name, device_str())
    except Exception as e:  # noqa: BLE001
        logger.warning("워밋업 추론 실패(무시): %s", e)


def models_info() -> dict:
    """현재 메모리에 로딩된 모델 요약(메트릭/모니터링용)."""
    return {"count": len(_models), "loaded": sorted(_models.keys()), "warmup_ready": len(_models) > 0}
