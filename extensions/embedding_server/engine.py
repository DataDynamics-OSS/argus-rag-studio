# SPDX-License-Identifier: Apache-2.0
"""임베딩 엔진 — FastEmbed 모델 캐시 + 비동기 임베딩.

모델은 (이름)별로 메모리에 캐시한다(최초 1회 로딩, 락으로 동시 로딩 1회만). FastEmbed 의
``embed`` 는 동기·CPU 작업이라 ``asyncio.to_thread`` 로 이벤트 루프를 막지 않는다."""

import asyncio
import logging
import threading

logger = logging.getLogger("embedding_server.engine")

_models: dict[str, object] = {}
_locks: dict[str, threading.Lock] = {}
_registry_lock = threading.Lock()


def supported_model_ids(dim: int | None = None) -> list[str]:
    """FastEmbed 지원 임베딩 모델 ID(선택적으로 차원으로 필터)."""
    from fastembed import TextEmbedding

    return sorted(
        m["model"]
        for m in TextEmbedding.list_supported_models()
        if dim is None or m.get("dim") == dim
    )


def supported_models_meta() -> list[dict]:
    """모델 ID + 차원 + 용량(설명 패널/검증용)."""
    from fastembed import TextEmbedding

    out = []
    for m in TextEmbedding.list_supported_models():
        out.append({"model": m["model"], "dim": m.get("dim"), "size_gb": m.get("size_in_GB")})
    return sorted(out, key=lambda x: x["model"])


def _lock_for(name: str) -> threading.Lock:
    with _registry_lock:
        return _locks.setdefault(name, threading.Lock())


def _build_model(name: str):
    """모델 객체를 만든다. device=cuda 면 GPU(CUDA EP)로 시도하고, 실패 시 CPU 로 폴백한다.

    fastembed 버전에 따라 GPU 인자(``cuda``/``device_ids`` 또는 ``providers``)가 다르므로
    순차로 시도한다. GPU 사용은 ``fastembed-gpu``(onnxruntime-gpu) 설치가 전제다.
    """
    from fastembed import TextEmbedding

    from embedding_server.config import config

    base = {"model_name": name, "cache_dir": config.cache_dir}
    if (config.device or "cpu").lower() == "cuda":
        attempts: list[dict] = []
        cuda_kw: dict = {"cuda": True}
        if config.cuda_device_ids:
            cuda_kw["device_ids"] = config.cuda_device_ids
        attempts.append(cuda_kw)
        attempts.append({"providers": ["CUDAExecutionProvider", "CPUExecutionProvider"]})
        for extra in attempts:
            try:
                logger.info("GPU(CUDA) 모델 로딩 시도: %s (%s)", name, list(extra))
                return TextEmbedding(**base, **extra)
            except TypeError as e:
                logger.warning("이 fastembed 버전이 %s 인자를 지원하지 않음 → 다음 방식: %s", list(extra), e)
            except Exception as e:  # noqa: BLE001 — onnxruntime-gpu 미설치/CUDA 오류 등
                logger.warning("GPU 로딩 실패(%s) → 다음 방식: %s", list(extra), e)
        logger.warning("GPU 로딩 불가 — CPU 로 폴백(fastembed-gpu/onnxruntime-gpu·드라이버 확인).")
    return TextEmbedding(**base)


def _load(name: str):
    """모델을 캐시에서 가져오거나 로딩한다(double-checked locking)."""
    model = _models.get(name)
    if model is not None:
        return model
    with _lock_for(name):
        model = _models.get(name)
        if model is None:
            from embedding_server.config import config

            logger.info("모델 로딩(최초 1회 다운로드 가능): %s [device=%s]", name, config.device)
            model = _build_model(name)
            _models[name] = model
            logger.info("모델 준비 완료: %s", name)
    return model


def _embed_sync(name: str, texts: list[str]) -> list[list[float]]:
    model = _load(name)
    return [v.tolist() for v in model.embed(list(texts))]


async def embed(name: str, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return await asyncio.to_thread(_embed_sync, name, texts)


def preload(name: str) -> None:
    """모델 로딩 + 더미 1회 추론(워밋업) — 첫 실제 요청의 지연을 없앤다."""
    _load(name)
    try:
        _embed_sync(name, ["warmup"])
        logger.info("워밋업 완료: %s", name)
    except Exception as e:  # noqa: BLE001
        logger.warning("워밋업 추론 실패(무시): %s", e)


def models_info() -> dict:
    """현재 메모리에 로딩된 모델 요약(메트릭/모니터링용)."""
    return {"count": len(_models), "loaded": sorted(_models.keys()), "warmup_ready": len(_models) > 0}
