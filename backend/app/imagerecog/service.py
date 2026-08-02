# SPDX-License-Identifier: Apache-2.0
"""이미지 추출 및 분석 서비스 — 문서에서 이미지 추출 → VLM 분류 → 썸네일 동봉.

설정(``image_classification.*``)이 켜져 있어야 하며, 인제스천과 동일한 분류 엔드포인트/모델/
카테고리/cap 을 그대로 사용한다(설정 > 이미지 추출 및 분류에서 조정).

추출과 분석은 2단계로 분리한다: ``extract_document_stream``/``extract_url_stream`` 이 이미지를
한 장씩 추출·저장하며 실행 1건(status=extracted)을 ``rag_image_recognition_runs`` 에 기록하고
(원본·썸네일·source·manifest 를 분류 버킷 ``settings.os_classification_bucket`` 에 저장),
``analyze_run_stream`` 이 사용자가 선택한 이미지만 버킷에서 다시 읽어 분석·갱신한다. 이력은
``list_runs``/``get_run_detail``/``delete_run`` 으로 조회·삭제한다(단건 비스트리밍
``analyze_document`` 은 휘발성, 저장하지 않음).
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def analyze_document(filename: str, data: bytes) -> dict:
    """문서 1건의 이미지를 추출·분류해 결과(썸네일 포함)를 반환한다.

    Raises:
        RuntimeError: 분류 비활성/모델 미설정/LibreOffice 미설치 등(라우터가 4xx 로 매핑).
    """
    from app.core.config import settings
    from app.imaging.extractors import extract_images, is_supported, source_kind
    from app.imaging.thumbnails import make_thumbnail, to_data_url
    from app.ingestion.image_classifier import _resolve_endpoint, classify_image_bytes

    if not settings.image_classification_enabled:
        raise RuntimeError(
            "이미지 추출 및 분류가 비활성화되어 있습니다. 설정 > 이미지 추출 및 분류에서 켜고 엔드포인트를 지정하세요."
        )
    if not is_supported(filename):
        raise RuntimeError(f"지원하지 않는 파일 형식입니다: {filename}")
    # 엔드포인트/모델 미설정이면 추출 전에 명확히 실패.
    _resolve_endpoint()

    kind = source_kind(filename)
    images = await extract_images(filename, data, with_png=True)
    if not images:
        return {
            "filename": filename, "source_kind": kind, "count": 0,
            "extracted": 0, "truncated": False, "counts_by_type": {}, "items": [],
        }

    cap = settings.image_classification_max_images
    extracted = len(images)
    truncated = bool(cap and extracted > cap)
    if truncated:
        images = images[:cap]

    thumb_max = settings.image_conversion_thumbnail_max or 320

    def _classify_all() -> tuple[list[dict], dict[str, int]]:
        import httpx

        url, _model, headers, timeout = _resolve_endpoint()
        items: list[dict] = []
        counts: dict[str, int] = {}
        with httpx.Client(timeout=timeout, headers=headers) as client:
            for im in images:
                if not im.png:  # 디코드 실패 이미지 — 분류 생략
                    continue
                try:
                    res = classify_image_bytes(im.png, client=client)
                except Exception as e:  # noqa: BLE001 — 한 장 실패가 전체를 막지 않음
                    logger.warning("이미지 추출 및 분류 실패(index=%s, %s): %s", im.index, im.locator, e)
                    continue
                counts[res["type"]] = counts.get(res["type"], 0) + 1
                items.append({
                    "index": im.index, "page": im.page, "locator": im.locator,
                    "type": res["type"], "confidence": res["confidence"],
                    "summary": res["summary"],
                    "ocr_text": res.get("ocr_text", ""),
                    "details": res.get("details", ""),
                    "width": im.width, "height": im.height,
                    "thumbnail": to_data_url(make_thumbnail(im.png, thumb_max)),
                    "original": to_data_url(im.png),  # 확대 보기용 원본(축소 없음)
                })
        return items, counts

    items, counts = await asyncio.to_thread(_classify_all)
    logger.info(
        "이미지 추출 및 분석: file=%s kind=%s extracted=%d classified=%d", filename, kind, extracted, len(items)
    )
    return {
        "filename": filename, "source_kind": kind, "count": len(items),
        "extracted": extracted, "truncated": truncated,
        "counts_by_type": counts, "items": items,
    }


async def extract_document_stream(
    filename: str, data: bytes, *, batch_id: str | None = None,
    created_by: str | None = None, content_type: str | None = None,
):
    """업로드 문서/이미지에서 이미지를 추출·저장하며 진행 상황을 SSE 로 흘린다(분석은 하지 않음).

    추출된 이미지를 한 장씩 ``image`` 이벤트로 보내고, 모두 끝나면 ``done`` 으로 ``run_id`` 를
    알린다. 분석은 이후 ``analyze_run_stream`` 으로 사용자가 선택한 이미지만 수행한다.
    """
    from app.core.config import settings
    from app.imaging.extractors import extract_images, is_supported, source_kind

    if not settings.image_classification_enabled:
        raise RuntimeError(
            "이미지 추출 및 분류가 비활성화되어 있습니다. 설정 > 이미지 추출 및 분류에서 켜고 엔드포인트를 지정하세요."
        )
    if not is_supported(filename):
        raise RuntimeError(f"지원하지 않는 파일 형식입니다: {filename}")

    images = await extract_images(filename, data, with_png=True)

    async def _aiter():
        for im in images:
            yield im

    async for ev in _extract_core(
        filename=filename, kind=source_kind(filename), source_url=None,
        source_bytes=data, source_content_type=content_type,
        batch_id=batch_id, created_by=created_by,
        image_aiter=_aiter(), total_hint=len(images),
    ):
        yield ev


async def extract_url_stream(
    url: str, *, drop_small: bool = True, batch_id: str | None = None,
    created_by: str | None = None,
):
    """외부 URL 의 HTML 이미지를 **받는 대로 한 장씩** 추출·저장하며 SSE 로 흘린다(분석은 안 함)."""
    from app.core.config import settings
    from app.imaging.extractors import open_url_images

    if not settings.image_classification_enabled:
        raise RuntimeError(
            "이미지 추출 및 분류가 비활성화되어 있습니다. 설정 > 이미지 추출 및 분류에서 켜고 엔드포인트를 지정하세요."
        )

    target = (url or "").strip()
    total, title, agen = await open_url_images(
        target, with_png=True, drop_small=drop_small,
        min_kb=settings.image_classification_small_image_min_kb,
    )
    # 파일명은 HTML 타이틀(없으면 URL), 원본 URL 은 source_url 로 보관(이력 툴팁용).
    label = (title or target)[:500]
    async for ev in _extract_core(
        filename=label, kind="URL", source_url=target,
        source_bytes=None, source_content_type=None,
        batch_id=batch_id, created_by=created_by,
        image_aiter=agen, total_hint=total,
    ):
        yield ev


async def _extract_core(
    *, filename: str, kind: str, source_url: str | None, source_bytes: bytes | None,
    source_content_type: str | None, batch_id: str | None, created_by: str | None,
    image_aiter, total_hint: int,
):
    """이미지(async 이터러블)를 한 장씩 버킷에 저장하며 ``start``/``image``/``done`` 을 흘린다.

    추출 1건 = run 1건(상태 ``extracted``)으로 기록한다. 분석은 별도(``analyze_run_stream``).
    """
    import datetime as _dt
    import json
    import uuid

    from app.core.config import settings
    from app.imaging.thumbnails import make_thumbnail, to_data_url
    from app.imagerecog import storage as clf_storage

    cap = settings.image_classification_max_images
    thumb_max = settings.image_conversion_thumbnail_max or 320

    run_id = str(uuid.uuid4())
    kst = _dt.timezone(_dt.timedelta(hours=9))  # 날짜 폴더는 KST(UTC+9) 기준.
    now = _dt.datetime.now(kst)
    prefix = clf_storage.run_prefix(run_id, now.strftime("%Y-%m-%d"))

    store_ok = False
    try:
        await clf_storage.ensure_bucket()
        store_ok = True
    except Exception as e:  # noqa: BLE001
        logger.warning("분류 버킷 준비 실패 — 저장 없이 진행(run=%s): %s", run_id, e)

    source_key_val: str | None = None
    if store_ok and source_bytes:
        try:
            sk = clf_storage.source_key(prefix, filename)
            await clf_storage.put_bytes(sk, source_bytes, source_content_type or "application/octet-stream")
            source_key_val = sk
        except Exception as e:  # noqa: BLE001
            logger.warning("원본 파일 저장 실패(run=%s): %s", run_id, e)

    yield {
        "type": "start", "run_id": run_id, "filename": filename,
        "source_kind": kind, "total": total_hint,
    }

    manifest_items: list[dict] = []
    count = 0
    truncated = False
    async for im in image_aiter:
        if not im.png:
            continue
        if cap and count >= cap:  # 최대 장수 초과 — 나머지는 버린다.
            truncated = True
            break
        idx = im.index
        thumb = await asyncio.to_thread(make_thumbnail, im.png, thumb_max)
        okey = clf_storage.original_key(prefix, idx)
        tkey = clf_storage.thumb_key(prefix, idx)
        if store_ok:
            try:
                await clf_storage.put_bytes(okey, im.png, "image/png")
                await clf_storage.put_bytes(tkey, thumb, "image/png")
            except Exception as e:  # noqa: BLE001
                logger.warning("이미지 저장 실패(run=%s, index=%s): %s", run_id, idx, e)
        manifest_items.append({
            "index": idx, "page": im.page, "locator": im.locator,
            "width": im.width, "height": im.height,
            "original_key": okey, "thumb_key": tkey, "result": None,
        })
        yield {
            "type": "image", "run_id": run_id, "index": idx, "page": im.page,
            "locator": im.locator, "width": im.width, "height": im.height,
            "thumbnail": to_data_url(thumb), "original": to_data_url(im.png),
        }
        count += 1

    # manifest 기록 + 실행 이력 row INSERT(status=extracted) — 베스트에포트.
    if store_ok:
        manifest = {
            "run_id": run_id, "batch_id": batch_id, "filename": filename,
            "source_kind": kind, "status": "extracted",
            "extracted_count": count, "analyzed_count": 0,
            "counts_by_type": {}, "truncated": truncated,
            "created_at": now.isoformat(),
            "source_filename": filename, "source_key": source_key_val,
            "source_url": source_url, "source_content_type": source_content_type,
            "items": manifest_items,
        }
        try:
            await clf_storage.put_json(
                clf_storage.manifest_key(prefix), json.dumps(manifest, ensure_ascii=False)
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("manifest 기록 실패(run=%s): %s", run_id, e)
        # 실제 저장된 디렉토리 크기는 S3 list 로 집계(원본·썸네일·source·manifest 합).
        try:
            dir_size = await clf_storage.prefix_size(prefix)
        except Exception as e:  # noqa: BLE001
            logger.warning("디렉토리 크기 집계 실패(run=%s): %s", run_id, e)
            dir_size = 0
        try:
            from app.core.database import async_session
            from app.imagerecog.models import RagImageRecognitionRun

            async with async_session() as s:
                s.add(RagImageRecognitionRun(
                    run_id=run_id, batch_id=batch_id, filename=filename, source_kind=kind,
                    status="extracted", extracted_count=count,
                    size_bytes=dir_size, source_url=source_url,
                    bucket=clf_storage.bucket(), prefix=prefix, created_by=created_by,
                ))
                await s.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("실행 이력 기록 실패(run=%s): %s", run_id, e)

    logger.info(
        "이미지 추출(스트림): run=%s file=%s kind=%s extracted=%d stored=%s",
        run_id, filename, kind, count, store_ok,
    )
    yield {
        "type": "done", "run_id": run_id, "total": count, "truncated": truncated,
        "source_kind": kind, "filename": filename,
    }


async def analyze_run_stream(run_id: str, indices: list[int] | None = None):
    """추출된 실행(run)의 선택 이미지를 분석하며 SSE 로 흘린다(버킷의 원본을 다시 읽어 분석).

    ``indices`` 가 비면 모든 이미지를 분석한다. 분석 결과로 manifest·실행 이력을 갱신한다.

    Raises:
        RuntimeError: 분류 비활성/모델 미설정/실행 없음/manifest 없음 등.
    """
    import json

    import httpx

    from sqlalchemy import func, select

    from app.core.config import settings
    from app.core.database import async_session
    from app.imagerecog import storage as clf_storage
    from app.imagerecog.models import RagImageRecognitionRun as R
    from app.ingestion.image_classifier import _resolve_endpoint, classify_image_bytes

    if not settings.image_classification_enabled:
        raise RuntimeError(
            "이미지 추출 및 분류가 비활성화되어 있습니다. 설정 > 이미지 추출 및 분류에서 켜고 엔드포인트를 지정하세요."
        )
    _resolve_endpoint()  # VLM 엔드포인트/모델 미설정이면 분석 전에 명확히 실패.

    async with async_session() as s:
        row = (await s.execute(select(R).where(R.run_id == run_id))).scalar_one_or_none()
    if row is None:
        raise RuntimeError("실행 이력을 찾을 수 없습니다.")
    prefix = row.prefix or f"runs/{run_id}"
    try:
        manifest = json.loads(await clf_storage.get_text(clf_storage.manifest_key(prefix)))
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("저장된 이미지 정보(manifest)를 찾을 수 없습니다.") from e

    items = manifest.get("items", [])
    sel = set(indices) if indices else {it["index"] for it in items}
    targets = [it for it in items if it["index"] in sel and it.get("original_key")]

    async def _set_status(status: str) -> None:
        try:
            async with async_session() as s2:
                r2 = (await s2.execute(select(R).where(R.run_id == run_id))).scalar_one_or_none()
                if r2:
                    r2.status = status
                    await s2.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("실행 상태 갱신 실패(run=%s): %s", run_id, e)

    await _set_status("analyzing")

    url, _model, headers, timeout = _resolve_endpoint()
    client = httpx.Client(timeout=timeout, headers=headers)
    try:
        for it in targets:
            idx = it["index"]
            yield {"type": "analyzing", "index": idx}
            try:
                raw = await clf_storage.get_bytes(it["original_key"])
                res = await asyncio.to_thread(classify_image_bytes, raw, client)
            except Exception as e:  # noqa: BLE001 — 한 장 실패가 전체를 막지 않음
                logger.warning("이미지 분석 실패(run=%s, index=%s): %s", run_id, idx, e)
                yield {"type": "item", "index": idx, "ok": False, "error": str(e)[:200]}
                continue
            it["result"] = {
                "type": res["type"], "confidence": res["confidence"],
                "summary": res["summary"], "ocr_text": res["ocr_text"], "details": res["details"],
            }
            yield {"type": "item", "index": idx, "ok": True, "result": it["result"]}
    finally:
        client.close()

    # manifest 전체 항목 기준으로 분석 수·유형 집계 재계산(재분석 시 누적 일관).
    counts: dict[str, int] = {}
    analyzed_total = 0
    for it in items:
        r = it.get("result")
        if r and r.get("type"):
            counts[r["type"]] = counts.get(r["type"], 0) + 1
            analyzed_total += 1
    manifest["counts_by_type"] = counts
    manifest["analyzed_count"] = analyzed_total
    manifest["status"] = "succeeded"
    try:
        await clf_storage.put_json(
            clf_storage.manifest_key(prefix), json.dumps(manifest, ensure_ascii=False)
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("manifest 갱신 실패(run=%s): %s", run_id, e)
    try:
        dir_size = await clf_storage.prefix_size(prefix)  # manifest 갱신으로 크기 변동 반영.
    except Exception:  # noqa: BLE001
        dir_size = None
    try:
        async with async_session() as s3:
            r3 = (await s3.execute(select(R).where(R.run_id == run_id))).scalar_one_or_none()
            if r3:
                r3.status = "succeeded"
                r3.analyzed_count = analyzed_total
                r3.counts_by_type = counts
                if dir_size is not None:
                    r3.size_bytes = dir_size
                r3.finished_at = func.now()
                await s3.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("실행 이력 마감 실패(run=%s): %s", run_id, e)

    logger.info("이미지 분석(스트림): run=%s analyzed=%d", run_id, analyzed_total)
    yield {"type": "done", "run_id": run_id, "count": analyzed_total, "counts_by_type": counts}


# ── 실행 이력 조회/삭제 ───────────────────────────────────────────────────────

def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def _run_to_list_item(r) -> dict:
    """RagImageRecognitionRun → RunListItem 호환 dict."""
    return {
        "run_id": r.run_id, "batch_id": r.batch_id, "filename": r.filename,
        "source_kind": r.source_kind, "status": r.status,
        "extracted_count": r.extracted_count, "analyzed_count": r.analyzed_count,
        "counts_by_type": r.counts_by_type or {}, "size_bytes": r.size_bytes or 0,
        "source_url": r.source_url, "error": r.error,
        "created_by": r.created_by,
        "created_at": _iso(r.created_at), "finished_at": _iso(r.finished_at),
    }


async def list_runs(session, *, page: int = 1, page_size: int = 20, batch_id: str | None = None):
    """실행 이력 목록(최신순, 페이지네이션) — (items, total)."""
    from sqlalchemy import func, select

    from app.imagerecog.models import RagImageRecognitionRun as R

    base = select(R)
    if batch_id:
        base = base.where(R.batch_id == batch_id)
    total = (await session.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()
    rows = (await session.execute(
        base.order_by(R.created_at.desc(), R.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return [_run_to_list_item(r) for r in rows], int(total)


async def get_run_detail(session, run_id: str) -> dict | None:
    """실행 1건 상세 — 메타 + 이미지별 결과. 없으면 None.

    이미지는 버킷에서 읽어 **data URL** 로 임베드한다(MinIO presigned 직접 fetch 는 내부
    엔드포인트/CORS 로 브라우저에서 실패할 수 있어, 분석 탭과 동일하게 동일출처 data URL 사용).
    """
    import json

    from sqlalchemy import select

    from app.imaging.thumbnails import to_data_url
    from app.imagerecog import storage as clf_storage
    from app.imagerecog.models import RagImageRecognitionRun as R

    row = (await session.execute(
        select(R).where(R.run_id == run_id)
    )).scalar_one_or_none()
    if row is None:
        return None

    # 저장 위치는 DB prefix 컬럼 기준({yyyy-mm-dd}/{run_id}). 구버전 행은 runs/{run_id} 폴백.
    run_pref = row.prefix or f"runs/{run_id}"
    manifest = None
    try:
        text = await clf_storage.get_text(clf_storage.manifest_key(run_pref))
        manifest = json.loads(text)
    except Exception as e:  # noqa: BLE001 — manifest 없거나 손상 시 메타만 반환
        logger.warning("manifest 로드 실패(run=%s): %s", run_id, e)

    b = row.bucket or clf_storage.bucket()
    items: list[dict] = []
    for it in (manifest or {}).get("items", []):
        orig_url = ""
        thumb_url = ""
        try:
            if it.get("thumb_key"):
                thumb_url = to_data_url(await clf_storage.get_bytes(it["thumb_key"]))
            if it.get("original_key"):
                orig_url = to_data_url(await clf_storage.get_bytes(it["original_key"]))
        except Exception as e:  # noqa: BLE001 — 한 장 로드 실패는 건너뜀
            logger.warning("이미지 로드 실패(run=%s, index=%s): %s", run_id, it.get("index"), e)
        res = it.get("result") or {}
        items.append({
            "index": it.get("index", 0), "page": it.get("page"),
            "locator": it.get("locator", ""),
            "width": it.get("width", 0), "height": it.get("height", 0),
            "original_url": orig_url, "thumb_url": thumb_url,
            "type": res.get("type", ""), "confidence": res.get("confidence", 0.0),
            "summary": res.get("summary", ""), "ocr_text": res.get("ocr_text", ""),
            "details": res.get("details", ""),
        })

    # 업로드 원본 파일이 있으면 동일출처 프록시 경로를 노출(프런트가 authFetch→blob 로 다운로드).
    source_download_url = (
        f"/api/v1/image-recognition/runs/{run_id}/source"
        if (manifest or {}).get("source_key")
        else ""
    )

    detail = _run_to_list_item(row)  # source_url(=원본 페이지 URL) 등 메타 유지
    detail["truncated"] = bool((manifest or {}).get("truncated", False))
    detail["items"] = items
    detail["source_download_url"] = source_download_url
    detail["source_filename"] = (manifest or {}).get("source_filename") or row.filename
    return detail


async def get_run_source(session, run_id: str) -> tuple[bytes, str | None, str] | None:
    """업로드 원본 파일 바이트를 반환한다 — (bytes, content_type, filename). 없으면 None."""
    import json

    from sqlalchemy import select

    from app.imagerecog import storage as clf_storage
    from app.imagerecog.models import RagImageRecognitionRun as R

    row = (await session.execute(
        select(R).where(R.run_id == run_id)
    )).scalar_one_or_none()
    if row is None:
        return None
    run_pref = row.prefix or f"runs/{run_id}"
    try:
        manifest = json.loads(await clf_storage.get_text(clf_storage.manifest_key(run_pref)))
    except Exception:  # noqa: BLE001
        return None
    sk = manifest.get("source_key")
    if not sk:
        return None
    try:
        data = await clf_storage.get_bytes(sk)
    except Exception as e:  # noqa: BLE001
        logger.warning("원본 파일 로드 실패(run=%s): %s", run_id, e)
        return None
    return data, manifest.get("source_content_type"), manifest.get("source_filename") or row.filename


async def delete_run_images(session, run_id: str, indices: list[int]) -> dict | None:
    """실행에서 선택한 이미지(인덱스)만 삭제한다 — 버킷 객체 + manifest 항목 제거 후 카운트 재계산.

    반환: ``{"deleted": n, "remaining": m}``. 실행/안전 검증 실패 시 None.
    """
    import json

    from sqlalchemy import select

    from app.imagerecog import storage as clf_storage
    from app.imagerecog.models import RagImageRecognitionRun as R

    if not indices:
        return None
    row = (await session.execute(select(R).where(R.run_id == run_id))).scalar_one_or_none()
    if row is None:
        return None
    prefix = row.prefix or f"runs/{run_id}"
    try:
        manifest = json.loads(await clf_storage.get_text(clf_storage.manifest_key(prefix)))
    except Exception as e:  # noqa: BLE001
        logger.warning("manifest 로드 실패(run=%s): %s", run_id, e)
        return None

    sel = set(indices)
    items = manifest.get("items", [])
    to_delete = [it for it in items if it.get("index") in sel]
    keys: list[str] = []
    for it in to_delete:
        if it.get("original_key"):
            keys.append(it["original_key"])
        if it.get("thumb_key"):
            keys.append(it["thumb_key"])
    try:
        await clf_storage.delete_objects(keys)
    except Exception as e:  # noqa: BLE001 — 객체 삭제 실패해도 manifest/DB 는 정리
        logger.warning("이미지 객체 삭제 실패(run=%s): %s", run_id, e)

    remaining = [it for it in items if it.get("index") not in sel]
    counts: dict[str, int] = {}
    analyzed = 0
    for it in remaining:
        r = it.get("result")
        if r and r.get("type"):
            counts[r["type"]] = counts.get(r["type"], 0) + 1
            analyzed += 1
    manifest["items"] = remaining
    manifest["extracted_count"] = len(remaining)
    manifest["analyzed_count"] = analyzed
    manifest["counts_by_type"] = counts
    try:
        await clf_storage.put_json(
            clf_storage.manifest_key(prefix), json.dumps(manifest, ensure_ascii=False)
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("manifest 갱신 실패(run=%s): %s", run_id, e)

    try:
        dir_size = await clf_storage.prefix_size(prefix)  # 삭제 반영된 실제 크기.
    except Exception:  # noqa: BLE001
        dir_size = None

    row.extracted_count = len(remaining)
    row.analyzed_count = analyzed
    row.counts_by_type = counts
    if dir_size is not None:
        row.size_bytes = dir_size
    await session.commit()
    return {"deleted": len(to_delete), "remaining": len(remaining)}


async def delete_run(session, run_id: str) -> bool:
    """실행 1건 삭제 — 분류 버킷 prefix + DB row 제거. 없으면 False."""
    from sqlalchemy import select

    from app.imagerecog import storage as clf_storage
    from app.imagerecog.models import RagImageRecognitionRun as R

    row = (await session.execute(
        select(R).where(R.run_id == run_id)
    )).scalar_one_or_none()
    if row is None:
        return False
    # 저장 위치는 DB prefix 컬럼에 보관됨({yyyy-mm-dd}/{run_id}). 구버전 행은 runs/{run_id} 폴백.
    prefix = (row.prefix or f"runs/{run_id}").rstrip("/")
    try:
        await clf_storage.delete_prefix(prefix + "/")
    except Exception as e:  # noqa: BLE001 — 버킷 객체 삭제 실패해도 DB 행은 정리
        logger.warning("분류 버킷 객체 삭제 실패(run=%s): %s", run_id, e)
    await session.delete(row)
    await session.commit()
    return True
