# SPDX-License-Identifier: Apache-2.0
"""Argus 임베딩 서버 — OpenAI 호환 FastAPI 앱.

엔드포인트:
    - POST /v1/embeddings : OpenAI 호환 임베딩 (RAG 의 OpenAICompatibleProvider 가 사용)
    - GET  /v1/models     : 제공 모델 목록 (RAG 의 '모델 불러오기')
    - GET  /health        : 헬스체크

RAG Studio 연결: 컬렉션 생성 시 프로바이더=OpenAI 호환, 서버 URL=http://<host>:<port>/v1
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel

from embedding_server import __version__, metrics
from embedding_server.config import config
from embedding_server.logging_config import setup_logging

# 추론 백엔드 선택 — torch(sentence-transformers) GPU 또는 FastEmbed(ONNX, 기본).
# 두 모듈은 동일 인터페이스(supported_model_ids/embed/preload/models_info)를 노출한다.
if config.backend == "sentence_transformers":
    from embedding_server import engine_st as engine
else:
    from embedding_server import engine

logger = logging.getLogger("embedding_server")


def _available_models() -> list[str]:
    """노출할 모델 ID 목록.

    우선순위: EMBED_MODELS 화이트리스트 > EMBED_DIM 차원필터(기본 1024) > FastEmbed 전체.
    """
    if config.allowed_models:
        return config.allowed_models
    return engine.supported_model_ids(config.dim_filter)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Argus 임베딩 서버 %s 기동 (설정=%s, 로그=%s, 기본 모델=%s, 인증=%s)",
                __version__, config.config_dir, config.log_dir / config.log_filename,
                config.default_model, "on" if config.api_key else "off")
    active_device = getattr(engine, "device_str", lambda: config.device)()
    metrics.set_info(server="embedding", version=__version__, device=active_device,
                     model=config.default_model, cache_dir=config.cache_dir or "/")
    metrics.set_models_provider(engine.models_info)
    if config.preload:
        try:
            engine.preload(config.default_model)
        except Exception as e:  # 프리로드 실패해도 서버는 뜬다(첫 요청 때 재시도)
            logger.warning("기본 모델 프리로드 실패: %s", e)
    # 레지스트리 하트비트(ARGUS_HEARTBEAT_URL 설정 시) — LB 뒤 레플리카까지 모니터링
    from embedding_server import heartbeat
    hb_task = heartbeat.start("embedding", __version__, metrics.snapshot)
    yield
    await heartbeat.stop(hb_task)


app = FastAPI(title="Argus Embedding Server", version=__version__, lifespan=lifespan)

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


class EmbeddingsRequest(BaseModel):
    input: str | list[str]
    model: str | None = None
    encoding_format: str | None = "float"


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
    data = [{"id": m, "object": "model", "created": now, "owned_by": "argus"}
            for m in _available_models()]
    return {"object": "list", "data": data}


@app.post("/v1/embeddings")
async def create_embeddings(req: EmbeddingsRequest, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    model = req.model or config.default_model
    texts = [req.input] if isinstance(req.input, str) else list(req.input)
    if not texts:
        return {"object": "list", "data": [], "model": model,
                "usage": {"prompt_tokens": 0, "total_tokens": 0}}
    if len(texts) > config.max_batch:
        raise HTTPException(status_code=400, detail=f"입력이 너무 많습니다(최대 {config.max_batch}).")
    if model not in set(_available_models()):
        raise HTTPException(status_code=404, detail=f"제공하지 않는 모델입니다: {model}")

    try:
        vectors = await engine.embed(model, texts)
    except Exception as e:
        logger.warning("임베딩 실패(model=%s): %s", model, e)
        raise HTTPException(status_code=500, detail=f"임베딩 실패: {e}")

    metrics.incr("embed_items_total", len(texts))
    data = [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)]
    toks = sum(len(t.split()) for t in texts)  # 대략치(정보용)
    return {"object": "list", "data": data, "model": model,
            "usage": {"prompt_tokens": toks, "total_tokens": toks}}
