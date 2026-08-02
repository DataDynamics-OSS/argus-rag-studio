# SPDX-License-Identifier: Apache-2.0
"""리랭킹 엔진 — FastEmbed cross-encoder 모델 캐시 + 비동기 점수 계산.

cross-encoder 는 (query, document) 쌍을 함께 입력받아 관련도 점수를 낸다(bi-encoder 임베딩과
다른 구조). 모델은 이름별로 메모리 캐시하며(락으로 동시 로딩 1회), 동기·CPU 작업이라
``asyncio.to_thread`` 로 이벤트 루프를 막지 않는다.
"""

import asyncio
import logging
import threading

logger = logging.getLogger("reranker_server.engine")

_models: dict[str, object] = {}
_locks: dict[str, threading.Lock] = {}
_registry_lock = threading.Lock()


def supported_model_ids() -> list[str]:
    """FastEmbed 가 지원하는 cross-encoder(리랭커) 모델 ID."""
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return sorted({m["model"] for m in TextCrossEncoder.list_supported_models()})


def _lock_for(name: str) -> threading.Lock:
    with _registry_lock:
        return _locks.setdefault(name, threading.Lock())


def _build_model(name: str):
    """모델 객체 생성. device=cuda 면 GPU(CUDA EP)로 시도하고 실패 시 CPU 로 폴백한다.

    fastembed 버전에 따라 GPU 인자(``cuda``/``device_ids`` 또는 ``providers``)가 달라 순차 시도.
    GPU 사용은 ``fastembed-gpu``(onnxruntime-gpu) 설치가 전제다.
    """
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    from reranker_server.config import config

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
                logger.info("GPU(CUDA) 리랭커 로딩 시도: %s (%s)", name, list(extra))
                return TextCrossEncoder(**base, **extra)
            except TypeError as e:
                logger.warning("이 fastembed 버전이 %s 인자를 지원하지 않음 → 다음 방식: %s", list(extra), e)
            except Exception as e:  # noqa: BLE001
                logger.warning("GPU 로딩 실패(%s) → 다음 방식: %s", list(extra), e)
        logger.warning("GPU 로딩 불가 — CPU 로 폴백(fastembed-gpu/onnxruntime-gpu·드라이버 확인).")
    return TextCrossEncoder(**base)


def _load(name: str):
    model = _models.get(name)
    if model is not None:
        return model
    with _lock_for(name):
        model = _models.get(name)
        if model is None:
            from reranker_server.config import config

            logger.info("리랭커 모델 로딩(최초 1회 다운로드 가능): %s [device=%s]", name, config.device)
            model = _build_model(name)
            _models[name] = model
            logger.info("리랭커 모델 준비 완료: %s", name)
    return model


def _rerank_sync(name: str, query: str, documents: list[str]) -> list[float]:
    model = _load(name)
    return [float(s) for s in model.rerank(query, documents)]


async def rerank(name: str, query: str, documents: list[str]) -> list[float]:
    """query 와 각 document 의 관련도 점수 리스트(documents 순서대로)."""
    if not documents:
        return []
    return await asyncio.to_thread(_rerank_sync, name, query, documents)


def preload(name: str) -> None:
    """모델 로딩 + 더미 1회 추론(워밋업) — 첫 실제 요청의 지연을 없앤다."""
    _load(name)
    try:
        _rerank_sync(name, "warmup", ["warmup passage"])
        logger.info("리랭커 워밋업 완료: %s", name)
    except Exception as e:  # noqa: BLE001
        logger.warning("리랭커 워밋업 실패(무시): %s", e)


def models_info() -> dict:
    """현재 메모리에 로딩된 리랭커 모델 요약(메트릭/모니터링용)."""
    return {"count": len(_models), "loaded": sorted(_models.keys()), "warmup_ready": len(_models) > 0}
