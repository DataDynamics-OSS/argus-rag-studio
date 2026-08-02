# SPDX-License-Identifier: Apache-2.0
"""기존 어노테이션 이미지에 썸네일을 일괄 생성(백필).

런타임 썸네일은 클라이언트(canvas)에서 만들지만, 이 기능 도입 이전에 업로드된 이미지는
썸네일이 없다. 이 스크립트는 ``thumb_uri`` 가 비어 있는 이미지의 원본을 읽어 Pillow 로
축소한 JPEG 썸네일(긴 변 320px, 흰 배경)을 어노테이션 버킷에 저장하고 ``thumb_uri`` 를
갱신한다. 파일명 규칙은 런타임과 동일(``{원본명}_thumbnail.jpg``).

사용법(backend 디렉터리에서):
    ARGUS_RAG_STUDIO_SERVER_CONFIG_DIR=packaging/config \\
        ./.venv/bin/python -m scripts.backfill_thumbnails [옵션]

옵션:
    --force        이미 썸네일이 있는 이미지도 다시 생성(덮어쓰기)
    --limit N      최대 N개만 처리
    --dry-run      실제 저장 없이 대상만 출력
"""

import argparse
import asyncio
import io
import logging

from PIL import Image
from sqlalchemy import select

import app.collections.models  # noqa: F401 — annotation_images.collection_id FK 대상 테이블 등록
from app.annotations import storage
from app.annotations.models import AnnotationImage
from app.core.database import async_session
from app.storage.client import get_object

MAX_SIZE = 320  # 썸네일 긴 변(px) — 클라이언트와 동일
QUALITY = 85

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill_thumbnails")


def make_thumbnail(data: bytes) -> bytes:
    """원본 이미지 바이트 → 축소 JPEG 썸네일 바이트(투명 배경은 흰색 합성)."""
    img = Image.open(io.BytesIO(data))
    img.thumbnail((MAX_SIZE, MAX_SIZE))
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=QUALITY)
    return out.getvalue()


async def run(*, force: bool, limit: int | None, dry_run: bool) -> None:
    async with async_session() as session:
        q = select(AnnotationImage).where(AnnotationImage.source_uri.isnot(None))
        if not force:
            q = q.where(AnnotationImage.thumb_uri.is_(None))
        q = q.order_by(AnnotationImage.id)
        if limit:
            q = q.limit(limit)
        images = (await session.execute(q)).scalars().all()

    logger.info("대상 이미지: %d개%s%s", len(images), " (force)" if force else "", " (dry-run)" if dry_run else "")
    ok = fail = 0
    for img in images:
        key = storage.build_thumb_key(img.folder, img.filename, "image/jpeg")
        if dry_run:
            logger.info("[dry-run] %s -> %s", img.filename, key)
            continue
        try:
            data = await get_object(img.source_uri)
            thumb = make_thumbnail(data)
            uri = await storage.put_image(key, thumb, content_type="image/jpeg")
            async with async_session() as s2:
                row = await s2.get(AnnotationImage, img.id)
                if row:
                    row.thumb_uri = uri
                    await s2.commit()
            ok += 1
            logger.info("OK   %s -> %s", img.filename, key)
        except Exception as e:  # noqa: BLE001 — 한 건 실패가 전체를 막지 않게
            fail += 1
            logger.warning("FAIL %s (%s)", img.filename, e)

    logger.info("완료 — 생성 %d / 실패 %d / 전체 %d", ok, fail, len(images))


def main() -> None:
    parser = argparse.ArgumentParser(description="어노테이션 이미지 썸네일 일괄 백필")
    parser.add_argument("--force", action="store_true", help="기존 썸네일도 재생성")
    parser.add_argument("--limit", type=int, default=None, help="최대 처리 개수")
    parser.add_argument("--dry-run", action="store_true", help="저장 없이 대상만 출력")
    args = parser.parse_args()
    asyncio.run(run(force=args.force, limit=args.limit, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
