# SPDX-License-Identifier: Apache-2.0
"""검색 근거 페이지 — HWP/HWPX 원본의 해당 페이지를 보여주기 위한 렌더/매칭.

HWP/HWPX 는 LibreOffice 가 못 여는 경우가 많아, 헤드리스 브라우저 @rhwp/core 렌더 서비스
(extensions/hwp_render_server)로 페이지 텍스트/이미지를 얻는다. 청크 텍스트를 페이지 텍스트와
매칭해 "이 청크가 원본 몇 페이지" 를 추정한다.
"""

import base64
import logging
import re
from collections import OrderedDict

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

HWP_EXTS = (".hwp", ".hwpx")
_TIMEOUT = 120.0
# content_hash → {"page_count","page_texts"} 캐시(페이지 텍스트는 재요청 비용 절감).
_TEXT_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_TEXT_CACHE_MAX = 64


def is_hwp(name: str | None) -> bool:
    return bool(name) and name.lower().endswith(HWP_EXTS)


def available() -> bool:
    return bool(settings.hwp_render_url)


def _norm(s: str) -> str:
    """매칭용 정규화 — 한글·영숫자만 남기고 공백 제거."""
    return re.sub(r"[^0-9A-Za-z가-힣]", "", s or "")


def best_page(chunk_text: str, page_texts: list[str]) -> int:
    """청크 텍스트와 가장 겹치는 페이지(1-base). char 5-gram 중첩 수로 점수화."""
    cn = _norm(chunk_text)
    if not cn or not page_texts:
        return 1
    grams = {cn[i:i + 5] for i in range(0, max(1, len(cn) - 4))}
    if not grams:
        return 1
    best_i, best_score = 0, -1
    for i, pt in enumerate(page_texts):
        pn = _norm(pt)
        score = sum(1 for g in grams if g in pn)
        if score > best_score:
            best_i, best_score = i, score
    return best_i + 1


async def pages_text(content_hash: str, data: bytes) -> dict:
    """렌더 서비스에서 페이지 수 + 페이지별 텍스트(매칭용). content_hash 로 캐시."""
    if content_hash in _TEXT_CACHE:
        _TEXT_CACHE.move_to_end(content_hash)
        return _TEXT_CACHE[content_hash]
    b64 = base64.b64encode(data).decode("ascii")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{settings.hwp_render_url.rstrip('/')}/pages-text", json={"data_b64": b64})
        resp.raise_for_status()
        out = resp.json()
    _TEXT_CACHE[content_hash] = out
    _TEXT_CACHE.move_to_end(content_hash)
    while len(_TEXT_CACHE) > _TEXT_CACHE_MAX:
        _TEXT_CACHE.popitem(last=False)
    return out


async def render_page(data: bytes, page: int, scale: float = 1.5) -> bytes:
    """렌더 서비스에서 특정 페이지(1-base)를 PNG 로 받는다."""
    b64 = base64.b64encode(data).decode("ascii")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{settings.hwp_render_url.rstrip('/')}/render",
            json={"data_b64": b64, "page": max(0, page - 1), "scale": scale},
        )
        resp.raise_for_status()
        return base64.b64decode(resp.json()["image_b64"])
