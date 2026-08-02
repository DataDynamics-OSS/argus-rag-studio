# SPDX-License-Identifier: Apache-2.0
"""어노테이션(Annotation) 서비스(비즈니스 로직 계층).

이미지 등록·조회·메타 갱신·박스 일괄 교체를 담당한다. 좌표 변환/직렬화는
``app.annotations.aihub`` 가, 오브젝트 스토리지 입출력은 ``app.storage.client`` 가 맡는다.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations import aihub, storage
from app.annotations.models import AnnotationBox, AnnotationImage
from app.annotations.schemas import (
    AnnotationDetailResponse,
    AnnotationImageResponse,
    BoxItem,
    PaginatedImagesResponse,
)

logger = logging.getLogger(__name__)


def build_object_key(folder: str | None, filename: str) -> str:
    """오브젝트 키 규칙: ``{folder}/{filename}`` (어노테이션 버킷, 폴더 탐색기 기준)."""
    return storage.build_key(folder, filename)


async def _box_count(session: AsyncSession, image_db_id: int) -> int:
    return (await session.execute(
        select(func.count()).select_from(AnnotationBox)
        .where(AnnotationBox.image_id == image_db_id)
    )).scalar() or 0


def _to_response(img: AnnotationImage, box_count: int = 0) -> AnnotationImageResponse:
    return AnnotationImageResponse(
        id=img.id,
        image_id=img.image_id,
        collection_id=img.collection_id,
        filename=img.filename,
        folder=img.folder,
        source_uri=img.source_uri,
        content_type=img.content_type,
        content_hash=img.content_hash,
        width=img.width,
        height=img.height,
        size_bytes=img.size_bytes,
        status=img.status,
        has_thumbnail=bool(img.thumb_uri),
        meta=img.meta_json,
        box_count=box_count,
        created_by=img.created_by,
        created_at=img.created_at,
        updated_at=img.updated_at,
    )


async def find_image_by_hash(
    session: AsyncSession, content_hash: str
) -> AnnotationImage | None:
    return (await session.execute(
        select(AnnotationImage).where(AnnotationImage.content_hash == content_hash)
    )).scalars().first()


async def find_image_by_folder_name(
    session: AsyncSession, folder: str, filename: str
) -> AnnotationImage | None:
    """동일 폴더 내 같은 파일명 이미지(탐색기 충돌 검사용)."""
    return (await session.execute(
        select(AnnotationImage).where(
            AnnotationImage.folder == storage.norm_folder(folder),
            AnnotationImage.filename == filename,
        )
    )).scalars().first()


async def create_image(
    session: AsyncSession,
    *,
    filename: str,
    source_uri: str | None,
    content_type: str | None,
    content_hash: str | None,
    width: int,
    height: int,
    size_bytes: int,
    collection_id: int | None,
    created_by: str | None,
    folder: str = "",
) -> AnnotationImage:
    """이미지를 등록한다(상태 ``draft``). 기본 메타 블록을 채워 둔다."""
    meta = aihub.default_meta()
    img = AnnotationImage(
        image_id=str(uuid.uuid4()),
        collection_id=collection_id,
        filename=filename,
        folder=storage.norm_folder(folder),
        source_uri=source_uri,
        content_type=content_type,
        content_hash=content_hash,
        width=width,
        height=height,
        size_bytes=size_bytes,
        status="draft",
        meta_json=meta,
        created_by=created_by,
    )
    session.add(img)
    await session.commit()
    await session.refresh(img)
    logger.info("어노테이션 이미지 등록: %s (id=%d)", img.filename, img.id)
    return img


async def get_image(session: AsyncSession, image_uuid: str) -> AnnotationImage | None:
    return (await session.execute(
        select(AnnotationImage).where(AnnotationImage.image_id == image_uuid)
    )).scalars().first()


async def get_detail(
    session: AsyncSession, img: AnnotationImage
) -> AnnotationDetailResponse:
    rows = (await session.execute(
        select(AnnotationBox).where(AnnotationBox.image_id == img.id)
        .order_by(AnnotationBox.seq)
    )).scalars().all()
    boxes = [
        BoxItem(seq=b.seq, data=b.data, x1=b.x1, y1=b.y1, x2=b.x2, y2=b.y2)
        for b in rows
    ]
    base = _to_response(img, box_count=len(boxes))
    return AnnotationDetailResponse(**base.model_dump(), boxes=boxes)


# 그리드에 미리보기로 노출할 이미지 확장자(읽기전용 오브젝트 판별).
_IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)


def _object_to_response(folder: str, key: str, name: str) -> AnnotationImageResponse:
    """DB 미등록 S3 이미지 오브젝트(예: 분할 크롭) → 읽기전용 그리드 항목."""
    return AnnotationImageResponse(
        id=0,
        image_id=key,           # React key/식별자로 오브젝트 키를 그대로 사용
        collection_id=None,
        filename=name,
        folder=storage.norm_folder(folder),
        source_uri=storage.build_source_uri(key),
        content_type=None,
        content_hash=None,
        width=0,
        height=0,
        size_bytes=0,
        status="",
        has_thumbnail=False,
        meta=None,
        box_count=0,
        created_by=None,
        created_at=_EPOCH,
        updated_at=_EPOCH,
        readonly=True,
        object_key=key,
    )


async def _folder_object_items(
    session: AsyncSession, folder: str, search: str | None
) -> list[AnnotationImageResponse]:
    """해당 폴더에 직접 들어있는, DB 미등록 이미지 오브젝트(읽기전용)를 나열한다.

    하위 폴더의 객체·썸네일·라벨 JSON·폴더 마커는 제외하고, DB 에 등록된 이미지(같은 키)는 dedupe.
    """
    norm = storage.norm_folder(folder)
    seg = f"{norm}/" if norm else ""

    # 이 폴더의 DB 이미지 파일명 → 키 집합(dedupe 용)
    names = (await session.execute(
        select(AnnotationImage.filename).where(AnnotationImage.folder == norm)
    )).scalars().all()
    db_keys = {build_object_key(norm, n) for n in names}

    keys = await storage.list_direct_object_keys(norm)
    out: list[AnnotationImageResponse] = []
    for key in keys:
        rest = key[len(seg):] if seg else key
        if not rest or "/" in rest:
            continue  # 폴더 마커 또는 하위 폴더 객체
        low = rest.lower()
        if "_thumbnail." in low or not low.endswith(_IMG_EXTS):
            continue  # 썸네일·JSONL·JSON 등 비대상
        if key in db_keys:
            continue  # DB 등록 이미지는 정식 항목으로 따로 나옴
        if search and search.lower() not in rest.lower():
            continue
        out.append(_object_to_response(norm, key, rest))
    out.sort(key=lambda r: r.filename)
    return out


async def list_images(
    session: AsyncSession,
    *,
    status: str | None = None,
    collection_id: int | None = None,
    search: str | None = None,
    folder: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedImagesResponse:
    base = select(AnnotationImage)
    if status:
        base = base.where(AnnotationImage.status == status)
    if collection_id is not None:
        base = base.where(AnnotationImage.collection_id == collection_id)
    if search:
        base = base.where(AnnotationImage.filename.ilike(f"%{search}%"))
    # folder 가 주어지면 정확히 그 폴더의 이미지만(루트는 ""). None 이면 전체(평면 목록).
    if folder is not None:
        base = base.where(AnnotationImage.folder == storage.norm_folder(folder))

    total_db = (await session.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar() or 0

    # 특정 폴더를 볼 때만 DB 미등록 이미지 오브젝트(분할 크롭 등)를 읽기전용으로 합친다.
    # 상태/컬렉션 필터가 걸린 목록은 라벨링 대상 전용이므로 제외.
    objects: list[AnnotationImageResponse] = []
    if folder is not None and status is None and collection_id is None:
        objects = await _folder_object_items(session, folder, search)
    total = total_db + len(objects)

    # 페이지 윈도우 — DB 이미지(앞) → 읽기전용 오브젝트(뒤) 순서로 정렬되어 있다고 보고 슬라이스.
    win_start = (page - 1) * page_size if page_size > 0 else 0
    win_end = win_start + page_size if page_size > 0 else total

    items: list[AnnotationImageResponse] = []
    db_lo, db_hi = max(win_start, 0), min(win_end, total_db)
    if db_hi > db_lo:
        query = base.order_by(AnnotationImage.created_at.desc()).offset(db_lo).limit(db_hi - db_lo)
        images = (await session.execute(query)).scalars().all()
        counts: dict[int, int] = {}
        if images:
            ids = [i.id for i in images]
            rows = (await session.execute(
                select(AnnotationBox.image_id, func.count())
                .where(AnnotationBox.image_id.in_(ids))
                .group_by(AnnotationBox.image_id)
            )).all()
            counts = {img_id: cnt for img_id, cnt in rows}
        items.extend(_to_response(i, box_count=counts.get(i.id, 0)) for i in images)

    obj_lo, obj_hi = max(win_start - total_db, 0), min(win_end - total_db, len(objects))
    if obj_hi > obj_lo:
        items.extend(objects[obj_lo:obj_hi])

    return PaginatedImagesResponse(items=items, total=total, page=page, page_size=page_size)


async def update_image(
    session: AsyncSession,
    img: AnnotationImage,
    *,
    status: str | None = None,
    collection_id: int | None = None,
    meta: dict | None = None,
    set_collection: bool = False,
) -> AnnotationImage:
    """이미지 상태/컬렉션/메타 부분 갱신.

    ``set_collection`` 이 True 면 ``collection_id`` 를 (None 포함) 명시적으로 덮어쓴다.
    """
    if status is not None:
        img.status = status
    if set_collection:
        img.collection_id = collection_id
    if meta is not None:
        img.meta_json = meta
    await session.commit()
    await session.refresh(img)
    # 라벨 JSON 사이드카 동기화 — "완료" 로 전환되면 이미지 옆에 저장하고, 완료에서
    # 다른 상태로 되돌리면 낡은 사이드카를 삭제한다(DB 가 진실의 원천이라 재생성 가능).
    if status == "completed":
        await write_label_json(session, img)
    elif status is not None:
        await delete_label_json(img)
    return img


async def write_label_json(session: AsyncSession, img: AnnotationImage) -> str | None:
    """이미지와 같은 위치에 AI-Hub 라벨 JSON 사이드카를 저장한다(확장자만 .json).

    원본 이미지가 오브젝트 스토리지에 없으면(가져오기로 만든 메타 전용 레코드 등) 건너뛴다.
    사이드카 저장 실패가 상태 갱신/응답을 막지 않도록 예외는 로깅 후 삼킨다."""
    if not img.source_uri:
        return None
    try:
        boxes = await get_boxes(session, img.id)
        payload = aihub.build_export(
            filename=img.filename, width=img.width, height=img.height,
            meta=img.meta_json, boxes=boxes,
        )
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        key = storage.build_json_key(img.folder, img.filename)
        return await storage.put_json(key, body)
    except Exception as e:  # noqa: BLE001 — 사이드카 저장은 best-effort
        logger.warning("라벨 JSON 사이드카 저장 실패(무시): image_id=%s (%s)", img.image_id, e)
        return None


async def delete_label_json(img: AnnotationImage) -> None:
    """완료에서 다른 상태로 되돌릴 때 이미지 옆 라벨 JSON 사이드카를 제거한다.

    완료된 적이 없어 사이드카가 없을 수도 있으므로 best-effort(없으면 무시)로 처리한다."""
    if not img.source_uri:
        return
    key = storage.build_json_key(img.folder, img.filename)
    try:
        await storage.delete_object(key)
        logger.info("라벨 JSON 사이드카 삭제: %s", key)
    except Exception as e:  # noqa: BLE001 — 사이드카 정리는 best-effort
        logger.warning("라벨 JSON 사이드카 삭제 실패(무시): image_id=%s (%s)", img.image_id, e)


async def replace_boxes(
    session: AsyncSession, img: AnnotationImage, boxes: list[BoxItem]
) -> int:
    """이미지의 박스 전체를 일괄 교체한다(멱등). 교체된 박스 수를 반환."""
    await session.execute(
        delete(AnnotationBox).where(AnnotationBox.image_id == img.id)
    )
    for b in boxes:
        session.add(AnnotationBox(
            image_id=img.id, seq=b.seq, data=b.data,
            x1=b.x1, y1=b.y1, x2=b.x2, y2=b.y2,
        ))
    # draft 였다면 작업 시작 상태로 승격
    if img.status == "draft" and boxes:
        img.status = "in_progress"
    await session.commit()
    logger.info("어노테이션 박스 교체: image_id=%d count=%d", img.id, len(boxes))
    return len(boxes)


async def set_thumbnail(
    session: AsyncSession, img: AnnotationImage, data: bytes, content_type: str | None
) -> AnnotationImage:
    """썸네일 객체를 어노테이션 버킷에 저장하고 ``thumb_uri`` 를 갱신한다."""
    key = storage.build_thumb_key(img.folder, img.filename, content_type)
    img.thumb_uri = await storage.put_image(key, data, content_type=content_type)
    await session.commit()
    await session.refresh(img)
    logger.info("어노테이션 썸네일 생성: %s", key)
    return img


async def delete_image(session: AsyncSession, img: AnnotationImage) -> None:
    key = storage.build_key(img.folder, img.filename)
    json_key = storage.build_json_key(img.folder, img.filename)  # 완료 시 만든 라벨 사이드카
    thumb_uri = img.thumb_uri
    await session.delete(img)
    await session.commit()
    for target in (key, json_key, thumb_uri):
        if not target:
            continue
        try:
            # thumb_uri 는 s3://.../key 형식 → key 만 추출
            obj_key = target.split("/", 3)[-1] if target.startswith("s3://") else target
            await storage.delete_object(obj_key)
        except Exception as e:  # noqa: BLE001 — S3 정리는 best-effort
            logger.warning("어노테이션 S3 객체 삭제 실패(무시): %s (%s)", target, e)
    logger.info("어노테이션 이미지 삭제: %s (id=%d)", img.filename, img.id)


# ── 폴더(가상 디렉터리) ────────────────────────────────────────────────────

async def list_child_folders(parent: str | None) -> list[str]:
    """parent 바로 아래 자식 폴더 경로 목록(S3 prefix 기준, 루트 기준 전체 경로)."""
    return await storage.list_folders(parent)


async def create_folder(path: str) -> None:
    await storage.create_folder(path)


async def delete_folder(session: AsyncSession, path: str) -> int:
    """폴더(하위 포함) 삭제 — DB 이미지·박스(FK CASCADE) + S3 객체 제거. 삭제 이미지 수 반환."""
    folder = storage.norm_folder(path)
    imgs = (await session.execute(
        select(AnnotationImage).where(
            (AnnotationImage.folder == folder)
            | (AnnotationImage.folder.like(f"{folder}/%"))
        )
    )).scalars().all()
    for im in imgs:
        await session.delete(im)
    await session.commit()
    try:
        await storage.delete_prefix(folder)
    except Exception as e:  # noqa: BLE001 — S3 정리는 best-effort
        logger.warning("어노테이션 폴더 S3 삭제 실패(무시): %s (%s)", folder, e)
    logger.info("어노테이션 폴더 삭제: %s (images=%d)", folder, len(imgs))
    return len(imgs)


async def get_boxes(session: AsyncSession, image_db_id: int) -> list[AnnotationBox]:
    return list((await session.execute(
        select(AnnotationBox).where(AnnotationBox.image_id == image_db_id)
        .order_by(AnnotationBox.seq)
    )).scalars().all())
