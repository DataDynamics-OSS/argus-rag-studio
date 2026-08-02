# SPDX-License-Identifier: Apache-2.0
"""임베딩 메타 API — 로컬(FastEmbed) 지원 모델 목록.

컬렉션 생성 시 ``local`` 프로바이더의 모델 드롭다운을 채우는 데 쓴다. 벡터 컬럼 차원과
맞는 모델만 노출해 차원 불일치를 원천 차단한다(``?dim=`` 으로 필터)."""

import re
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.auth import CurrentUser
from app.core.config import settings
from app.core.http import auth_headers
from app.embedding.provider import list_local_models
from app.embedding.service import check_server_health, list_remote_models, probe_dimension
from app.rerank.service import list_local_rerank_models, list_rerank_models

router = APIRouter(prefix="/embedding", tags=["embedding"])


class ProbeRequest(BaseModel):
    """OpenAI 호환 임베딩 서버의 출력 차원을 감지한다."""

    server_url: str | None = None
    model: str = Field("", max_length=200)


class ServerModelsRequest(BaseModel):
    """OpenAI 호환 서버가 제공하는 모델 목록을 조회한다."""

    server_url: str | None = None


class ServerHealthRequest(BaseModel):
    """임베딩 서버 접속 테스트."""

    server_url: str = Field(..., min_length=1)


@router.get("/local-models")
async def local_models(
    _user: CurrentUser,
    dim: int | None = Query(None, description="이 차원과 일치하는 모델만(기본: 서버 기본 차원)"),
):
    """FastEmbed 로컬 임베딩 지원 모델 목록(벡터 컬럼 차원에 맞는 것만)."""
    target = dim if dim is not None else settings.embedding_default_dim
    return {"dim": target, "models": list_local_models(target_dim=target)}


@router.post("/probe")
async def probe(req: ProbeRequest, _user: CurrentUser):
    """OpenAI 호환 서버에 샘플을 보내 임베딩 차원을 감지한다. 컬럼 차원과 일치하는지도 알려준다."""
    try:
        dim = await probe_dimension(req.server_url or None, req.model)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"차원 감지 실패: {e}")
    column_dim = settings.embedding_default_dim
    return {"dim": dim, "column_dim": column_dim, "matches": dim == column_dim}


@router.post("/health")
async def server_health(req: ServerHealthRequest, _user: CurrentUser):
    """임베딩 서버 접속 테스트(/health → /models 폴백). 성공 시 {ok, url}."""
    try:
        url = await check_server_health(req.server_url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"ok": True, "url": url}


@router.post("/server-models")
async def server_models(req: ServerModelsRequest, _user: CurrentUser):
    """OpenAI 호환 서버가 제공하는 모델 ID 목록(GET /models)."""
    try:
        models = await list_remote_models(req.server_url or None)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"모델 목록 조회 실패: {e}")
    return {"models": models}


@router.get("/rerank-models")
async def rerank_models(_user: CurrentUser):
    """리랭커 서버(rerank.server_url)가 제공하는 cross-encoder 모델 목록."""
    try:
        models = await list_rerank_models()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"리랭커 모델 목록 조회 실패: {e}")
    return {"models": models}


@router.post("/rerank-health")
async def rerank_health(req: ServerHealthRequest, _user: CurrentUser):
    """리랭커 서버 접속 테스트(입력 URL 의 GET /v1/models). 성공 시 {ok, models}."""
    try:
        models = await list_rerank_models(req.server_url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"ok": True, "models": models}


@router.get("/local-rerank-models")
async def local_rerank_models(_user: CurrentUser):
    """로컬(in-process) FastEmbed cross-encoder 리랭커 모델 목록(서버 불필요)."""
    return {"models": list_local_rerank_models()}


@router.get("/parse-strategies")
async def parse_strategies(_user: CurrentUser):
    """문서 파싱 전략 목록 + 가용성(의존성 설치 여부). 컬렉션 생성/재인덱싱 UI 안내용."""
    from app.ingestion.parsers import list_parse_strategies

    return {"strategies": list_parse_strategies()}


class ExtServerStat(BaseModel):
    """외부 확장 서버(embedding/rerank/detection) 메트릭 — /stats 프록시 결과."""

    kind: str
    url: str
    ok: bool
    stats: dict | None = None
    error: str | None = None


def _stats_url(server_url: str | None) -> str | None:
    """서버 URL(예: http://host:8080/v1)에서 호스트를 유도해 /stats 엔드포인트로."""
    p = urlparse(server_url or "")
    return f"{p.scheme}://{p.netloc}/stats" if p.netloc else None


async def _fetch_stat(kind: str, url: str, key: str, hdr: str, scheme: str) -> ExtServerStat:
    su = _stats_url(url)
    if not su:
        return ExtServerStat(kind=kind, url="", ok=False, error="서버 URL 미설정")
    try:
        headers = auth_headers(key, hdr, scheme)
        async with httpx.AsyncClient(timeout=3, headers=headers) as client:
            resp = await client.get(su)
        if resp.status_code == 200:
            return ExtServerStat(kind=kind, url=su, ok=True, stats=resp.json())
        return ExtServerStat(kind=kind, url=su, ok=False, error=f"HTTP {resp.status_code}")
    except Exception as e:  # noqa: BLE001 — 연결 불가/타임아웃 등
        return ExtServerStat(kind=kind, url=su, ok=False, error=str(e)[:200])


def _prom_value(text: str, name: str) -> float | None:
    """Prometheus 텍스트에서 첫 샘플 값 — `name{...} 1.23` 형태."""
    m = re.search(rf"^{re.escape(name)}(?:\{{[^}}]*\}})?\s+([0-9.eE+-]+)\s*$", text, re.MULTILINE)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


