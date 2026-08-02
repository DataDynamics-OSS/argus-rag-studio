# SPDX-License-Identifier: Apache-2.0
"""Argus 리랭커 서버 — FastEmbed cross-encoder FastAPI 앱.

엔드포인트:
    - POST /rerank    : {query, texts} → [{index, score}, ...] (TEI 호환 형식)
    - GET  /v1/models : 제공 리랭커 모델 목록
    - GET  /health    : 헬스체크

RAG Studio 연결: rerank.provider=cross_encoder, rerank.server_url=http://<host>:8081/rerank
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

from reranker_server import __version__, metrics
from reranker_server.config import config
from reranker_server.logging_config import setup_logging

# 추론 백엔드 선택 — torch(sentence-transformers CrossEncoder) GPU 또는 FastEmbed(ONNX, 기본).
# 두 모듈은 동일 인터페이스(supported_model_ids/rerank/preload/models_info)를 노출한다.
if config.backend == "sentence_transformers":
    from reranker_server import engine_st as engine
else:
    from reranker_server import engine

logger = logging.getLogger("reranker_server")


def _available_models() -> list[str]:
    """노출할 리랭커 모델 ID 목록(화이트리스트 설정 시 그것만, 아니면 FastEmbed 전체)."""
    return config.allowed_models or engine.supported_model_ids()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Argus 리랭커 서버 %s 기동 (설정=%s, 로그=%s, 기본 모델=%s, 인증=%s)",
                __version__, config.config_dir, config.log_dir / config.log_filename,
                config.default_model, "on" if config.api_key else "off")
    active_device = getattr(engine, "device_str", lambda: config.device)()
    metrics.set_info(server="reranker", version=__version__, device=active_device,
                     model=config.default_model, cache_dir=config.cache_dir or "/")
    metrics.set_models_provider(engine.models_info)
    if config.preload:
        try:
            engine.preload(config.default_model)
        except Exception as e:
            logger.warning("기본 모델 프리로드 실패: %s", e)
    # 레지스트리 하트비트(ARGUS_HEARTBEAT_URL 설정 시) — LB 뒤 레플리카까지 모니터링
    from reranker_server import heartbeat
    hb_task = heartbeat.start("reranker", __version__, metrics.snapshot)
    yield
    await heartbeat.stop(hb_task)


app = FastAPI(title="Argus Reranker Server", version=__version__, lifespan=lifespan)

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


class RerankRequest(BaseModel):
    query: str = Field(..., min_length=1)
    texts: list[str] = Field(default_factory=list)
    model: str | None = None
    top_n: int | None = None


def _check_auth(authorization: str | None) -> None:
    if config.api_key and authorization != f"Bearer {config.api_key}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/v1/models")
def list_models(authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    now = int(time.time())
    return {"object": "list",
            "data": [{"id": m, "object": "model", "created": now, "owned_by": "argus"}
                     for m in _available_models()]}


@app.post("/rerank")
async def rerank(req: RerankRequest, authorization: str | None = Header(default=None)):
    """query 와 texts 의 관련도를 cross-encoder 로 채점. TEI 형식 [{index, score}] 반환(점수 내림차순)."""
    _check_auth(authorization)
    model = req.model or config.default_model
    if not req.texts:
        return []
    if len(req.texts) > config.max_batch:
        raise HTTPException(status_code=400, detail=f"입력이 너무 많습니다(최대 {config.max_batch}).")
    if model not in set(_available_models()):
        raise HTTPException(status_code=404, detail=f"제공하지 않는 모델입니다: {model}")

    try:
        scores = await engine.rerank(model, req.query, req.texts)
    except Exception as e:
        logger.warning("리랭크 실패(model=%s): %s", model, e)
        raise HTTPException(status_code=500, detail=f"리랭크 실패: {e}")

    metrics.incr("rerank_docs_total", len(req.texts))
    results = [{"index": i, "score": s} for i, s in enumerate(scores)]
    results.sort(key=lambda r: r["score"], reverse=True)
    if req.top_n:
        results = results[: req.top_n]
    return results
