# SPDX-License-Identifier: Apache-2.0
"""어노테이션 자동 bbox 인식 — 외부 검출 서버(PaddleOCR) 클라이언트.

편집기의 '자동 인식'이 이미지의 텍스트 영역 bbox(+인식 텍스트)를 받아 후보 박스로
채운다. 검출 결과는 확정이 아니라 초안이며 사람이 검수·수정한다(human-in-the-loop).

검출 서버 계약: ``POST {server_url}/v1/detect`` (멀티파트 file/lang/min_score/with_text)
→ ``{"boxes": [{x1,y1,x2,y2,text,score}], "width", "height"}``.
"""

import logging

import httpx

from app.core.config import settings
from app.core.http import auth_headers

logger = logging.getLogger(__name__)


class DetectionError(RuntimeError):
    """검출 비활성/연결 실패/서버 오류 — 라우터에서 503 으로 변환한다."""


async def detect_boxes(
    image: bytes,
    content_type: str | None,
    *,
    lang: str | None = None,
    min_score: float | None = None,
    with_text: bool = True,
) -> list[dict]:
    """검출 서버를 호출해 후보 박스 목록을 반환한다.

    각 박스는 ``{"x1","y1","x2","y2","text","score"}``(원본 픽셀 좌표)다.
    검출이 비활성이거나 서버 호출이 실패하면 ``DetectionError`` 를 던진다."""
    if not settings.detection_enabled:
        raise DetectionError("자동 인식 기능이 비활성화되어 있습니다(detection.enabled=false).")

    url = settings.detection_server_url.rstrip("/") + "/v1/detect"
    headers = auth_headers(
        settings.detection_api_key,
        settings.detection_auth_header,
        settings.detection_auth_scheme,
    )
    files = {"file": ("image", image, content_type or "application/octet-stream")}
    data = {
        "lang": lang or settings.detection_lang,
        "min_score": str(min_score if min_score is not None else settings.detection_min_score),
        "with_text": "true" if with_text else "false",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.detection_timeout, headers=headers) as client:
            resp = await client.post(url, files=files, data=data)
    except httpx.HTTPError as e:
        raise DetectionError(f"검출 서버 연결 실패: {e} @ {url}") from e

    if resp.status_code != 200:
        raise DetectionError(f"검출 서버 오류({resp.status_code}): {resp.text[:200]} @ {url}")

    payload = resp.json()
    boxes = payload.get("boxes") if isinstance(payload, dict) else None
    return boxes or []
