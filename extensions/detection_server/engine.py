# SPDX-License-Identifier: Apache-2.0
"""검출 엔진 — PaddleOCR 모델 캐시 + 비동기 텍스트 bbox 검출.

모델은 (언어)별로 메모리에 캐시한다(최초 1회 로딩, 락으로 동시 로딩 1회만). PaddleOCR 의
추론은 동기·CPU(또는 GPU) 작업이라 ``asyncio.to_thread`` 로 이벤트 루프를 막지 않는다.

반환 박스는 축정렬(AABB) 사각형 ``(x1,y1,x2,y2)`` + 인식 텍스트 + 신뢰도(score)다.
PaddleOCR 의 검출 결과는 사각형이 회전했을 수 있어 4점 다각형을 min/max 로 정규화한다."""

import asyncio
import io
import logging
import threading

logger = logging.getLogger("detection_server.engine")

_models: dict[str, object] = {}
_locks: dict[str, threading.Lock] = {}
_registry_lock = threading.Lock()


def _lock_for(lang: str) -> threading.Lock:
    with _registry_lock:
        return _locks.setdefault(lang, threading.Lock())


def _build(lang: str, use_gpu: bool):
    """버전(2.x/3.x)에 맞는 생성자 인자를 차례로 시도해 PaddleOCR 인스턴스를 만든다."""
    from paddleocr import PaddleOCR

    # 3.x: 불필요한 문서 방향/워핑/텍스트라인 회전 모듈을 꺼 속도·모델 다운로드를 줄인다.
    v3 = {
        "lang": lang,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }
    if use_gpu:
        v3["device"] = "gpu"
    # 2.x: 각도 분류기 + 내부 로그 억제
    v2 = {"lang": lang, "use_angle_cls": True, "show_log": False}
    if use_gpu:
        v2["use_gpu"] = True

    last: Exception | None = None
    for kwargs in (v3, v2, {"lang": lang}):
        try:
            return PaddleOCR(**kwargs)
        except (TypeError, ValueError) as e:
            last = e
    raise last or RuntimeError("PaddleOCR 초기화 실패")


def _load(lang: str):
    """PaddleOCR 모델을 캐시에서 가져오거나 로딩한다(double-checked locking)."""
    model = _models.get(lang)
    if model is not None:
        return model
    with _lock_for(lang):
        model = _models.get(lang)
        if model is None:
            from detection_server.config import config

            logger.info("PaddleOCR 모델 로딩(최초 1회 다운로드 가능): lang=%s", lang)
            model = _build(lang, config.use_gpu)
            _models[lang] = model
            logger.info("PaddleOCR 준비 완료: lang=%s", lang)
    return model


def _quad_to_aabb(quad) -> tuple[int, int, int, int]:
    xs = [float(p[0]) for p in quad]
    ys = [float(p[1]) for p in quad]
    return round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))


def _parse_classic(raw) -> list[dict]:
    """PaddleOCR 2.x ``.ocr()`` 결과 파싱.

    형식: ``[[ [quad(4점), (text, score)], ... ]]`` (이미지 1장 → 바깥 리스트 길이 1).
    det 전용(rec=False)이면 ``[[ quad, ... ]]`` 형태일 수 있다."""
    out: list[dict] = []
    for page in raw or []:
        for line in page or []:
            if (
                isinstance(line, (list, tuple))
                and len(line) == 2
                and isinstance(line[1], (list, tuple))
            ):
                quad, rec = line[0], line[1]
                text, score = str(rec[0]), float(rec[1])
            else:  # det 전용 — 좌표만
                quad, text, score = line, "", 1.0
            x1, y1, x2, y2 = _quad_to_aabb(quad)
            out.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "text": text, "score": score})
    return out


def _parse_predict(raw) -> list[dict]:
    """PaddleOCR 3.x ``.predict()`` 결과 파싱.

    각 결과는 ``rec_polys``|``dt_polys`` + ``rec_texts`` + ``rec_scores`` 키를 갖는
    dict 또는 dict 류(Result) 객체다. ``res.json`` 에 ``{"res": {...}}`` 로 감싸일 수도 있다."""
    out: list[dict] = []
    for res in raw or []:
        data = res
        j = getattr(res, "json", None)
        if isinstance(j, dict):
            data = j
        if isinstance(data, dict) and isinstance(data.get("res"), dict):
            data = data["res"]

        def _get(key):
            try:
                return data[key]
            except (KeyError, TypeError):
                return None

        polys = _get("rec_polys")
        if polys is None:
            polys = _get("dt_polys")
        texts = _get("rec_texts") or []
        scores = _get("rec_scores") or []
        for i, quad in enumerate(polys or []):
            x1, y1, x2, y2 = _quad_to_aabb(quad)
            text = str(texts[i]) if i < len(texts) else ""
            score = float(scores[i]) if i < len(scores) else 1.0
            out.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "text": text, "score": score})
    return out


def _detect_sync(lang: str, image: bytes, min_score: float, with_text: bool) -> dict:
    import numpy as np
    from PIL import Image

    img = Image.open(io.BytesIO(image)).convert("RGB")
    width, height = img.size
    arr = np.array(img)
    model = _load(lang)

    boxes: list[dict] = []
    used = False
    # 3.x — predict() 우선(현재 PaddleOCR 권장 API)
    if hasattr(model, "predict"):
        try:
            boxes = _parse_predict(model.predict(arr))
            used = True
        except Exception as e:  # noqa: BLE001 — 2.x .ocr 로 폴백
            logger.debug("predict() 실패, ocr() 폴백: %s", e)
    # 2.x — .ocr() (또는 3.x 가 predict 미제공일 때)
    if not used and hasattr(model, "ocr"):
        try:
            raw = model.ocr(arr, cls=True, rec=with_text)
        except TypeError:
            raw = model.ocr(arr)
        boxes = _parse_classic(raw)

    boxes = [b for b in boxes if b["score"] >= min_score and b["x2"] > b["x1"] and b["y2"] > b["y1"]]
    # 읽기 순서(위→아래, 좌→우) 정렬
    boxes.sort(key=lambda b: (b["y1"], b["x1"]))
    return {"boxes": boxes, "width": width, "height": height}


async def detect(lang: str, image: bytes, min_score: float, with_text: bool = True) -> dict:
    return await asyncio.to_thread(_detect_sync, lang, image, min_score, with_text)


def preload(lang: str) -> None:
    _load(lang)


def models_info() -> dict:
    """현재 로딩된 검출 모델(언어별) 요약(메트릭/모니터링용)."""
    return {"count": len(_models), "loaded": sorted(_models.keys()), "warmup_ready": len(_models) > 0}