async def _fetch_vlm_stat() -> ExtServerStat | None:
    """VLM(vLLM — /stats 없음) 프로브: /models(서빙 모델) + /version + /metrics(요청·KV 캐시)."""
    base = (settings.image_classification_server_url or "").rstrip("/")
    if not base:
        return None
    url = f"{base}/models"
    root = base[:-3] if base.endswith("/v1") else base  # /version·/metrics 는 루트 경로
    try:
        headers = auth_headers(settings.image_classification_api_key,
                               settings.image_classification_auth_header,
                               settings.image_classification_auth_scheme)
        async with httpx.AsyncClient(timeout=3, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return ExtServerStat(kind="vlm", url=url, ok=False, error=f"HTTP {resp.status_code}")
            models = [m.get("id") for m in (resp.json().get("data") or [])]
            stats: dict = {"server": "vlm", "model": models[0] if models else None,
                           "models": {"count": len(models), "loaded": models}}
            # 부가 메트릭(best-effort — 실패해도 연결 상태에는 영향 없음)
            try:
                ver = await client.get(f"{root}/version")
                if ver.status_code == 200:
                    stats["version"] = (ver.json() or {}).get("version")
            except Exception:  # noqa: BLE001
                pass
            try:
                met = await client.get(f"{root}/metrics")
                if met.status_code == 200:
                    text = met.text
                    running = _prom_value(text, "vllm:num_requests_running")
                    waiting = _prom_value(text, "vllm:num_requests_waiting")
                    kv = _prom_value(text, "vllm:kv_cache_usage_perc")
                    prompt = _prom_value(text, "vllm:prompt_tokens_total")
                    gen = _prom_value(text, "vllm:generation_tokens_total")
                    stats["device"] = "cuda"  # vLLM 메트릭 노출 = GPU 서빙
                    extra: dict = {}
                    if running is not None or waiting is not None:
                        extra["요청"] = f"실행 {int(running or 0)} · 대기 {int(waiting or 0)}"
                    if kv is not None:
                        extra["KV 캐시"] = f"{round(kv * 100 if kv <= 1 else kv)}%"
                    if prompt is not None or gen is not None:
                        extra["누적 토큰"] = f"입력 {int(prompt or 0)} · 생성 {int(gen or 0)}"
                    if extra:
                        stats["extra"] = extra
            except Exception:  # noqa: BLE001
                pass
        return ExtServerStat(kind="vlm", url=url, ok=True, stats=stats)
    except Exception as e:  # noqa: BLE001
        return ExtServerStat(kind="vlm", url=url, ok=False, error=str(e)[:200])


async def _fetch_hwp_stat() -> ExtServerStat | None:
    """HWP 렌더 서버 프로브: GET /stats(요청·렌더·브라우저·업타임), 구버전은 /health 폴백."""
    base = (settings.hwp_render_url or "").rstrip("/")
    if not base:
        return None
    url = f"{base}/stats"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(url)
            if resp.status_code == 404:  # 구버전 서버 — 연결 확인만
                resp = await client.get(f"{base}/health")
                if resp.status_code == 200:
                    return ExtServerStat(kind="hwp_render", url=f"{base}/health", ok=True,
                                         stats={"server": "hwp_render", "device": "cpu"})
        if resp.status_code != 200:
            return ExtServerStat(kind="hwp_render", url=url, ok=False, error=f"HTTP {resp.status_code}")
        d = resp.json() or {}
        return ExtServerStat(kind="hwp_render", url=url, ok=True, stats={
            "server": "hwp_render", "device": "cpu",
            "version": d.get("version"),
            # 모델 자리에는 실질 렌더 엔진(rhwp WASM) 버전 — ML 모델은 없는 서비스.
            "model": f"rhwp {d['rhwp']}" if d.get("rhwp") else None,
            "uptime_seconds": d.get("uptime_seconds"),
            "extra": {
                "요청": f"총 {d.get('requests', 0)} · 오류 {d.get('errors', 0)}",
                "렌더": d.get("renders", 0),
                "브라우저": "가동" if d.get("browser_up") else "중지",
            },
        })
    except Exception as e:  # noqa: BLE001
        return ExtServerStat(kind="hwp_render", url=url, ok=False, error=str(e)[:200])


@router.get("/server-stats", response_model=list[ExtServerStat])
async def server_stats(_user: CurrentUser):
    """서비스 런타임 프로브를 모아서 반환한다(잡 모니터링 '서비스' 탭).

    임베딩·리랭커·검출은 /stats 메트릭, VLM 은 /v1/models(서빙 모델), HWP 렌더는
    /health(연결)로 병렬 조회한다 — 다운된 서버는 ok=false 로 표시, 전체를 막지 않음."""
    import asyncio

    targets = [
        ("embedding", settings.embedding_server_url, settings.embedding_api_key,
         settings.embedding_auth_header, settings.embedding_auth_scheme),
        ("rerank", settings.rerank_server_url, settings.rerank_api_key,
         settings.rerank_auth_header, settings.rerank_auth_scheme),
    ]
    # 검출 서버는 기능이 켜져 있을 때만 모니터링 대상에 포함한다(detection.enabled=false 면 제외).
    if settings.detection_enabled:
        targets.append(
            ("detection", settings.detection_server_url, settings.detection_api_key,
             settings.detection_auth_header, settings.detection_auth_scheme)
        )
    results = await asyncio.gather(
        *(_fetch_stat(*t) for t in targets), _fetch_vlm_stat(), _fetch_hwp_stat()
    )
    return [r for r in results if r is not None]
