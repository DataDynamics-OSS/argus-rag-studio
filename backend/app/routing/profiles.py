# SPDX-License-Identifier: Apache-2.0
"""컬렉션 라우팅 디스크립터(Phase 2) — centroid 계산·저장·로딩.

컬렉션마다 임베딩 공간이 달라 컬렉션 자체 벡터는 서로 비교 불가 → **전역 임베딩
설정(라우팅 공간)** 으로 각 컬렉션의 대표 텍스트를 임베딩해 centroid 를 사이드
테이블(rag_routing_profiles)에 둔다. 설계: design/embedding-routing.md §8 Phase 2.

- 대표 텍스트: 최근 청크 샘플(기본 64개, 최신 우선) — 없으면 컬렉션 설명(description).
- 공간이 바뀌면(전역 임베딩 설정 변경) 기존 행은 stale — 라우팅에서 제외, 재계산 필요.
- centroid/선두 임베딩 모두 L2 정규화 저장 → 라우터는 내적=코사인.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections.models import RagCollection
from app.core.config import settings
from app.routing.models import RagRoutingProfile
from app.chunks.models import RagChunk

logger = logging.getLogger(__name__)

SAMPLE_LIMIT = 64          # 컬렉션당 대표 청크 수(최신 우선)
SAMPLE_TEXT_CHARS = 1000   # 청크당 임베딩 입력 상한(비용 절제)
LEAD_TEXT_CHARS = 2000     # 라우팅 시 선두 텍스트 임베딩 입력 상한


def routing_space() -> dict:
    """라우팅 공간 = 전역 임베딩 설정(컬렉션별 설정과 무관한 공용 비교 공간)."""
    return {
        "provider": settings.embedding_provider,
        "server_url": settings.embedding_server_url,
        "model": settings.embedding_model,
        "dim": settings.embedding_default_dim,
    }


def normalize(vec: list[float]) -> list[float]:
    """L2 정규화(0 벡터는 그대로)."""
    n = math.sqrt(sum(x * x for x in vec))
    return [x / n for x in vec] if n > 0 else list(vec)


def centroid_of(vectors: list[list[float]]) -> list[float]:
    """벡터 평균 → L2 정규화(순수 함수 — 테스트 용이). 빈 입력은 빈 리스트."""
    if not vectors:
        return []
    dim = len(vectors[0])
    acc = [0.0] * dim
    for v in vectors:
        for i, x in enumerate(v):
            acc[i] += x
    return normalize([x / len(vectors) for x in acc])


async def _embed_routing(texts: list[str]) -> list[list[float]]:
    """라우팅 공간으로 임베딩(전역 설정) — 반환 벡터는 정규화하지 않음(호출부가 처리)."""
    from app.embedding.service import embed_texts

    sp = routing_space()
    return await embed_texts(
        texts, provider=sp["provider"], server_url=sp["server_url"],
        model=sp["model"], dim=sp["dim"],
    )


async def recompute_profiles(
    session: AsyncSession, collection_id: int | None = None
) -> list[dict]:
    """활성 컬렉션(또는 지정 1개)의 라우팅 디스크립터를 재계산한다.

    반환: [{collection_id, name, status(built|empty|error), source, sample_count}].
    대표 텍스트가 전혀 없으면(청크·설명 모두 없음) 기존 프로파일을 지우고 empty 로 보고.
    한 컬렉션 실패가 전체를 막지 않는다(error 행으로 보고).
    """
    q = select(RagCollection).where(RagCollection.status == "active")
    if collection_id is not None:
        q = q.where(RagCollection.id == collection_id)
    collections = list((await session.execute(q)).scalars().all())

    sp = routing_space()
    out: list[dict] = []
    for col in collections:
        row = {"collection_id": col.id, "name": col.name}
        try:
            texts = [
                t[:SAMPLE_TEXT_CHARS]
                for (t,) in (await session.execute(
                    select(RagChunk.text)
                    .where(RagChunk.collection_id == col.id)
                    .order_by(RagChunk.id.desc())
                    .limit(SAMPLE_LIMIT)
                )).all()
                if t and t.strip()
            ]
            source = "chunks"
            if not texts and (col.description or "").strip():
                texts, source = [col.description.strip()[:SAMPLE_TEXT_CHARS]], "description"
            if not texts:
                await session.execute(
                    delete(RagRoutingProfile).where(RagRoutingProfile.collection_id == col.id)
                )
                out.append({**row, "status": "empty", "source": None, "sample_count": 0})
                continue

            centroid = centroid_of([normalize(v) for v in await _embed_routing(texts)])
            existing = await session.get(RagRoutingProfile, col.id)
            if existing is None:
                existing = RagRoutingProfile(collection_id=col.id)
                session.add(existing)
            existing.centroid_json = json.dumps(centroid)
            existing.space_provider = sp["provider"]
            existing.space_model = sp["model"]
            existing.space_dim = sp["dim"]
            existing.source = source
            existing.sample_count = len(texts)
            existing.built_at = datetime.now(timezone.utc)
            out.append({**row, "status": "built", "source": source, "sample_count": len(texts)})
        except Exception as e:  # noqa: BLE001 — 한 컬렉션 실패가 전체를 막지 않음
            logger.warning("라우팅 프로파일 계산 실패: collection=%s err=%s", col.id, e)
            out.append({**row, "status": "error", "source": None, "sample_count": 0,
                        "error": str(e)[:200]})
    await session.commit()
    return out


def _space_matches(p: RagRoutingProfile, sp: dict) -> bool:
    return (
        p.space_provider == sp["provider"]
        and p.space_model == sp["model"]
        and p.space_dim == sp["dim"]
    )


async def load_profiles_for_ctx(session: AsyncSession) -> list[dict]:
    """현 라우팅 공간과 일치하는 프로파일만 ctx 형태로 반환(stale 은 제외)."""
    sp = routing_space()
    rows = list((await session.execute(select(RagRoutingProfile))).scalars().all())
    out = []
    for p in rows:
        if not _space_matches(p, sp):
            continue
        try:
            centroid = json.loads(p.centroid_json)
        except (TypeError, ValueError):
            continue
        out.append({"collection_id": p.collection_id, "centroid": centroid, "source": p.source})
    return out


async def embed_lead_text(lead_text: str) -> list[float] | None:
    """선두 텍스트를 라우팅 공간으로 임베딩(정규화) — 실패 시 None(라우팅을 막지 않음)."""
    text = (lead_text or "").strip()[:LEAD_TEXT_CHARS]
    if not text:
        return None
    try:
        return normalize((await _embed_routing([text]))[0])
    except Exception as e:  # noqa: BLE001
        logger.warning("선두 텍스트 임베딩 실패(내용 라우터 건너뜀): %s", e)
        return None


async def profiles_status(session: AsyncSession) -> list[dict]:
    """활성 컬렉션별 프로파일 상태(UI 용) — 미계산/유효/stale 구분."""
    sp = routing_space()
    collections = list((await session.execute(
        select(RagCollection).where(RagCollection.status == "active")
    )).scalars().all())
    by_id = {
        p.collection_id: p
        for p in (await session.execute(select(RagRoutingProfile))).scalars().all()
    }
    out = []
    for col in collections:
        p = by_id.get(col.id)
        preview: list[float] = []
        dim = 0
        if p is not None:
            try:
                centroid = json.loads(p.centroid_json)
                dim = len(centroid)
                preview = [round(float(x), 4) for x in centroid[:16]]
            except (TypeError, ValueError):
                pass
        out.append({
            "collection_id": col.id,
            "name": col.name,
            "built": p is not None,
            "stale": (p is not None and not _space_matches(p, sp)),
            "source": p.source if p else None,
            "sample_count": p.sample_count if p else 0,
            "built_at": p.built_at.isoformat() if p and p.built_at else None,
            "space_model": p.space_model if p else None,
            "dim": dim,
            "centroid_preview": preview,
        })
    return out
