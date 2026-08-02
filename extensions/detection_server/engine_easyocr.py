# SPDX-License-Identifier: Apache-2.0
"""검출 엔진(GPU) — EasyOCR(torch) 기반 텍스트 bbox 검출.

PaddlePaddle GPU 휠이 없는 환경(예: aarch64 + Blackwell GB10/sm_121)에서 GPU 가속을
얻기 위한 엔진. torch 가 해당 GPU의 CUDA 커널을 지원하므로 EasyOCR 로 GPU 추론한다.

``engine.py``(PaddleOCR)와 동일한 인터페이스(``detect``/``preload``)를 제공해
``main.py`` 가 설정(``DETECT_ENGINE``)에 따라 둘 중 하나를 선택한다. 반환 형식도 동일:
축정렬(AABB) ``(x1,y1,x2,y2)`` + 인식 텍스트 + 신뢰도(score)."""

import asyncio
import io
import logging
import threading

logger = logging.getLogger("detection_server.engine_easyocr")

# Reader 는 (언어튜플)별로 메모리에 캐시(최초 1회 로딩, 락으로 동시 로딩 1회만)
_readers: dict[tuple[str, ...], object] = {}
_locks: dict[tuple[str, ...], threading.Lock] = {}
_registry_lock = threading.Lock()

# PaddleOCR 언어 코드 → EasyOCR 언어 리스트 매핑(요청은 paddle 코드로 들어올 수 있음)
_LANG_MAP = {
    "korean": ["ko", "en"],
    "ko": ["ko", "en"],
    "en": ["en"],
    "english": ["en"],
    "japan": ["ja", "en"],
    "ja": ["ja", "en"],
    "ch": ["ch_sim", "en"],
    "chinese": ["ch_sim", "en"],
}


def _resolve_langs(lang: str | None) -> tuple[str, ...]:
    """요청 lang 을 EasyOCR 언어 리스트로 정규화한다."""
    from detection_server.config import config

    if lang:
        key = lang.strip().lower()
        if key in _LANG_MAP:
            return tuple(_LANG_MAP[key])
        if "," in key:  # 이미 EasyOCR 코드 콤마목록("ko,en")으로 준 경우
            return tuple(x.strip() for x in key.split(",") if x.strip())
    cfg = [x.strip() for x in config.easyocr_langs.split(",") if x.strip()]
    return tuple(cfg or ["en"])


def _lock_for(key: tuple[str, ...]) -> threading.Lock:
    with _registry_lock:
        return _locks.setdefault(key, threading.Lock())


def _load(langs: tuple[str, ...]):
    """EasyOCR Reader 를 캐시에서 가져오거나 로딩한다(double-checked locking)."""
    reader = _readers.get(langs)
    if reader is not None:
        return reader
    with _lock_for(langs):
        reader = _readers.get(langs)
        if reader is None:
            import easyocr

            from detection_server.config import config

            logger.info("EasyOCR Reader 로딩(최초 1회 모델 다운로드 가능): langs=%s gpu=%s",
                        langs, config.use_gpu)
            reader = easyocr.Reader(list(langs), gpu=config.use_gpu)
            _readers[langs] = reader
            logger.info("EasyOCR Reader 준비 완료: langs=%s", langs)
    return reader


def _quad_to_aabb(quad) -> tuple[int, int, int, int]:
    xs = [float(p[0]) for p in quad]
    ys = [float(p[1]) for p in quad]
    return round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))


def _detect_sync(lang: str, image: bytes, min_score: float, with_text: bool) -> dict:
    import numpy as np
    from PIL import Image

    img = Image.open(io.BytesIO(image)).convert("RGB")
    width, height = img.size
    arr = np.array(img)
    reader = _load(_resolve_langs(lang))

    boxes: list[dict] = []
    if with_text:
        # readtext: [(quad 4점, text, conf), ...]
        for quad, text, conf in reader.readtext(arr):
            x1, y1, x2, y2 = _quad_to_aabb(quad)
            boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2,
                          "text": str(text), "score": float(conf)})
    else:
        # detect: (horizontal_list, free_list). horizontal_list[0] = [[xmin,xmax,ymin,ymax], ...]
        horizontal, _free = reader.detect(arr)
        for xmin, xmax, ymin, ymax in (horizontal[0] if horizontal else []):
            boxes.append({"x1": round(float(xmin)), "y1": round(float(ymin)),
                          "x2": round(float(xmax)), "y2": round(float(ymax)),
                          "text": "", "score": 1.0})

    boxes = [b for b in boxes if b["score"] >= min_score and b["x2"] > b["x1"] and b["y2"] > b["y1"]]
    boxes.sort(key=lambda b: (b["y1"], b["x1"]))  # 읽기 순서(위→아래, 좌→우)
    return {"boxes": boxes, "width": width, "height": height}


async def detect(lang: str, image: bytes, min_score: float, with_text: bool = True) -> dict:
    return await asyncio.to_thread(_detect_sync, lang, image, min_score, with_text)


def preload(lang: str) -> None:
    _load(_resolve_langs(lang))


def models_info() -> dict:
    """현재 로딩된 EasyOCR Reader(언어셋별) 요약(메트릭/모니터링용)."""
    return {
        "count": len(_readers),
        "loaded": ["+".join(k) for k in _readers],
        "warmup_ready": len(_readers) > 0,
    }
