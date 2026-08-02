# SPDX-License-Identifier: Apache-2.0
"""이미지 썸네일(다운스케일) + data URL 유틸 — 휘발성 미리보기용(S3 미사용)."""

import base64
import io


def make_thumbnail(png: bytes, max_px: int = 320) -> bytes:
    """PNG 를 긴 변 ``max_px`` 이하로 축소한 PNG 바이트로 만든다. 실패 시 원본 반환."""
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(png)).convert("RGB")
        img.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001 — 축소 실패 시 원본을 그대로 사용
        return png


def to_data_url(png: bytes) -> str:
    """PNG 바이트 → ``data:image/png;base64,…`` data URL(프런트 <img> 직접 표시용)."""
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
