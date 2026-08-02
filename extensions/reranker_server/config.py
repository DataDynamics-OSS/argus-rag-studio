# SPDX-License-Identifier: Apache-2.0
"""리랭커 서버 설정 — config.yml + config.properties 로드(임베딩 서버와 동일 패턴).

설정 디렉터리: ``ARGUS_RERANKER_SERVER_CONFIG_DIR`` (기본 /etc/argus-reranker-server).
``RERANK_*`` 환경변수가 있으면 config 값보다 우선한다(빈값도 유효).
"""

import os
from pathlib import Path

from reranker_server.config_loader import load_config

_CONFIG_DIR = Path(
    os.environ.get("ARGUS_RERANKER_SERVER_CONFIG_DIR", "/etc/argus-reranker-server")
)
_raw: dict = load_config(config_dir=_CONFIG_DIR)


def _get(section: str, key: str, default):
    sec = _raw.get(section)
    if isinstance(sec, dict) and key in sec and sec[key] is not None:
        return sec[key]
    return default


def _get_nested(section: str, sub: str, key: str, default):
    sec = _raw.get(section)
    if isinstance(sec, dict):
        s = sec.get(sub)
        if isinstance(s, dict) and key in s and s[key] is not None:
            return s[key]
    return default


def _env(env_key: str, fallback: str) -> str:
    v = os.environ.get(env_key)
    return v if v is not None else fallback


def _to_int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _to_bool(v, default: bool) -> bool:
    if v is None:
        return default
    return str(v).lower() in ("1", "true", "yes", "on")


class Config:
    # 메타/로깅 (catalog/RAG 백엔드와 동일 키)
    app_name: str = _get("app", "name", "argus-reranker-server")
    log_level: str = _env("RERANK_LOG_LEVEL", str(_get("logging", "level", "INFO")))
    log_dir: Path = Path(_env("RERANK_LOG_DIR", str(_get("logging", "dir", "logs"))))
    log_filename: str = str(_get("logging", "filename", "argus-reranker-server.log"))
    log_rolling_backup_count: int = _to_int(
        _get_nested("logging", "rolling", "backup_count", 30), 30
    )

    # 바인딩 (기본 8081 — RAG rerank.server_url 과 맞춤)
    host: str = _env("RERANK_HOST", str(_get("server", "host", "0.0.0.0")))
    port: int = _to_int(_env("RERANK_PORT", str(_get("server", "port", 8081))), 8081)

    # 인증 — 빈값이면 무인증. RAG 의 rerank.api_key 와 동일해야 함
    api_key: str = _env("RERANK_API_KEY", str(_get("rerank", "api_key", "changeme")))

    # 모델
    default_model: str = _env(
        "RERANK_DEFAULT_MODEL", str(_get("rerank", "default_model", "Xenova/ms-marco-MiniLM-L-6-v2"))
    )
    allowed_models: list[str] = [
        m.strip()
        for m in _env("RERANK_MODELS", str(_get("rerank", "models", "") or "")).split(",")
        if m.strip()
    ]
    cache_dir: str | None = (
        _env("RERANK_CACHE_DIR", str(_get("rerank", "cache_dir", "") or "")) or None
    )
    preload: bool = _to_bool(_env("RERANK_PRELOAD", str(_get("rerank", "preload", False))), False)
    max_batch: int = _to_int(_env("RERANK_MAX_BATCH", str(_get("rerank", "max_batch", 256))), 256)

    # 추론 백엔드 — fastembed(ONNX, 기본) | sentence_transformers(torch, GPU 가속).
    # torch 백엔드는 aarch64 + Blackwell 처럼 onnxruntime-gpu 휠이 없는 환경의 GPU 대안.
    backend: str = _env("RERANK_BACKEND", str(_get("rerank", "backend", "fastembed")))

    # 디바이스 — cpu(기본) | cuda. cuda 는 fastembed-gpu(onnxruntime-gpu) 설치 필요(requirements-gpu.txt).
    # GPU 로딩 실패 시 자동으로 CPU 로 폴백한다.
    device: str = _env("RERANK_DEVICE", str(_get("rerank", "device", "cpu")))
    cuda_device_ids: list[int] = [
        int(x)
        for x in _env("RERANK_CUDA_DEVICE_IDS", str(_get("rerank", "cuda_device_ids", "") or ""))
        .replace(" ", "")
        .split(",")
        if x.strip().isdigit()
    ]

    config_dir: Path = _CONFIG_DIR


config = Config()
