# SPDX-License-Identifier: Apache-2.0
"""인제스천 서비스 — 잡 enqueue + 처리 파이프라인(parse→chunk→embed→index).

수집(업로드/register)과 처리를 분리한다: 등록 시 ``rag_documents`` 와 ``rag_ingestion_jobs``
행만 만들고 즉시 반환하며, 비동기 워커가 ``run_pipeline`` 으로 실제 처리를 수행한다.

멱등성: 재처리(reindex) 시 해당 문서의 기존 청크를 모두 삭제 후 재삽입한다. 같은 원본을
다시 올려도 ``content_hash`` 로 중복을 거를 수 있다(라우터에서 사전 확인).
"""

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunks.models import RagChunk
from app.collections.models import RagCollection
from app.core.config import settings
from app.documents.models import RagDocument
from app.embedding.service import embed_for_collection
from app.ingestion.chunking import chunk_text_with_meta, semantic_chunk, split_sentences
from app.ingestion.classify import classify_document
from app.ingestion.transforms import DEFAULT_PIPELINE, normalize_pipeline, run_transforms
from app.ingestion.metadata import extract_metadata
from app.ingestion.models import RagIngestionJob
from app.ingestion.parsers import PARSE_STRATEGIES, parse_document, resolve_parse_strategy
from app.storage.client import get_object
from app.vectorstore import VectorItem, get_vector_store

logger = logging.getLogger(__name__)


def _strip_nulls(value):
    """파싱 텍스트에 섞인 NUL(0x00) 등 PostgreSQL TEXT 가 거부하는 제어문자를 제거한다.

    일부 PDF/HWP 추출 결과에 0x00 이 포함되면 청크/메타데이터 INSERT 가
    CharacterNotInRepertoireError 로 실패한다. 문자열·dict·list 를 재귀 정리한다.
    """
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: _strip_nulls(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_nulls(v) for v in value]
    return value


# 구형 오피스(.doc/.ppt/.xls)는 순수 파이썬 로더가 없어 LibreOffice 로 PDF 변환 후 파싱한다.
_LEGACY_OFFICE_EXTS = {".doc", ".ppt", ".xls"}


