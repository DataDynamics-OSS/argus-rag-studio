# SPDX-License-Identifier: Apache-2.0
"""라우팅 인테이크 공용 코어 — 등록 경로 + 폴더 스캔(run_scan, seen 증분 캐시).

설계: design/source-watch.md §3.3(스킵 규칙)·§4(코어 추출). API 엔드포인트
(routing/router.py)와 소스 워처(app/sourcewatch)가 이 코어를 공유한다 —
라우팅/등록 로직 중복 금지. 실행 주체는 ``username``(사람 또는 "watch:<name>")으로
남는다(문서·결정 로그의 created_by).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import posixpath
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections.models import RagCollection
from app.core.config import settings
from app.ingestion import service as ingestion_service
from app.ingestion.classify import classify_document
from app.ingestion.metadata import extract_metadata
from app.routing import service
from app.routing.base import RouteInput
from app.routing.schemas import (
    IntakeResponse,
    RouteDecision,
    ScanIntakeResponse,
    ScanItemResult,
)
from app.sourcewatch.models import RagSourceSeenFile
from app.sources import service as sources_service
from app.sources.adapters import (
    SourceEntry,
    SourceObjectNotFound,
    SourcePathError,
    normalize_source_path,
)
from app.sources.models import RagStorageSource
from app.storage.client import build_object_key, put_object

logger = logging.getLogger(__name__)

_DECISION_KEYS = (
    "collection_id", "collection_name", "confidence", "mode",
    "matched_router", "fallback_used", "review", "policy_version", "trace",
)


def to_decision(result: dict) -> RouteDecision:
    return RouteDecision(**{k: result.get(k) for k in _DECISION_KEYS})


LEAD_MAX_BYTES = 20 * 1024 * 1024  # 선두 텍스트 추출 대상 파일 크기 상한(과대 파일 방어)


def _extract_lead_text(filename: str, data: bytes) -> str:
    """내용 라우터(content_embedding)용 선두 텍스트 — text 전략 경량 파싱(best-effort).

    실패/과대 파일은 빈 문자열(내용 라우터만 조용히 건너뜀 — 다른 단계는 그대로).
    반환은 프로파일 임베딩 입력 상한(LEAD_TEXT_CHARS)으로 자른다.
    """
    from app.ingestion.parsers import parse_document
    from app.routing.profiles import LEAD_TEXT_CHARS

    if not data or len(data) > LEAD_MAX_BYTES:
        return ""
    try:
        return (parse_document(filename, data, "text") or "")[:LEAD_TEXT_CHARS]
    except Exception as e:  # noqa: BLE001
        logger.info("선두 텍스트 추출 건너뜀(내용 라우터 미적용): %s err=%s", filename, e)
        return ""


async def build_route_input(
    filename: str,
    data: bytes,
    content_hash: str | None,
    source_type: str = "upload",
    source_path: str = "",
    storage: str = "",
    with_lead: bool = False,
) -> RouteInput:
    """업로드 바이트에서 라우팅 입력(메타데이터+자동분류)을 만든다 — 파싱/임베딩 없이 저비용.

    인제스천 파이프라인과 동일한 ``extract_metadata`` + ``classify_document`` 를 재사용해, 실제
    인제스천에서 쓸 메타데이터와 같은 신호로 라우팅한다(best-effort — 추출 실패해도 파일명만으로 진행).
    참조 인테이크는 ``source_path``/``storage`` 를 채우고, 출처를 메타데이터(origin_*)에도 보존한다.

    ``with_lead=True``(활성 정책에 content_embedding 단계가 있을 때 — 호출부가
    ``service.policy_needs_content`` 로 판단)면 선두 텍스트를 text 전략으로 추출한다 —
    Phase 2 내용 라우터의 유일한 추가 비용이며 단계가 없으면 기존과 동일하게 무비용.
    """
    meta: dict = {}
    try:
        extracted = await asyncio.to_thread(extract_metadata, filename, data)
        if isinstance(extracted, dict):
            meta.update(extracted)
    except Exception as e:  # noqa: BLE001
        logger.warning("라우팅 메타추출 건너뜀: %s err=%s", filename, e)
    try:
        classified = classify_document(filename, source_meta=meta)
        if isinstance(classified, dict):
            meta.update(classified)
    except Exception as e:  # noqa: BLE001
        logger.warning("라우팅 분류 건너뜀: %s err=%s", filename, e)
    if storage:
        meta["origin_source"] = storage
    if source_path:
        meta["origin_path"] = source_path
    lead_text = ""
    if with_lead:
        lead_text = await asyncio.to_thread(_extract_lead_text, filename, data)
    return RouteInput(
        filename=filename, metadata=meta, source_type=source_type,
        content_hash=content_hash, source_path=source_path, storage=storage,
        lead_text=lead_text,
    )


async def fetch_from_source(source: RagStorageSource, path: str) -> tuple[str, bytes]:
    """소스에서 문서 바이트를 가져온다 — 경로 정규화 + read 전 stat 크기 상한 검사.

    반환: (정규화 경로, 바이트). 경로 오류 400 / 미존재 404 / 상한 초과 413 / 소스 장애 502.
    """
    try:
        norm = normalize_source_path(path)
        adapter = sources_service.adapter_for(source)
    except SourcePathError as e:
        raise HTTPException(status_code=400, detail=str(e))
    max_bytes = settings.source_max_fetch_mb * 1024 * 1024
    try:
        st = await adapter.stat(norm)
        if st.size > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"파일이 상한({settings.source_max_fetch_mb}MB)을 초과합니다: {st.size} bytes",
            )
        data = await adapter.read(norm)
    except SourceObjectNotFound:
        raise HTTPException(
            status_code=404, detail=f"소스 '{source.name}' 에 경로가 없습니다: {norm}"
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — 소스 연결/자격증명 장애를 502 로 표면화
        logger.warning("소스 접근 실패: source=%s path=%s err=%s", source.name, norm, e)
        raise HTTPException(status_code=502, detail=f"소스 '{source.name}' 접근 실패: {e}")
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    return norm, data


async def register_and_enqueue(
    session: AsyncSession,
    username: str,
    route_input: RouteInput,
    result: dict,
    data: bytes,
    content_type: str | None,
) -> IntakeResponse:
    """라우팅 결정 이후의 공통 등록 경로 — 컬렉션 검증 → 중복 검사 → 등록/적재 → enqueue → 로깅.

    업로드·참조·스캔·워처 인테이크가 공유한다(결정 전 단계만 다름). 422/409 는 여기서 발생.
    """
    cid = result.get("collection_id")
    if cid is None:
        raise HTTPException(
            status_code=422,
            detail="라우팅 실패: 매칭되는 규칙이 없고 폴백 컬렉션도 설정되지 않았습니다.",
        )
    collection = (await session.execute(
        select(RagCollection).where(RagCollection.id == cid)
    )).scalars().first()
    if not collection or collection.status != "active":
        raise HTTPException(
            status_code=422, detail=f"라우팅 대상 컬렉션(id={cid})을 찾을 수 없거나 비활성입니다."
        )

    dup = await ingestion_service.find_document_by_hash(session, cid, route_input.content_hash)
    if dup:
        raise HTTPException(
            status_code=409,
            detail=f"동일한 내용의 문서가 이미 등록되어 있습니다(컬렉션 {cid}, id={dup.id}).",
        )

    document = await ingestion_service.create_pending_document(
        session,
        collection_id=cid,
        name=route_input.filename,
        source_type=route_input.source_type,
        source_uri=None,
        content_hash=route_input.content_hash,
        size_bytes=len(data),
        metadata_json=json.dumps(route_input.metadata, ensure_ascii=False) or None,
        created_by=username,
    )
    key = build_object_key(collection.collection_id, document.document_id, route_input.filename)
    document.source_uri = await put_object(key, data, content_type=content_type)
    await session.commit()

    job = await ingestion_service.enqueue_job(session, document.id, cid)

    try:
        await service.log_decision(session, document.id, result, username)
    except Exception as e:  # noqa: BLE001
        logger.warning("라우팅 결정 로깅 실패: document=%d err=%s", document.id, e)

    return IntakeResponse(
        document_id=document.id, document_uuid=document.document_id,
        name=document.name, status=document.status, job_id=job.job_id,
        decision=to_decision(result),
    )


async def scan_one(
    session: AsyncSession,
    username: str,
    source: RagStorageSource,
    path: str,
    dry_run: bool,
    with_lead: bool = False,
) -> ScanItemResult:
    """scan 파일 1개 처리 — 실패해도 예외를 올리지 않고 상태로 보고한다(나머지 파일 계속).

    dry_run 은 결정+중복 검사까지만(등록·적재 없음), 실행은 단건 참조 인테이크와 동일 경로.
    """
    try:
        norm, data = await fetch_from_source(source, path)
    except HTTPException as e:
        return ScanItemResult(path=path, status="failed", detail=str(e.detail))

    filename = posixpath.basename(norm)
    route_input = await build_route_input(
        filename, data, hashlib.sha256(data).hexdigest(),
        source_type="storage_ref", source_path=norm, storage=source.name,
        with_lead=with_lead,
    )
    result = await service.decide(session, route_input)
    base = dict(
        path=norm,
        collection_id=result.get("collection_id"),
        collection_name=result.get("collection_name"),
        confidence=result.get("confidence"),
        review=bool(result.get("review")),
        fallback_used=bool(result.get("fallback_used")),
        matched_router=result.get("matched_router"),
    )

    if dry_run:
        cid = result.get("collection_id")
        if cid is None:
            return ScanItemResult(**base, status="no_route", detail="매칭 규칙·폴백 없음")
        dup = await ingestion_service.find_document_by_hash(session, cid, route_input.content_hash)
        if dup:
            return ScanItemResult(**base, status="duplicate", detail=f"동일 내용 문서 존재(id={dup.id})")
        return ScanItemResult(**base, status="routed")

    try:
        res = await register_and_enqueue(
            session, username, route_input, result, data, mimetypes.guess_type(filename)[0]
        )
        return ScanItemResult(**base, status="routed", document_id=res.document_id, job_id=res.job_id)
    except HTTPException as e:
        status = "duplicate" if e.status_code == 409 else "no_route" if e.status_code == 422 else "failed"
        return ScanItemResult(**base, status=status, detail=str(e.detail))
    except Exception as e:  # noqa: BLE001 — 파일 1개 실패가 scan 전체를 막지 않게
        logger.warning("scan 등록 실패: source=%s path=%s err=%s", source.name, norm, e)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return ScanItemResult(**base, status="failed", detail=str(e))


# ---------------------------------------------------------------------------
# seen 증분 캐시 — 스킵 규칙(순수)과 적용/기록
# ---------------------------------------------------------------------------

def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def should_skip_seen(
    seen: RagSourceSeenFile | None,
    entry_size: int,
    entry_mtime: datetime | None,
    active_policy_version: int | None,
) -> bool:
    """seen 스킵 규칙(설계 §3.3, 순수 판정) — True 면 읽지 않고 건너뛴다.

    - routed/duplicate + 지문(size+mtime) 동일 → skip(이미 들어간 파일)
    - no_route/failed + 지문 동일 + **정책 버전도 동일** → skip(같은 정책이면 결과 동일)
    - 지문 다름/신규 → 재처리(content_hash 중복 차단이 최종 방어선)
    """
    if seen is None:
        return False
    same_print = (
        seen.size == entry_size
        and _utc(seen.mtime) == _utc(entry_mtime)
        and entry_mtime is not None
    )
    if not same_print:
        return False
    if seen.status in ("routed", "duplicate"):
        return True
    # no_route | failed — 정책이 바뀌면 새 규칙으로 구제될 수 있으므로 재평가.
    return seen.policy_version is not None and seen.policy_version == active_policy_version


async def _load_seen(
    session: AsyncSession, source_pk: int, paths: list[str]
) -> dict[str, RagSourceSeenFile]:
    out: dict[str, RagSourceSeenFile] = {}
    for i in range(0, len(paths), 500):
        chunk = paths[i:i + 500]
        rows = (await session.execute(
            select(RagSourceSeenFile).where(
                RagSourceSeenFile.source_id == source_pk,
                RagSourceSeenFile.path.in_(chunk),
            )
        )).scalars().all()
        for r in rows:
            out[r.path] = r
    return out


async def _upsert_seen(
    session: AsyncSession, source_pk: int, entry: SourceEntry,
    status: str, policy_version: int | None,
) -> None:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    now = datetime.now(timezone.utc)
    values = dict(
        size=entry.size, mtime=_utc(entry.mtime), status=status,
        policy_version=policy_version, last_seen_at=now,
    )
    stmt = pg_insert(RagSourceSeenFile).values(
        source_id=source_pk, path=entry.path, **values
    ).on_conflict_do_update(constraint="uq_source_seen_path", set_=values)
    await session.execute(stmt)


async def prune_seen(session: AsyncSession, older_than_days: int) -> int:
    """소스에서 사라진 파일의 잔재 정리 — last_seen_at 이 오래된 행 삭제."""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    res = await session.execute(
        delete(RagSourceSeenFile).where(RagSourceSeenFile.last_seen_at < cutoff)
    )
    await session.commit()
    return res.rowcount or 0


# ---------------------------------------------------------------------------
# run_scan — 폴더 스캔 실행 단위(엔드포인트·워처 공용)
# ---------------------------------------------------------------------------

async def run_scan(
    session: AsyncSession,
    source: RagStorageSource,
    *,
    prefix: str,
    recursive: bool,
    dry_run: bool,
    limit: int,
    username: str,
    use_seen: bool = True,
) -> ScanIntakeResponse:
    """소스 폴더(prefix) 하위 파일들을 일괄 인테이크 — 파일별 배분 리포트 반환.

    seen 증분 캐시(설계 §3.3): 지문(size+mtime) 동일 파일은 읽지 않고 건너뛴다(skipped).
    ``dry_run`` 은 캐시를 읽지도 쓰지도 않는다 — 시뮬레이션은 항상 전량 평가.
    """
    try:
        norm_prefix = normalize_source_path(prefix, allow_empty=True)
        adapter = sources_service.adapter_for(source)
        listing = await adapter.list(norm_prefix, recursive=recursive)
    except SourcePathError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except SourceObjectNotFound:
        raise HTTPException(status_code=404, detail=f"소스 '{source.name}' 에 경로가 없습니다: {prefix}")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("scan 열거 실패: source=%s prefix=%s err=%s", source.name, prefix, e)
        raise HTTPException(status_code=502, detail=f"소스 '{source.name}' 접근 실패: {e}")

    entries = [e for e in listing.entries if not e.is_dir]

    use_cache = use_seen and not dry_run
    seen_by_path: dict[str, RagSourceSeenFile] = {}
    policy_version: int | None = None
    if use_cache:
        policy = await service.get_default_policy(session)
        policy_version = policy.active_version
        seen_by_path = await _load_seen(session, source.id, [e.path for e in entries])

    # 스킵 판정은 전체 목록에 대해(읽기 전·추가 I/O 없음) — 상한(limit)은 "처리"에만 적용.
    to_process: list[SourceEntry] = []
    skipped = 0
    touched_ids: list[int] = []
    for entry in entries:
        seen = seen_by_path.get(entry.path)
        if use_cache and should_skip_seen(seen, entry.size, entry.mtime, policy_version):
            skipped += 1
            touched_ids.append(seen.id)
            continue
        to_process.append(entry)

    truncated = listing.truncated or len(to_process) > limit
    to_process = to_process[:limit]

    items: list[ScanItemResult] = []
    with_lead = await service.policy_needs_content(session) if to_process else False
    for entry in to_process:
        item = await scan_one(session, username, source, entry.path, dry_run, with_lead=with_lead)
        items.append(item)
        if use_cache and item.status in ("routed", "duplicate", "no_route", "failed"):
            try:
                await _upsert_seen(session, source.id, entry, item.status, policy_version)
                await session.commit()
            except Exception as e:  # noqa: BLE001 — 캐시 실패가 scan 을 막지 않게(최적화일 뿐)
                logger.warning("seen 기록 실패: source=%s path=%s err=%s", source.name, entry.path, e)
                await session.rollback()

    if use_cache and touched_ids:
        # 여전히 존재하는 파일의 프루닝 방지 — last_seen_at 터치(청크 갱신).
        now = datetime.now(timezone.utc)
        for i in range(0, len(touched_ids), 500):
            await session.execute(
                update(RagSourceSeenFile)
                .where(RagSourceSeenFile.id.in_(touched_ids[i:i + 500]))
                .values(last_seen_at=now)
            )
        await session.commit()

    counts: dict[str, int] = {}
    for it in items:
        counts[it.status] = counts.get(it.status, 0) + 1

    return ScanIntakeResponse(
        source_name=source.name, prefix=norm_prefix, recursive=recursive,
        dry_run=dry_run, scanned=len(items), skipped=skipped, truncated=truncated,
        counts=counts, items=items,
    )
