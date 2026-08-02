# SPDX-License-Identifier: Apache-2.0
"""이미지 분할(bbox 크롭) — 각 박스를 잘라 학습용 크롭 이미지 + manifest(JSONL)로 만든다.

저장은 호출 측(router)이 담당한다. 이 모듈은 순수(블로킹 CPU) 함수만 제공한다:
원본 이미지 바이트 + 박스 목록 → 크롭 PNG 바이트 목록, 그리고 그로부터 JSONL 문자열 생성.

산출물은 원본 이미지가 있는 오브젝트 스토리지(MinIO)의 ``{이미지폴더}/{파일명stem}/`` 아래에
나란히 저장된다::

    {folder}/{stem}/{stem}_{seq}.png   크롭 PNG
    {folder}/{stem}/aihub_crops.jsonl  단순 manifest
    {folder}/{stem}/aihub_crops_sft.jsonl  ERNIE SFT 학습용

JSONL 의 이미지 경로는 크롭 PNG 와 **같은 디렉터리**라서 파일명(basename)만 적는다.
디렉터리째 내려받으면 manifest 와 이미지가 그대로 맞물린다.

참고 구현: PaddleOCR-VL-1.6-FT/scripts/crop_aihub_regions.py
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from io import BytesIO
from typing import Iterable

from PIL import Image

# 크롭 디렉터리 안의 manifest 파일명.
MANIFEST_NAME = "aihub_crops.jsonl"
SFT_NAME = "aihub_crops_sft.jsonl"

# 크롭 파라미터 — crop_aihub_regions.py 기본값과 동일.
DEFAULT_PAD = 3          # 박스 주변 여백(px)
DEFAULT_MIN_SIZE = 8     # 가로·세로가 이보다 작은 크롭은 건너뜀
DEFAULT_MIN_TEXT_LEN = 1  # 텍스트가 이보다 짧으면 건너뜀


@dataclass(frozen=True)
class CropBox:
    """크롭에 필요한 박스 값(ORM 비의존 평범한 값 객체).

    ORM(AnnotationBox)을 워커 스레드로 넘기면 lazy 속성 접근이 비동기 IO 를 유발해
    ``MissingGreenlet`` 이 나므로, async 컨텍스트에서 이 객체로 미리 복사해 전달한다.
    """

    seq: int
    data: str
    x1: int
    y1: int
    x2: int
    y2: int

    @classmethod
    def from_orm(cls, b) -> "CropBox":
        return cls(seq=b.seq, data=b.data or "", x1=b.x1, y1=b.y1, x2=b.x2, y2=b.y2)


@dataclass(frozen=True)
class RenderedCrop:
    """잘라낸 크롭 1개 — 파일명/텍스트/PNG 바이트."""

    filename: str
    text: str
    png: bytes


def render_crops(
    image_bytes: bytes,
    boxes: Iterable[CropBox],
    stem: str,
    *,
    pad: int = DEFAULT_PAD,
    min_size: int = DEFAULT_MIN_SIZE,
    min_text_len: int = DEFAULT_MIN_TEXT_LEN,
) -> tuple[list[RenderedCrop], int]:
    """원본 이미지에서 박스마다 크롭 PNG 를 만든다.

    반환: (크롭 목록, 건너뛴 박스 수). 동기(블로킹) 함수 — asyncio.to_thread 로 감싼다.
    텍스트가 비었거나 너무 작은 크롭은 건너뛴다.
    """
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    width, height = img.size

    out: list[RenderedCrop] = []
    skipped = 0
    for b in boxes:
        text = (b.data or "").strip()
        if len(text) < min_text_len:
            skipped += 1
            continue
        x0 = max(0, min(b.x1, b.x2) - pad)
        y0 = max(0, min(b.y1, b.y2) - pad)
        x1 = min(width, max(b.x1, b.x2) + pad)
        y1 = min(height, max(b.y1, b.y2) + pad)
        if (x1 - x0) < min_size or (y1 - y0) < min_size:
            skipped += 1
            continue
        buf = BytesIO()
        img.crop((x0, y0, x1, y1)).save(buf, "PNG")
        out.append(RenderedCrop(filename=f"{stem}_{b.seq}.png", text=text, png=buf.getvalue()))

    return out, skipped


def build_jsonl(crops: Iterable[RenderedCrop], *, sft: bool) -> str:
    """크롭 목록 → JSONL 문자열. 이미지 경로는 colocated 파일명(basename)만 기록."""
    lines: list[str] = []
    for c in crops:
        if sft:
            rec = {
                "image_info": [{"matched_text_index": 0, "image_url": c.filename}],
                "text_info": [
                    {"text": "OCR:", "tag": "mask"},
                    {"text": c.text, "tag": "no_mask"},
                ],
            }
        else:
            rec = {"image": c.filename, "text": c.text}
        lines.append(json.dumps(rec, ensure_ascii=False))
    return ("\n".join(lines) + "\n") if lines else ""


def is_crop_filename(name: str, stem: str) -> bool:
    """파일명이 이 stem 의 크롭(``{stem}_<숫자>.png``)인지 — 고아 크롭 정리에 사용."""
    return re.match(rf"^{re.escape(stem)}_\d+\.png$", name or "") is not None