async def _prepare_for_parse(filename: str, data: bytes) -> tuple[str, bytes]:
    """파싱 입력 준비. 구형 오피스면 PDF 로 변환(LibreOffice)해 (이름.pdf, pdf바이트) 반환.

    메타데이터는 원본 바이트에서 따로 뽑으므로(이 단계 호출 전), 여기서는 본문 파싱용만 변환한다.
    그 외 형식은 원본 그대로 반환한다.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext not in _LEGACY_OFFICE_EXTS:
        return filename, data
    from app.s3browse import office_pdf

    if not office_pdf.is_available():
        raise RuntimeError(
            f"구형 오피스({ext}) 처리에는 LibreOffice(soffice)가 필요합니다 — 미설치."
        )
    pdf = await office_pdf.convert_to_pdf(data, ext.lstrip("."))
    stem = os.path.splitext(filename)[0] or "document"
    return f"{stem}.pdf", pdf


async def parse_preview(filename: str, data: bytes, *, strategy: str, max_chars: int) -> dict:
    """파일 바이트를 **파싱만** 해서 결과 텍스트(+메타)를 반환한다. 저장·청킹·임베딩 없음.

    인제스천 파이프라인의 parse 단계와 동일한 ``parse_document`` 를 그대로 호출하므로,
    실제 인제스천에서 나올 텍스트를 미리/사후에 눈으로 검증할 수 있다.

    - ``strategy='auto'`` 면 파일 유형으로 실제 전략을 해석한다.
    - 잘못된 전략은 ``ValueError``, 파싱 실패는 ``parse_document`` 가 ``RuntimeError`` 를 던진다.
    - ``max_chars`` 보다 길면 자르고 ``truncated=True`` 로 표시한다(전체 길이는 ``char_count``).
    """
    strat = (strategy or "text").lower()
    if strat not in PARSE_STRATEGIES:
        raise ValueError(f"알 수 없는 파싱 전략: {strat}")
    # 구형 오피스면 PDF 변환 후(이름도 .pdf 로) 파싱 — 전략 자동해석도 변환 결과 기준.
    parse_name, parse_data = await _prepare_for_parse(filename, data)
    resolved = resolve_parse_strategy(parse_name) if strat == "auto" else strat
    t0 = time.perf_counter()
    body = await asyncio.to_thread(parse_document, parse_name, parse_data, strat)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    body = _strip_nulls(body)  # 인제스천과 동일하게 NUL 제거
    full = len(body)
    truncated = full > max_chars
    return {
        "filename": filename,
        "strategy": resolved,
        "char_count": full,
        "truncated": truncated,
        "elapsed_ms": elapsed_ms,
        "text": body[:max_chars] if truncated else body,
    }


def _resolve_pipeline(collection: RagCollection) -> dict:
    """컬렉션의 인제스천 보강 파이프라인(있으면) 또는 기본값."""
    raw = getattr(collection, "ingestion_pipeline", None)
    return normalize_pipeline(raw) if raw else DEFAULT_PIPELINE


async def chunk_body(
    body: str,
    collection: RagCollection,
    *,
    strategy: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    chunk_unit: str | None = None,
    pipeline: dict | None = None,
    image_classification: dict | None = None,
) -> list[dict]:
    """본문을 컬렉션(또는 override) 설정으로 청킹한다. 인제스천·프리뷰 공용(단일 출처).

    semantic 은 문장 임베딩이 필요해 컬렉션 임베더(서버)를 호출한다. 그 외 전략은 서버 불필요.
    반환: chunk_text_with_meta/semantic_chunk 의 piece dict 목록(text/section_path/char_*/token_count).
    ``image_classification`` 은 image_captions 단계용 VLM 분석 결과(1-c 산출 — ctx 로 주입).
    """
    strat = strategy or collection.chunk_strategy
    size = chunk_size if chunk_size is not None else collection.chunk_size
    overlap = chunk_overlap if chunk_overlap is not None else collection.chunk_overlap
    unit = chunk_unit or collection.chunk_unit

    # 인제스천 보강 파이프라인 — post_parse(본문 텍스트) → 청킹 → post_chunk(청크).
    # 컬렉션의 ingestion_pipeline(없으면 기본). 미리보기 등에서 draft 를 인자로 override 가능.
    pipeline = normalize_pipeline(pipeline) if pipeline else _resolve_pipeline(collection)
    # pii_regex/pii_function 단계가 있으면 규칙·함수를 미리 로드해 ctx 로 주입(apply 는 to_thread 라 async DB 불가).
    pp = pipeline["post_parse"]
    post_parse_ctx = None
    need_rules = any(s.get("id") == "pii_regex" for s in pp)
    need_funcs = any(s.get("id") == "pii_function" for s in pp)
    if need_rules or need_funcs:
        from app.core.database import async_session
        from app.pii.service import list_enabled_dicts, list_enabled_functions
        async with async_session() as _s:
            post_parse_ctx = {}
            if need_rules:
                post_parse_ctx["pii_rules"] = await list_enabled_dicts(_s)
            if need_funcs:
                post_parse_ctx["pii_functions"] = await list_enabled_functions(_s)
    # image_captions 단계가 있으면 VLM 분석 결과를 ctx 로 주입(pii 와 동일 패턴).
    if any(s.get("id") == "image_captions" for s in pp):
        post_parse_ctx = post_parse_ctx or {}
        post_parse_ctx["image_classification"] = image_classification or {}
    body = await asyncio.to_thread(run_transforms, "post_parse", body, pp, post_parse_ctx)

    if strat == "semantic":
        sentences = await asyncio.to_thread(split_sentences, body)
        if len(sentences) >= 2:
            sentence_vecs = await embed_for_collection(sentences, collection)
            pieces = await asyncio.to_thread(semantic_chunk, body, sentences, sentence_vecs, size, unit)
        else:  # 문장 1개 이하 → 일반 청킹 폴백
            pieces = await asyncio.to_thread(chunk_text_with_meta, body, size, overlap, "recursive", unit)
    else:
        pieces = await asyncio.to_thread(chunk_text_with_meta, body, size, overlap, strat, unit)

    return await asyncio.to_thread(run_transforms, "post_chunk", pieces, pipeline["post_chunk"])


async def chunk_preview(
    filename: str,
    data: bytes,
    collection: RagCollection,
    *,
    parse_strategy: str | None = None,
    strategy: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    chunk_unit: str | None = None,
    pipeline: dict | None = None,
    image_classification: dict | None = None,
    max_chars: int,
) -> dict:
    """파일을 **파싱+청킹만** 해서 청킹 전(전문)/후(청크) 를 함께 반환한다. 저장·임베딩 없음.

    청크에는 본문 내 위치(char_start/char_end)가 포함돼 프런트에서 전문 위 구간 하이라이트가 가능하다.
    전략/크기/오버랩을 override 하면 라이브로 다른 청킹 결과를 미리 볼 수 있다.
    ``image_classification`` 은 저장된 VLM 분석 결과(문서 metadata) — image_captions 단계가
    미리보기에서도 실제 인제스천과 같은 주입을 보여주도록 한다(프리뷰에서 VLM 재호출 없음).
    """
    p_strat = (parse_strategy or collection.parse_strategy or "text").lower()
    if p_strat not in PARSE_STRATEGIES:
        raise ValueError(f"알 수 없는 파싱 전략: {p_strat}")
    parse_name, parse_data = await _prepare_for_parse(filename, data)
    body = await asyncio.to_thread(parse_document, parse_name, parse_data, p_strat)
    body = _strip_nulls(body)

    pieces = await chunk_body(
        body, collection,
        strategy=strategy, chunk_size=chunk_size, chunk_overlap=chunk_overlap, chunk_unit=chunk_unit,
        pipeline=pipeline, image_classification=image_classification,
    )

    full = len(body)
    truncated = full > max_chars
    shown = body[:max_chars] if truncated else body
    # 잘린 경우, 표시 본문 범위 안에서 시작하는 청크만(끝은 표시 길이로 클립).
    items: list[dict] = []
    for p in pieces:
        cs = p.get("char_start")
        if truncated and cs is not None and cs >= len(shown):
            continue
        ce = p.get("char_end")
        if truncated and ce is not None:
            ce = min(ce, len(shown))
        items.append({
            "seq": p.get("seq", len(items) + 1),
            "text": p["text"],
            "section_path": p.get("section_path"),
            "char_start": cs,
            "char_end": ce,
            "char_count": p.get("char_count"),
            "token_count": p.get("token_count"),
        })

    return {
        "parse_strategy": p_strat,
        "chunk_strategy": (strategy or collection.chunk_strategy),
        "chunk_size": (chunk_size if chunk_size is not None else collection.chunk_size),
        "chunk_overlap": (chunk_overlap if chunk_overlap is not None else collection.chunk_overlap),
        "chunk_unit": (chunk_unit or collection.chunk_unit),
        "char_count": full,
        "truncated": truncated,
        "body": shown,
        "chunk_total": len(pieces),
        "chunks": items,
    }


async def enqueue_job(
    session: AsyncSession, document_id: int, collection_id: int
) -> RagIngestionJob:
    """문서에 대한 인제스천 잡을 ``queued`` 상태로 생성한다."""
    job = RagIngestionJob(
        job_id=str(uuid.uuid4()),
        document_id=document_id,
        collection_id=collection_id,
        status="queued",
        progress=0,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    logger.info("인제스천 잡 enqueue: job=%s document=%d", job.job_id, document_id)
    return job


async def claim_next_job(session: AsyncSession) -> RagIngestionJob | None:
    """다음 처리 대상 잡을 원자적으로 집어 ``running`` 으로 표시한다.

    ``FOR UPDATE SKIP LOCKED`` 로 다중 워커 동시 실행에도 한 잡을 한 워커만 가져간다.
    """
    row = (await session.execute(
        select(RagIngestionJob)
        .where(RagIngestionJob.status == "queued")
        .order_by(RagIngestionJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )).scalars().first()
    if not row:
        return None
    row.status = "running"
    row.stage = "parse"
    row.started_at = func.now()
    await session.commit()
    await session.refresh(row)
    return row


async def _set_progress(
    session: AsyncSession, job: RagIngestionJob, stage: str, progress: int
) -> None:
    job.stage = stage
    job.progress = progress
    await session.commit()


async def run_pipeline(session: AsyncSession, job: RagIngestionJob) -> None:
    """단일 잡을 처리한다: 원본 로드 → 파싱 → 청킹 → 임베딩 → 청크 인덱싱.

    실패 시 잡과 문서를 ``failed`` 로 표시하고 사유를 기록한다(예외는 삼키고 로깅).
    """
    document = (await session.execute(
        select(RagDocument).where(RagDocument.id == job.document_id)
    )).scalars().first()
    if not document:
        job.status = "failed"
        job.error = "문서를 찾을 수 없습니다."
        job.finished_at = func.now()
        await session.commit()
        return

    collection = (await session.execute(
        select(RagCollection).where(RagCollection.id == job.collection_id)
    )).scalars().first()
    if not collection:
        job.status = "failed"
        job.error = "컬렉션을 찾을 수 없습니다."
        job.finished_at = func.now()
        await session.commit()
        return

    # 실패 처리에서 만료된 ORM 속성 접근(→ async lazy load → MissingGreenlet)을 피하기 위해
    # 잡/문서 식별자를 평범한 값으로 미리 확보한다.
    job_pk, job_uid, doc_id = job.id, job.job_id, job.document_id

    try:
        document.status = "processing"
        await session.commit()

        # 1) 원본 바이트 로드 (오브젝트 스토리지)
        if not document.source_uri:
            raise RuntimeError("source_uri 가 없어 원본을 로드할 수 없습니다.")
        data = await get_object(document.source_uri)

        # 1-b) 메타데이터 추출(best-effort) — 본문과 별개로 문서 속성(제목/작성자/일시)을
        #      metadata_json 에 병합 저장. 실패해도 인제스천을 막지 않는다.
        # CPU 작업(파싱·문장분리·청킹)은 to_thread 로 오프로드해 이벤트 루프(=서버 응답)를
        # 막지 않는다. (rhwp 네이티브·kss·docling 등은 동기·CPU 바운드)
        extracted = await asyncio.to_thread(extract_metadata, document.name, data)
        if extracted:
            try:
                existing = json.loads(document.metadata_json) if document.metadata_json else {}
                if not isinstance(existing, dict):
                    existing = {}
            except (ValueError, TypeError):
                existing = {}
            existing.update(extracted)
            document.metadata_json = json.dumps(_strip_nulls(existing), ensure_ascii=False)

        # 1-b2) 자동 분류(P2, best-effort) — 규칙 기반 doc_type 등 비-보안 메타데이터를
        #       metadata_json 에 채워 검색 필터(P1)가 쓸 수 있게 한다. 보안등급/DRM 은 다루지
        #       않는다(컬렉션 경계 담당). 실패해도 인제스천을 막지 않는다.
        try:
            current = json.loads(document.metadata_json) if document.metadata_json else {}
            if not isinstance(current, dict):
                current = {}
            classified = classify_document(document.name, source_meta=current)
            if classified:
                current.update(classified)
                document.metadata_json = json.dumps(_strip_nulls(current), ensure_ascii=False)
        except Exception as clf_err:  # noqa: BLE001 — 분류는 부가기능, 인제스천 진행 우선
            logger.warning("문서 분류 건너뜀: document=%s err=%s", document.name, clf_err)

        # 1-c) 이미지 분류(best-effort) — 전역 설정이 켜져 있거나, 컬렉션 파이프라인에
        #       image_captions(이미지 내용 주입) 단계가 있을 때 실행. 문서 내 이미지를 VLM 으로
        #       도표/차트/사진 등으로 식별해 metadata_json["image_classification"] 에 저장한다.
        #       분류 결과는 본문 주입(post_parse) + 청크↔이미지 연결(페이지 기준)에 재사용한다.
        #       실패해도(엔드포인트 오류/의존성 부재) 인제스천을 막지 않는다.
        caption_stage = next(
            (s for s in _resolve_pipeline(collection)["post_parse"] if s.get("id") == "image_captions"),
            None,
        )
        want_images = settings.image_classification_enabled or caption_stage is not None
        # 단계 config 의 VLM 지정(server_url/model/api_key — 있으면 전역 설정보다 우선).
        vlm_override: dict | None = None
        if caption_stage:
            _cfg = caption_stage.get("config") or {}
            vlm_override = {
                k: _cfg[k] for k in ("server_url", "model", "api_key") if _cfg.get(k)
            } or None
        image_classification: dict | None = None
        if want_images:
            try:
                from app.ingestion.image_classifier import classify_document_images

                clf = await asyncio.to_thread(
                    classify_document_images, document.name, data,
                    endpoint_override=vlm_override,
                )
                if clf.get("count"):
                    image_classification = clf
                    try:
                        existing = json.loads(document.metadata_json) if document.metadata_json else {}
                        if not isinstance(existing, dict):
                            existing = {}
                    except (ValueError, TypeError):
                        existing = {}
                    existing["image_classification"] = clf
                    document.metadata_json = json.dumps(_strip_nulls(existing), ensure_ascii=False)
            except Exception as clf_err:  # noqa: BLE001 — 분류는 부가기능, 인제스천 진행 우선
                logger.warning(
                    "이미지 분류 건너뜀: document=%s err=%s", document.name, clf_err
                )

        # 2) 파싱 — 컬렉션별 전략(text/layout/docai/vlm) 적용.
        #    구형 오피스(.doc/.ppt/.xls)는 LibreOffice 로 PDF 변환 후 파싱(메타는 위에서 원본 기준).
        await _set_progress(session, job, "parse", 20)
        parse_name, parse_data = await _prepare_for_parse(document.name, data)
        body = await asyncio.to_thread(
            parse_document,
            parse_name,
            parse_data,
            collection.parse_strategy,
            insert_image_markers=want_images,
        )
        # 추출 텍스트에 섞인 NUL(0x00) 제거 — Postgres TEXT 저장 불가 문자. 청킹 전(오프셋 보존).
        body = _strip_nulls(body)

        # 2-b) 내용 기반 doc_type 정제(P3, best-effort) — 규칙(P2)이 other 로 둔 문서만 대상.
        #       선두 텍스트 + 유형 앵커를 컬렉션 임베딩 모델로 함께 임베딩해 코사인 최대 유형을
        #       채택(threshold 이상). 에어갭(사내 임베딩 서버 재사용). 실패해도 인제스천 진행.
        if settings.content_classification_enabled and body.strip():
            try:
                from app.ingestion.classify import (
                    DOC_TYPE_ANCHORS,
                    classify_by_anchors,
                    needs_content_refinement,
                )

                meta = json.loads(document.metadata_json) if document.metadata_json else {}
                if isinstance(meta, dict) and needs_content_refinement(meta):
                    lead = body[: settings.content_classification_lead_chars]
                    codes = list(DOC_TYPE_ANCHORS.keys())
                    vecs = await embed_for_collection(
                        [lead, *[DOC_TYPE_ANCHORS[c] for c in codes]], collection
                    )
                    anchor_vecs = {c: vecs[i + 1] for i, c in enumerate(codes)}
                    hit = classify_by_anchors(
                        vecs[0], anchor_vecs, settings.content_classification_threshold
                    )
                    if hit:
                        meta["doc_type"], score = hit
                        meta["doc_type_source"] = "embedding"
                        meta["doc_type_confidence"] = round(float(score), 3)
                        document.metadata_json = json.dumps(_strip_nulls(meta), ensure_ascii=False)
                        logger.info(
                            "내용 기반 분류: document=%s → %s (%.3f)",
                            document.name, meta["doc_type"], score,
                        )
            except Exception as cc_err:  # noqa: BLE001 — 분류는 부가기능, 인제스천 진행 우선
                logger.warning("내용 기반 분류 건너뜀: document=%s err=%s", document.name, cc_err)

        # 3) 청킹 — 컬렉션별 전략/크기/오버랩 적용 + 청크별 위치 메타데이터
        await _set_progress(session, job, "chunk", 40)
        pieces = await chunk_body(body, collection, image_classification=image_classification)
        if not pieces:
            raise RuntimeError("청크가 생성되지 않았습니다(빈 문서).")

        # 3-b) 청크 ↔ 이미지 연결(best-effort). 파싱이 본문에 삽입한 이미지 위치 마커
        #      (``[[IMG:p…:i…]]``)를 가진 청크를 해당 이미지에 정확히 연결하고, 마커는 본문에서
        #      제거한다(임베딩·검색에 노출 방지). 마커가 전혀 없으면(docai/비PDF 등) 페이지
        #      텍스트 휴리스틱으로 폴백한다. 실패해도 인제스천을 막지 않는다.
        if want_images:
            try:
                from app.ingestion.image_classifier import (
                    build_chunk_image_refs,
                    extract_page_texts,
                    link_and_strip_markers,
                )

                chunk_texts = [p["text"] for p in pieces]
                linked_pieces, any_marker = await asyncio.to_thread(
                    link_and_strip_markers, chunk_texts, image_classification or {}
                )
                linked = 0
                if any_marker:
                    # 마커 기반 정확 연결 — 마커를 제거한 본문으로 교체.
                    for piece, (clean, refs) in zip(pieces, linked_pieces):
                        piece["text"] = clean
                        piece["char_count"] = len(clean)
                        if refs:
                            piece["image_refs"] = refs
                            linked += 1
                elif image_classification:
                    # 마커 없음 → 페이지 텍스트 부분일치 휴리스틱으로 폴백.
                    page_texts = await asyncio.to_thread(extract_page_texts, document.name, data)
                    refs_per_chunk = await asyncio.to_thread(
                        build_chunk_image_refs, chunk_texts, image_classification, page_texts
                    )
                    for piece, refs in zip(pieces, refs_per_chunk):
                        if refs:
                            piece["image_refs"] = refs
                            linked += 1
                logger.info(
                    "청크-이미지 연결: document=%s chunks=%d linked=%d (마커=%s)",
                    document.name, len(pieces), linked, any_marker,
                )
            except Exception as link_err:  # noqa: BLE001 — 연결은 부가기능
                logger.warning("청크-이미지 연결 건너뜀: document=%s err=%s", document.name, link_err)

        # 4) 임베딩 (컬렉션별 프로바이더/모델, 배치, 차원 검증)
        await _set_progress(session, job, "embed", 70)
        vectors = await embed_for_collection([p["text"] for p in pieces], collection)

        # 5) 인덱싱 — 기존 청크 삭제 후 재삽입(재처리 멱등). 위치 메타(section_path/offset) 저장.
        await _set_progress(session, job, "index", 90)
        store = get_vector_store()
        await session.execute(
            delete(RagChunk).where(RagChunk.document_id == document.id)
        )
        await store.delete_by_document(session, collection.id, document.id)
        # 임베딩 정본은 청크 행에 함께 저장(Postgres). 외부 스토어용 업서트 아이템도 수집.
        vector_items: list[VectorItem] = []
        for seq, (piece, vector) in enumerate(zip(pieces, vectors)):
            pos = {
                k: piece[k]
                for k in ("char_start", "char_end", "char_count", "token_count")
                if piece.get(k) is not None
            }
            # 청크에 연결된 이미지 참조([{index, page, type, summary}]) 저장(검색 결과 표시용).
            if piece.get("image_refs"):
                pos["image_refs"] = piece["image_refs"]
            cid = str(uuid.uuid4())
            session.add(RagChunk(
                chunk_id=cid,
                document_id=document.id,
                collection_id=collection.id,
                seq=seq,
                text=piece["text"],
                embedding=vector,
                section_path=piece.get("section_path"),
                metadata_json=json.dumps(pos, ensure_ascii=False) if pos else None,
            ))
            vector_items.append(VectorItem(
                chunk_id=cid, vector=vector,
                payload={"document_id": document.id, "status": "indexed", "seq": seq},
            ))
        await session.flush()
        # 렉시컬 검색(M3)용 tsvector 채우기 — 'simple' 설정으로 다국어 무난하게.
        await session.execute(
            text(
                "UPDATE rag_chunks SET tsv = to_tsvector('simple', text) "
                "WHERE document_id = :doc_id"
            ),
            {"doc_id": document.id},
        )
        # 벡터 스토어 업서트(pgvector 는 no-op — 정본이 위 청크 행에 이미 있음).
        await store.upsert(session, collection.id, vector_items)

        # 6) 완료 표시
        document.status = "indexed"
        document.chunk_count = len(pieces)
        document.indexed_at = func.now()
        job.status = "succeeded"
        job.stage = "index"
        job.progress = 100
        job.chunk_count = len(pieces)
        job.finished_at = func.now()
        await session.commit()
        logger.info(
            "인제스천 완료: job=%s document=%d chunks=%d", job_uid, doc_id, len(pieces)
        )
    except Exception as e:
        await session.rollback()
        logger.warning("인제스천 실패: job=%s document=%s err=%s", job_uid, doc_id, e)
        # 실패 상태 기록(별도 트랜잭션) — 만료 ORM 접근 없이 확보한 식별자로만. 기록 실패도 삼키지 않고
        # 명확히 로깅해, 핸들러가 다시 터져 잡이 'running' 으로 영구 정체되는 것을 막는다.
        try:
            await session.execute(
                update(RagIngestionJob)
                .where(RagIngestionJob.id == job_pk)
                .values(status="failed", error=str(e)[:2000], finished_at=func.now())
            )
            await session.execute(
                update(RagDocument)
                .where(RagDocument.id == doc_id)
                .values(status="failed")
            )
            await session.commit()
        except Exception as rec_err:  # 실패 기록조차 실패 — 잡은 정체될 수 있으나 원인을 남긴다
            await session.rollback()
            logger.error(
                "인제스천 실패 상태 기록 실패: job=%s 원인=%s 기록오류=%s", job_uid, e, rec_err
            )


async def create_pending_document(
    session: AsyncSession,
    *,
    collection_id: int,
    name: str,
    source_type: str,
    source_uri: str | None,
    content_hash: str | None,
    size_bytes: int,
    metadata_json: str | None,
    created_by: str | None,
) -> RagDocument:
    """인제스천 대상 문서 행을 ``registered`` 상태로 생성한다(업로드/register 공용)."""
    document = RagDocument(
        document_id=str(uuid.uuid4()),
        collection_id=collection_id,
        name=name,
        source_type=source_type,
        source_uri=source_uri,
        content_hash=content_hash,
        size_bytes=size_bytes,
        status="registered",
        chunk_count=0,
        metadata_json=metadata_json,
        created_by=created_by,
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)
    return document


async def find_document_by_hash(
    session: AsyncSession, collection_id: int, content_hash: str
) -> RagDocument | None:
    """컬렉션 내 동일 content_hash 문서를 찾는다(멱등 등록용)."""
    return (await session.execute(
        select(RagDocument).where(
            RagDocument.collection_id == collection_id,
            RagDocument.content_hash == content_hash,
        )
    )).scalars().first()


async def get_job(session: AsyncSession, job_id: str) -> RagIngestionJob | None:
    return (await session.execute(
        select(RagIngestionJob).where(RagIngestionJob.job_id == job_id)
    )).scalars().first()


async def list_jobs_for_collection(
    session: AsyncSession, collection_id: int, limit: int = 50
) -> list[RagIngestionJob]:
    return list((await session.execute(
        select(RagIngestionJob)
        .where(RagIngestionJob.collection_id == collection_id)
        .order_by(RagIngestionJob.created_at.desc())
        .limit(limit)
    )).scalars().all())


async def list_jobs(
    session: AsyncSession,
    *,
    status: str | None = None,
    collection_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[tuple[RagIngestionJob, str | None, str | None, str | None]], int]:
    """전역 잡 목록(필터·페이지) — (잡, 문서명, 컬렉션명, 문서UUID) + 총계. 모니터링 페이지용."""
    conds = []
    if status:
        conds.append(RagIngestionJob.status == status)
    if collection_id is not None:
        conds.append(RagIngestionJob.collection_id == collection_id)

    count_q = select(func.count()).select_from(RagIngestionJob)
    if conds:
        count_q = count_q.where(*conds)
    total = (await session.execute(count_q)).scalar() or 0

    q = (
        select(RagIngestionJob, RagDocument.name, RagCollection.name, RagDocument.document_id)
        .outerjoin(RagDocument, RagDocument.id == RagIngestionJob.document_id)
        .outerjoin(RagCollection, RagCollection.id == RagIngestionJob.collection_id)
    )
    if conds:
        q = q.where(*conds)
    q = q.order_by(RagIngestionJob.created_at.desc())
    if page_size > 0:
        q = q.offset((page - 1) * page_size).limit(page_size)
    rows = (await session.execute(q)).all()
    return [(job, doc, col, uuid_) for job, doc, col, uuid_ in rows], total


async def jobs_summary(session: AsyncSession) -> dict:
    """잡 요약 집계 — 대기/진행중/24h 완료·실패/총계/진행중 단계별 분포."""
    status_rows = (await session.execute(
        select(RagIngestionJob.status, func.count()).group_by(RagIngestionJob.status)
    )).all()
    by_status = {s: c for s, c in status_rows}

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    succeeded_24h = (await session.execute(
        select(func.count()).where(
            RagIngestionJob.status == "succeeded", RagIngestionJob.finished_at >= since
        )
    )).scalar() or 0
    failed_24h = (await session.execute(
        select(func.count()).where(
            RagIngestionJob.status == "failed", RagIngestionJob.finished_at >= since
        )
    )).scalar() or 0

    stage_rows = (await session.execute(
        select(RagIngestionJob.stage, func.count())
        .where(RagIngestionJob.status == "running")
        .group_by(RagIngestionJob.stage)
    )).all()

    return {
        "queued": by_status.get("queued", 0),
        "running": by_status.get("running", 0),
        "succeeded_24h": succeeded_24h,
        "failed_24h": failed_24h,
        "total": sum(by_status.values()),
        "running_by_stage": {(st or "?"): c for st, c in stage_rows},
    }
