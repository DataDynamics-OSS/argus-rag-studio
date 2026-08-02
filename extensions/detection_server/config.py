# SPDX-License-Identifier: Apache-2.0
"""검출 서버 설정 — config.yml + config.properties 로드(catalog/RAG 백엔드와 동일 패턴).

설정 디렉터리: ``ARGUS_DETECTION_SERVER_CONFIG_DIR`` (기본 /etc/argus-detection-server).
도커/운영 편의를 위해 ``DETECT_*`` 환경변수가 있으면 config 값보다 우선한다(빈값도 유효).
"""

import os
from pathlib import Path

from detection_server.config_loader import load_config

_CONFIG_DIR = Path(
    os.environ.get("ARGUS_DETECTION_SERVER_CONFIG_DIR", "/etc/argus-detection-server")
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
    """DETECT_* 환경변수가 있으면(빈값 포함) 우선, 없으면 config 값."""
    v = os.environ.get(env_key)
    return v if v is not None else fallback


def _to_int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _to_float(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _to_bool(v, default: bool) -> bool:
    if v is None:
        return default
    return str(v).lower() in ("1", "true", "yes", "on")


class Config:
    # 메타/로깅 (catalog/RAG 백엔드와 동일 키)
    app_name: str = _get("app", "name", "argus-detection-server")
    log_level: str = _env("DETECT_LOG_LEVEL", str(_get("logging", "level", "INFO")))
    log_dir: Path = Path(_env("DETECT_LOG_DIR", str(_get("logging", "dir", "logs"))))
    log_filename: str = str(_get("logging", "filename", "argus-detection-server.log"))
    log_rolling_backup_count: int = _to_int(
        _get_nested("logging", "rolling", "backup_count", 30), 30
    )

    # 바인딩 — 8080(임베딩)/8081(리랭커)과 겹치지 않게 8082 기본
    host: str = _env("DETECT_HOST", str(_get("server", "host", "0.0.0.0")))
    port: int = _to_int(_env("DETECT_PORT", str(_get("server", "port", 8082))), 8082)

    # 인증 — 빈값이면 무인증
    api_key: str = _env("DETECT_API_KEY", str(_get("detection", "api_key", "changeme")))

    # 검출 엔진 — paddleocr(CPU 기본) | easyocr(torch GPU)
    # aarch64+Blackwell 처럼 paddlepaddle-gpu 휠이 없는 환경의 GPU 가속은 easyocr 를 쓴다.
    engine: str = _env("DETECT_ENGINE", str(_get("detection", "engine", "paddleocr"))).lower()

    # 검출(PaddleOCR)
    # lang: korean | en | ch | japan | ... (PaddleOCR 언어 코드)
    default_lang: str = _env("DETECT_LANG", str(_get("detection", "lang", "korean")))
    use_gpu: bool = _to_bool(_env("DETECT_USE_GPU", str(_get("detection", "use_gpu", False))), False)
    # EasyOCR 언어(콤마목록, 예: ko,en). paddle 코드(korean 등)는 엔진이 자동 매핑.
    easyocr_langs: str = _env("DETECT_EASYOCR_LANGS", str(_get("detection", "easyocr_langs", "ko,en")))
    # 신뢰도 임계값(이 미만 박스는 응답에서 제외) — 요청에서 override 가능
    min_score: float = _to_float(
        _env("DETECT_MIN_SCORE", str(_get("detection", "min_score", 0.5))), 0.5
    )
    # 입력 이미지 최대 크기(MB)
    max_image_mb: int = _to_int(
        _env("DETECT_MAX_IMAGE_MB", str(_get("detection", "max_image_mb", 20))), 20
    )
    # 시작 시 기본 언어 모델 미리 로딩
    preload: bool = _to_bool(_env("DETECT_PRELOAD", str(_get("detection", "preload", False))), False)

    # 설정 출처(배너용)
    config_dir: Path = _CONFIG_DIR


config = Config()
