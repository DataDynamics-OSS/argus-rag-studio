# SPDX-License-Identifier: Apache-2.0
"""기존 문서에 자동 분류(P2 규칙 + 선택적 P3 내용 기반)를 일괄 소급 적용(백필).

P2/P3 도입 이전에 인덱싱된 문서는 ``metadata_json`` 에 ``doc_type`` 이 없어 검색 메타데이터
필터(P1)가 걸리지 않는다. 이 스크립트는 **재파싱·재임베딩 없이** 분류만 다시 계산해 채운다:

  - P2(규칙): 파일명 + 기존 metadata_json 만으로 doc_type 결정(I/O 없음, 저비용).
  - P3(내용 기반, --content): 규칙이 ``other`` 로 둔 문서만, **저장된 청크에서 선두 텍스트를
    재구성**해(원본 재다운로드/재파싱 없음) 앵커 임베딩과 비교해 유형을 추정한다.

인제스천 파이프라인(``ingestion/service.run_pipeline``)의 분류 단계와 동일한 함수를 쓴다 —
결과가 신규 인제스천과 일치한다. 사람/출처 확정값은 보존하고, 분류는 멱등하다.

사용법(backend 디렉터리에서):
    ARGUS_RAG_STUDIO_SERVER_CONFIG_DIR=packaging/config \\
        ./.venv/bin/python -m scripts.backfill_classification [옵션]

옵션:
    --collection ID  특정 컬렉션만 처리
    --content        P3 내용 기반 보강도 수행(other 문서를 앵커 임베딩으로 재분류)
    --force          이미 doc_type 이 있는 문서도 재계산(규칙/앵커 변경 후 재적용)
    --limit N        최대 N개만 처리
    --dry-run        저장 없이 변경 예정만 출력
"""

import argparse
import asyncio
import json
import logging

from sqlalchemy import select

import app.collections.models  # noqa: F401 — FK 대상 테이블 등록
from app.chunks.models import RagChunk
from app.collections.models import RagCollection
from app.core.config import settings
from app.core.database import async_session
from app.documents.models import RagDocument
from app.embedding.service import embed_for_collection
from app.ingestion.classify import (
    DOC_TYPE_ANCHORS,
    classify_by_anchors,
    classify_document,
    needs_content_refinement,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill_classification")


def _load_meta(raw: str | None) -> dict:
    try:
        meta = json.loads(raw) if raw else {}
        return meta if isinstance(meta, dict) else {}
    except (ValueError, TypeError):
        return {}


async def _lead_text(session, document_id: int, max_chars: int) -> str:
    """저장된 청크(seq 순)에서 선두 텍스트를 max_chars 까지 재구성(재파싱 회피)."""
    rows = (await session.execute(
        select(RagChunk.text)
        .where(RagChunk.document_id == document_id)
        .order_by(RagChunk.seq)
        .limit(20)
    )).scalars().all()
    buf: list[str] = []
    total = 0
    for t in rows:
        if not t:
            continue
        buf.append(t)
        total += len(t)
        if total >= max_chars:
            break
    return " ".join(buf)[:max_chars]


async def _refine_content(session, doc: RagDocument, coll: RagCollection, meta: dict) -> bool:
    """P3 내용 기반 보강 — other 문서를 앵커 임베딩으로 재분류. 변경 시 meta 갱신 후 True."""
    lead = await _lead_text(session, doc.id, settings.content_classification_lead_chars)
    if not lead.strip():
        return False
    codes = list(DOC_TYPE_ANCHORS.keys())
    vecs = await embed_for_collection([lead, *[DOC_TYPE_ANCHORS[c] for c in codes]], coll)
    anchor_vecs = {c: vecs[i + 1] for i, c in enumerate(codes)}
    hit = classify_by_anchors(vecs[0], anchor_vecs, settings.content_classification_threshold)
    if not hit:
        return False
    meta["doc_type"], score = hit
    meta["doc_type_source"] = "embedding"
    meta["doc_type_confidence"] = round(float(score), 3)
    return True


async def run(*, collection_id: int | None, content: bool, force: bool,
              limit: int | None, dry_run: bool) -> None:
    async with async_session() as session:
        q = select(RagDocument).where(RagDocument.status == "indexed")
        if collection_id is not None:
            q = q.where(RagDocument.collection_id == collection_id)
        q = q.order_by(RagDocument.id)
        if limit:
            q = q.limit(limit)
        docs = (await session.execute(q)).scalars().all()

    logger.info(
        "대상 문서: %d개%s%s%s", len(docs),
        f" (collection={collection_id})" if collection_id is not None else "",
        " (+content)" if content else "", " (dry-run)" if dry_run else "",
    )

    coll_cache: dict[int, RagCollection | None] = {}
    changed = skipped = failed = 0
    other_before = other_after = 0

    for doc in docs:
        meta = _load_meta(doc.metadata_json)
        if not force and meta.get("doc_type"):
            skipped += 1
            continue
        before = meta.get("doc_type")
        try:
            # P2 규칙
            meta.update(classify_document(doc.name, source_meta=meta))
            # P3 내용 기반(선택) — other 로 남은 것만
            if content and needs_content_refinement(meta):
                if doc.collection_id not in coll_cache:
                    coll_cache[doc.collection_id] = await _get_collection(doc.collection_id)
                coll = coll_cache[doc.collection_id]
                if coll is not None:
                    async with async_session() as s2:
                        await _refine_content(s2, doc, coll, meta)

            after = meta.get("doc_type")
            if before == "other" or before is None:
                other_before += 1
            if after == "other":
                other_after += 1

            if dry_run:
                logger.info("[dry-run] %s: %s -> %s (%s)",
                            doc.name, before, after, meta.get("doc_type_source"))
                changed += 1
                continue

            async with async_session() as s2:
                row = await s2.get(RagDocument, doc.id)
                if row:
                    row.metadata_json = json.dumps(meta, ensure_ascii=False)
                    await s2.commit()
            changed += 1
            logger.info("OK   %s: %s -> %s (%s)",
                        doc.name, before, after, meta.get("doc_type_source"))
        except Exception as e:  # noqa: BLE001 — 한 건 실패가 전체를 막지 않게
            failed += 1
            logger.warning("FAIL %s (%s)", doc.name, e)

    logger.info(
        "완료 — 변경 %d / 건너뜀 %d / 실패 %d / 전체 %d",
        changed, skipped, failed, len(docs),
    )
    if content:
        logger.info("other: 처리 전 %d → 처리 후 %d", other_before, other_after)


async def _get_collection(collection_id: int) -> RagCollection | None:
    async with async_session() as session:
        return (await session.execute(
            select(RagCollection).where(RagCollection.id == collection_id)
        )).scalars().first()


def main() -> None:
    parser = argparse.ArgumentParser(description="기존 문서에 자동 분류(P2/P3) 일괄 소급 적용")
    parser.add_argument("--collection", type=int, default=None, help="특정 컬렉션만 처리")
    parser.add_argument("--content", action="store_true", help="P3 내용 기반 보강도 수행")
    parser.add_argument("--force", action="store_true", help="이미 doc_type 이 있어도 재계산")
    parser.add_argument("--limit", type=int, default=None, help="최대 처리 개수")
    parser.add_argument("--dry-run", action="store_true", help="저장 없이 대상만 출력")
    args = parser.parse_args()
    asyncio.run(run(
        collection_id=args.collection, content=args.content,
        force=args.force, limit=args.limit, dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
