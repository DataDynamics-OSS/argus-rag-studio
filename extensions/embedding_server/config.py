# SPDX-License-Identifier: Apache-2.0
"""임베딩 서버 설정 — config.yml + config.properties 로드(catalog/RAG 백엔드와 동일 패턴).

설정 디렉터리: ``ARGUS_EMBEDDING_SERVER_CONFIG_DIR`` (기본 /etc/argus-embedding-server).
도커/운영 편의를 위해 ``EMBED_*`` 환경변수가 있으면 config 값보다 우선한다(빈값도 유효).
"""

import os
from pathlib import Path

from embedding_server.config_loader import load_config

_CONFIG_DIR = Path(
    os.environ.get("ARGUS_EMBEDDING_SERVER_CONFIG_DIR", "/etc/argus-embedding-server")
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
    """EMBED_* 환경변수가 있으면(빈값 포함) 우선, 없으면 config 값."""
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
    app_name: str = _get("app", "name", "argus-embedding-server")
    log_level: str = _env("EMBED_LOG_LEVEL", str(_get("logging", "level", "INFO")))
    log_dir: Path = Path(_env("EMBED_LOG_DIR", str(_get("logging", "dir", "logs"))))
    log_filename: str = str(_get("logging", "filename", "argus-embedding-server.log"))
    log_rolling_backup_count: int = _to_int(
        _get_nested("logging", "rolling", "backup_count", 30), 30
    )

    # 바인딩
    host: str = _env("EMBED_HOST", str(_get("server", "host", "0.0.0.0")))
    port: int = _to_int(_env("EMBED_PORT", str(_get("server", "port", 8080))), 8080)

    # 인증 — 빈값이면 무인증
    api_key: str = _env("EMBED_API_KEY", str(_get("embedding", "api_key", "changeme")))

    # 모델
    default_model: str = _env(
        "EMBED_DEFAULT_MODEL", str(_get("embedding", "default_model", "mixedbread-ai/mxbai-embed-large-v1"))
    )
    allowed_models: list[str] = [
        m.strip()
        for m in _env("EMBED_MODELS", str(_get("embedding", "models", "") or "")).split(",")
        if m.strip()
    ]
    dim_filter: int | None = (
        _to_int(_env("EMBED_DIM", str(_get("embedding", "dim", 1024))), 0) or None
    )
    cache_dir: str | None = (
        _env("EMBED_CACHE_DIR", str(_get("embedding", "cache_dir", "") or "")) or None
    )
    preload: bool = _to_bool(_env("EMBED_PRELOAD", str(_get("embedding", "preload", False))), False)
    max_batch: int = _to_int(_env("EMBED_MAX_BATCH", str(_get("embedding", "max_batch", 256))), 256)

    # 추론 백엔드 — fastembed(ONNX, 기본) | sentence_transformers(torch, GPU 가속).
    # torch 백엔드는 aarch64 + Blackwell 처럼 onnxruntime-gpu 휠이 없는 환경의 GPU 대안.
    backend: str = _env("EMBED_BACKEND", str(_get("embedding", "backend", "fastembed")))

    # 디바이스 — cpu(기본) | cuda. cuda 는 fastembed-gpu(onnxruntime-gpu) 설치 필요(requirements-gpu.txt).
    # 대량 임베딩은 GPU 권장. GPU 로딩 실패 시 자동으로 CPU 로 폴백한다.
    device: str = _env("EMBED_DEVICE", str(_get("embedding", "device", "cpu")))
    # 사용할 GPU 인덱스(여러 개면 콤마, 예 "0,1"). 비우면 기본 GPU.
    cuda_device_ids: list[int] = [
        int(x)
        for x in _env("EMBED_CUDA_DEVICE_IDS", str(_get("embedding", "cuda_device_ids", "") or ""))
        .replace(" ", "")
        .split(",")
        if x.strip().isdigit()
    ]

    # 설정 출처(배너용)
    config_dir: Path = _CONFIG_DIR


config = Config()
