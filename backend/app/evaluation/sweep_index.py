# SPDX-License-Identifier: Apache-2.0
"""설정 스윕 — 인덱스 축(P2) 임시 후보 컬렉션 프로비저닝.

index_axis 후보 조합마다 base 컬렉션을 복제하되 인덱스 시점 설정(parse/chunk/...)만
override 한 *임시* 컬렉션을 만들고, base 의 원본 문서를 그대로 복사해 인제스천 잡을 건다.

핵심 제약:
  - 임베딩(벡터 공간)은 절대 바꾸지 않는다. provider/model/dim/server_url/distance_metric 을
    base 와 동일하게 복제한다. pgvector 컬럼이 Vector(1024) 로 물리 고정이라 차원이 달라지면
    색인이 깨지고, 같은 차원이어야 base 와 점수를 공정하게 비교할 수 있다.
  - 원본 바이트는 오브젝트 스토리지에 이미 있으므로 source_uri 를 그대로 재사용한다(재업로드 X).
  - 임시 컬렉션은 ``ephemeral_sweep_id`` 로 표식해 스윕 종료 시 _cleanup_ephemeral 이 CASCADE 삭제.
"""

import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections.models import RagCollection
from app.documents.models import RagDocument
from app.evaluation.models import RagEvalSweep
from app.ingestion.service import create_pending_document, enqueue_job

logger = logging.getLogger(__name__)

# 인덱스 시점에 override 가능한 컬럼(임베딩 설정은 제외 — 벡터 공간 불변).
_OVERRIDABLE = ("parse_strategy", "chunk_strategy", "chunk_size", "chunk_overlap", "chunk_unit")


def _combo_label(combo: dict) -> str:
    """index_combo 를 사람이 읽을 수 있는 짧은 라벨로(컬렉션명 표시용)."""
    parts = []
    for k in _OVERRIDABLE:
        if k in combo:
            parts.append(f"{k.replace('chunk_', '').replace('_strategy', '')}={combo[k]}")
    return ",".join(parts) or "base"


def _apply_overrides(base: RagCollection, combo: dict) -> dict:
    """base 설정 위에 combo 를 덮어 인덱스 설정 dict 를 만든다(검증·클램프 포함)."""
    cfg = {k: getattr(base, k) for k in _OVERRIDABLE}
    for k, v in combo.items():
        if k in _OVERRIDABLE:
            cfg[k] = v

    # chunk_overlap >= chunk_size 면 색인이 무한 루프/깨짐 → 안전하게 클램프.
    size = int(cfg["chunk_size"])
    overlap = int(cfg["chunk_overlap"])
    if overlap >= size:
        clamped = max(0, min(overlap, size - 1))
        logger.warning(
            "스윕 임시 컬렉션: chunk_overlap(%d) >= chunk_size(%d) → %d 로 클램프",
            overlap, size, clamped,
        )
        cfg["chunk_overlap"] = clamped
    return cfg


async def provision_ephemeral_collection(
    session: AsyncSession, sweep: RagEvalSweep, base: RagCollection, index_combo: dict
) -> RagCollection:
    """index_combo 로 override 한 임시 컬렉션을 만들고 base 의 원본 문서를 인제스천한다.

    반환: 생성된 임시 RagCollection(문서 잡 enqueue 완료). 인덱싱 완료 대기는 스윕 워커가 한다.
    """
    cfg = _apply_overrides(base, index_combo)

    # 임시 컬렉션 — 이름은 UNIQUE 제약을 피하려 sweep id + 짧은 uuid 를 붙인다.
    suffix = uuid.uuid4().hex[:8]
    name = f"[sweep#{sweep.id}] {base.name} · {_combo_label(index_combo)} · {suffix}"
    ephemeral = RagCollection(
        collection_id=str(uuid.uuid4()),
        name=name[:200],
        description=f"설정 스윕 #{sweep.id} 임시 후보({_combo_label(index_combo)}). 자동 정리됨.",
        # 벡터 공간은 base 와 100% 동일하게 복제(불변).
        embedding_provider=base.embedding_provider,
        embedding_model=base.embedding_model,
        embedding_dim=base.embedding_dim,
        embedding_server_url=base.embedding_server_url,
        distance_metric=base.distance_metric,
        rerank_provider=base.rerank_provider,
        rerank_model=base.rerank_model,
        # 인덱스 시점 설정만 override.
        parse_strategy=cfg["parse_strategy"],
        chunk_strategy=cfg["chunk_strategy"],
        chunk_unit=cfg["chunk_unit"],
        chunk_size=cfg["chunk_size"],
        chunk_overlap=cfg["chunk_overlap"],
        status="active",
        ephemeral_sweep_id=sweep.id,
        created_by=sweep.created_by,
        updated_by=sweep.created_by,
    )
    session.add(ephemeral)
    await session.commit()
    await session.refresh(ephemeral)

    # base 의 원본 보유 문서를 복사(같은 source_uri/content_hash 재사용 — 재업로드 없음).
    source_docs = list((await session.execute(
        select(RagDocument).where(
            RagDocument.collection_id == base.id,
            RagDocument.source_uri.isnot(None),
        )
    )).scalars().all())

    job_count = 0
    for doc in source_docs:
        clone = await create_pending_document(
            session,
            collection_id=ephemeral.id,
            name=doc.name,
            source_type=doc.source_type,
            source_uri=doc.source_uri,
            content_hash=doc.content_hash,
            size_bytes=doc.size_bytes,
            metadata_json=doc.metadata_json,
            created_by=sweep.created_by,
        )
        await enqueue_job(session, clone.id, ephemeral.id)
        job_count += 1

    logger.info(
        "스윕 %s: 임시 컬렉션 생성 id=%d (%s) — 문서 %d개 인제스천 enqueue",
        sweep.sweep_id, ephemeral.id, _combo_label(index_combo), job_count,
    )
    return ephemeral
