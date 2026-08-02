# SPDX-License-Identifier: Apache-2.0
"""Argus 검출 서버 — PaddleOCR 텍스트 bbox 검출 FastAPI 앱.

엔드포인트:
    - POST /v1/detect : 이미지(멀티파트) → 텍스트 bbox + 인식 텍스트 + 신뢰도
    - GET  /health    : 헬스체크

RAG Studio 연결: 백엔드 config 의 detection.server_url 을 이 서버 주소로 지정하면
어노테이션 편집기의 '자동 인식'이 이 서버를 호출한다(반환 박스는 후보 — 사람이 검수).
"""

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Header, HTTPException, Response, UploadFile

from detection_server import __version__, metrics
from detection_server.config import config
from detection_server.logging_config import setup_logging

# 엔진 선택 — easyocr(torch GPU) | paddleocr(CPU 기본). 둘 다 동일 인터페이스(detect/preload).
if config.engine == "easyocr":
    from detection_server import engine_easyocr as engine
else:
    from detection_server import engine

logger = logging.getLogger("detection_server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info(
        "Argus 검출 서버 %s 기동 (엔진=%s, 설정=%s, 로그=%s, 기본 언어=%s, GPU=%s, 인증=%s)",
        __version__, config.engine, config.config_dir, config.log_dir / config.log_filename,
        config.default_lang, "on" if config.use_gpu else "off",
        "on" if config.api_key else "off",
    )
    metrics.set_info(
        server="detection", version=__version__,
        device="cuda" if config.use_gpu else "cpu",
        model=f"{config.engine}:{config.default_lang}",
        cache_dir=os.environ.get("HOME", "/"),
    )
    metrics.set_models_provider(engine.models_info)
    if config.preload:
        try:
            engine.preload(config.default_lang)
        except Exception as e:  # 프리로드 실패해도 서버는 뜬다(첫 요청 때 재시도)
            logger.warning("기본 언어 모델 프리로드 실패: %s", e)
    # 레지스트리 하트비트(ARGUS_HEARTBEAT_URL 설정 시) — LB 뒤 레플리카까지 모니터링
    from detection_server import heartbeat
    hb_task = heartbeat.start("detection", __version__, metrics.snapshot)
    yield
    await heartbeat.stop(hb_task)


app = FastAPI(title="Argus Detection Server", version=__version__, lifespan=lifespan)

_META_PATHS = {"/metrics", "/stats", "/health"}


@app.middleware("http")
async def _metrics_mw(request, call_next):
    if request.url.path in _META_PATHS:
        return await call_next(request)
    metrics.req_start()
    t0 = time.perf_counter()
    status = 500
    err = False
    try:
        resp = await call_next(request)
        status = resp.status_code
        return resp
    except Exception:
        err = True
        raise
    finally:
        metrics.req_end(status, time.perf_counter() - t0, err)


@app.get("/stats")
def stats():
    """런타임 메트릭 JSON(시스템·GPU·요청·모델) — 원격 모니터링/대시보드용."""
    return metrics.snapshot()


@app.get("/metrics")
def prometheus_metrics():
    """Prometheus 텍스트 메트릭."""
    return Response(metrics.prometheus(), media_type="text/plain; version=0.0.4; charset=utf-8")


def _check_auth(authorization: str | None) -> None:
    if config.api_key and authorization != f"Bearer {config.api_key}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@app.post("/v1/detect")
async def detect(
    file: UploadFile = File(...),
    lang: str = Form(default=""),
    min_score: float = Form(default=-1.0),
    with_text: bool = Form(default=True),
    authorization: str | None = Header(default=None),
):
    """이미지에서 텍스트 bbox 를 검출한다.

    응답: ``{"boxes": [{x1,y1,x2,y2,text,score}], "width": W, "height": H}``.
    좌표는 원본 이미지 픽셀 기준(축정렬). ``with_text=false`` 면 검출만(텍스트 빈 문자열)."""
    _check_auth(authorization)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    if len(data) > config.max_image_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"이미지가 너무 큽니다(최대 {config.max_image_mb}MB).")

    use_lang = lang or config.default_lang
    score = min_score if min_score >= 0 else config.min_score
    try:
        result = await engine.detect(use_lang, data, score, with_text)
    except Exception as e:
        logger.warning("검출 실패(lang=%s): %s", use_lang, e)
        raise HTTPException(status_code=500, detail=f"검출 실패: {e}")

    metrics.incr("detect_images_total", 1)
    metrics.incr("detect_boxes_total", len(result["boxes"]))
    logger.info("검출 완료: lang=%s boxes=%d", use_lang, len(result["boxes"]))
    return result
