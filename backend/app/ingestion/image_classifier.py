# SPDX-License-Identifier: Apache-2.0
"""문서 이미지 분류 — 비전 LLM(VLM)으로 이미지 유형(도표/차트/사진 등)을 식별.

설정(``image_classification.*``)이 켜져 있을 때만 동작한다. 인제스천 파이프라인의 파싱
단계와 별개로(best-effort), 문서에서 임베디드 이미지를 추출해 OpenAI 호환 비전
엔드포인트(``/chat/completions``)로 각 이미지를 분류한다. ``_parse_vlm`` 과 동일한 호출
패턴을 쓰며, 엔드포인트/모델은 ``image_classification.*`` → (비어 있으면) ``llm.*`` 로 폴백한다.

전용 vLLM(예: Qwen2.5-VL) 엔드포인트를 ``image_classification.server_url`` 로 지정하면
생성 LLM 과 분리해 운용할 수 있다. 결과는 ``{type, confidence, summary}`` JSON 이며,
분류 실패/엔드포인트 오류는 인제스천을 막지 않는다(호출 측에서 무시).
"""

import base64
import io
import json
import logging
import re

logger = logging.getLogger(__name__)

# 카테고리 정의(두 프롬프트 공용) — 유형 판별 기준.
_CATEGORY_GUIDE = (
    "차트는 막대/선/원 등 데이터 시각화, table 은 표/도표, diagram 은 흐름도/구조도/모식도, "
    "photo 는 사진, screenshot 은 화면 캡처, formula 는 수식, logo 는 로고를 뜻한다."
)

# 경량 모드 — 유형 + 한 줄 요약(content_analysis=False).
_PROMPT_BASIC = (
    "이 이미지의 유형을 다음 중 하나로 정확히 분류하라: {categories}. "
    + _CATEGORY_GUIDE
    + " 반드시 JSON 객체 하나만 출력하라(코드펜스·설명 금지): "
    '{{"type": "<카테고리>", "confidence": <0~1 사이 숫자>, "summary": "<이미지 내용 한 줄 요약>"}}'
)

# 심층 모드 — 유형 + 상세 설명 + OCR 텍스트 + 표/수식 구조화(content_analysis=True).
_PROMPT_DEEP = (
    "이 이미지를 분석하라. "
    "(1) 유형을 다음 중 하나로 정확히 분류: {categories}. " + _CATEGORY_GUIDE + " "
    "(2) 이미지의 내용을 2~4문장으로 구체적으로 설명(무엇을 나타내며 핵심 정보가 무엇인지). "
    "(3) 이미지 안에 보이는 모든 글자(라벨·축·범례·캡션 포함)를 원문 그대로 추출. 글자가 없으면 빈 문자열. "
    "(4) details: table/chart 면 실제 데이터를 마크다운 표로 채우고, formula 면 LaTeX 수식을 "
    "채운다. 그 외 유형이거나 구조화할 데이터가 없으면 반드시 빈 문자열(\"\")로 둔다. "
    "지시문을 그대로 복사하지 말고 실제 내용을 채워라. "
    "반드시 JSON 객체 하나만 출력하라(코드펜스·설명 금지). 예시 형식: "
    '{{"type": "table", "confidence": 0.9, '
    '"summary": "분기별 매출 추이를 보여주는 표", "ocr_text": "구분 1Q 2Q ...", '
    '"details": "| 구분 | 1Q | 2Q |\\n|---|---|---|\\n| 매출 | 10 | 20 |"}}'
)


def _ext(filename: str) -> str:
    name = (filename or "").lower()
    dot = name.rfind(".")
    return name[dot:] if dot >= 0 else ""


def _resolve_endpoint(override: dict | None = None) -> tuple[str, str, dict[str, str], int]:
    """(url, model, headers, timeout) — override > image_classification.* > llm.* 순.

    ``override`` 는 image_captions 단계 config 의 {server_url, model, api_key}(있는 키만) —
    컬렉션/단계별로 다른 VLM 을 지정해 비교 테스트할 수 있다.
    """
    from app.core.config import settings
    from app.core.http import auth_headers

    ov = override or {}
    base = (
        str(ov.get("server_url") or "").strip()
        or settings.image_classification_server_url
        or settings.llm_server_url
    ).rstrip("/")
    model = (
        str(ov.get("model") or "").strip()
        or settings.image_classification_model
        or settings.llm_model
    )
    if not model:
        raise RuntimeError(
            "이미지 추출 및 분류에는 비전 가능한 모델명이 필요합니다 "
            "(image_classification.model 또는 llm.model)."
        )
    # api_key 가 비면 llm 키로 폴백(같은 엔드포인트를 재사용하는 일반적 경우).
    api_key = (
        str(ov.get("api_key") or "").strip()
        or settings.image_classification_api_key
        or settings.llm_api_key
    )
    headers = {"Content-Type": "application/json"}
    headers.update(auth_headers(
        api_key,
        settings.image_classification_auth_header,
        settings.image_classification_auth_scheme,
    ))
    return f"{base}/chat/completions", model, headers, settings.image_classification_timeout


def _categories() -> list[str]:
    from app.core.config import settings

    cats = [c.strip() for c in settings.image_classification_categories.split(",") if c.strip()]
    return cats or ["chart", "table", "diagram", "photo", "screenshot", "formula", "logo", "other"]


def _parse_json_object(content: str) -> dict:
    """모델 응답에서 첫 JSON 객체를 추출한다(코드펜스/잡설 방어)."""
    if not content:
        raise ValueError("빈 응답")
    text = content.strip()
    # ```json ... ``` 펜스 제거
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            raise ValueError(f"JSON 객체를 찾지 못함: {content[:120]}")
        return json.loads(m.group(0))


def _normalize(obj: dict) -> dict:
    """모델 출력 dict 를 {type, confidence, summary, ocr_text, details} 로 정규화(카테고리 검증).

    ``ocr_text``/``details`` 는 심층 모드(content_analysis)에서만 채워지며, 경량 모드나
    모델이 생략한 경우 빈 문자열이다(길이는 안전하게 캡)."""
    cats = _categories()
    raw_type = str(obj.get("type", "")).strip().lower()
    typ = raw_type if raw_type in cats else "other"
    try:
        conf = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    summary = str(obj.get("summary", "")).strip()[:1000]
    ocr_text = str(obj.get("ocr_text", "")).strip()[:4000]
    details = str(obj.get("details", "")).strip()[:4000]
    return {
        "type": typ, "confidence": round(conf, 3),
        "summary": summary, "ocr_text": ocr_text, "details": details,
    }


def classify_image_bytes(png: bytes, client=None, endpoint_override: dict | None = None) -> dict:
    """단일 PNG 바이트를 분석한다 → ``{type, confidence, summary, ocr_text, details}``.

    설정(``image_classification.content_analysis``)이 켜져 있으면 상세 설명·OCR·표/수식
    구조화까지 한 번의 호출로 추출하고, 꺼져 있으면 유형 + 한 줄 요약만 받는다(저비용).
    ``client`` 를 주면 재사용하고(여러 장 분류 시), 없으면 1회용 httpx.Client 를 만든다.
    """
    import httpx

    from app.core.config import settings

    url, model, headers, timeout = _resolve_endpoint(endpoint_override)
    deep = settings.image_classification_content_analysis
    prompt = (_PROMPT_DEEP if deep else _PROMPT_BASIC).format(categories=", ".join(_categories()))
    max_tokens = settings.image_classification_max_tokens if deep else 256
    b64 = base64.b64encode(png).decode("ascii")
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }
        ],
    }
    own = client is None
    if own:
        client = httpx.Client(timeout=timeout, headers=headers)
    try:
        # client 는 항상 인증 헤더를 갖고 생성된다(여기서/호출 측에서). 요청별 헤더 불필요.
        resp = client.post(url, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"비전 LLM 오류({resp.status_code}): {resp.text[:200]} @ {url}")
        content = resp.json()["choices"][0]["message"]["content"]
    finally:
        if own:
            client.close()
    return _normalize(_parse_json_object(content))


def _raw_to_rgb_png(raw: bytes) -> bytes | None:
    """원본 이미지 바이트를 RGB PNG 로 변환(크기 필터 없음). 디코드 실패 시 None.

    크기 필터는 enumerate_pdf_images 가 extract_image 의 dims 로 먼저 적용하므로, 분류용
    PNG 생성은 디코드 성공 여부만 본다(필터를 두 번 적용하면 마커와 인덱스가 어긋난다)."""
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:  # noqa: BLE001
        return None
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def enumerate_pdf_images(data: bytes, *, with_png: bool) -> list[dict]:
    """PDF 임베디드 이미지를 결정적 순서로 열거한다 → ``[{index, page, xref, width, height, y_frac, png?}]``.

    분류(``with_png=True``)와 마커 삽입(``with_png=False``)이 **동일한 index** 를 갖도록 하는
    단일 출처. 포함 여부(dedup by xref + min_pixels 필터)는 extract_image 의 dims 로만 결정해
    두 모드에서 완전히 동일하다(png 디코드 성공 여부는 포함에 영향을 주지 않음).

    ``index`` 는 필터 통과 이미지에 0,1,2… 순서로 부여(페이지 오름차순·get_images 순서).
    ``y_frac`` 은 페이지 내 세로 위치(상단=0.0~하단=1.0) — 마커를 본문의 해당 위치에 삽입하는 데 쓴다.
    """
    from app.core.config import settings

    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise RuntimeError(
            "이미지 추출 및 분류(PDF)에는 PyMuPDF 가 필요합니다. `pip install pymupdf` 후 사용하세요."
        ) from e

    out: list[dict] = []
    seen: set[int] = set()
    idx = 0
    min_px = settings.image_classification_min_pixels
    with fitz.open(stream=data, filetype="pdf") as doc:
        for pno, page in enumerate(doc, start=1):
            try:
                height = float(page.rect.height) or 1.0
            except Exception:  # noqa: BLE001
                height = 1.0
            for img in page.get_images(full=True):
                xref = img[0]
                if xref in seen:  # 같은 이미지가 여러 페이지에 반복되면 1회만
                    continue
                seen.add(xref)
                try:
                    info = doc.extract_image(xref)
                except Exception:  # noqa: BLE001
                    continue
                w, h = int(info.get("width", 0)), int(info.get("height", 0))
                if max(w, h) < min_px:  # 아이콘/장식 제외(두 모드 동일 기준)
                    continue
                y_frac = 1.0
                try:
                    rects = page.get_image_rects(xref)
                    if rects:
                        y_frac = max(0.0, min(1.0, float(rects[0].y0) / height))
                except Exception:  # noqa: BLE001 — 위치 못 구하면 페이지 끝으로
                    pass
                item = {
                    "index": idx, "page": pno, "xref": xref,
                    "width": w, "height": h, "y_frac": round(y_frac, 4),
                }
                if with_png:
                    item["png"] = _raw_to_rgb_png(info.get("image", b""))
                out.append(item)
                idx += 1
    return out


def _enumerate_images_for_classify(filename: str, data: bytes) -> list[dict]:
    """분류 대상 이미지를 열거한다 → ``[{index, page, locator, png, width, height, y_frac}]``.

    포맷별 추출은 ``imaging.extractors`` 에 위임한다 — PDF·단일 이미지 외에 DOCX/XLSX/PPTX/
    HWPX(zip 미디어), 바이너리 HWP(OLE BinData), HTML(data URI), 구형 오피스(LibreOffice
    변환 — 미설치면 예외, 호출부 best-effort)까지 커버. PDF 는 내부적으로
    ``enumerate_pdf_images`` 를 재사용하므로 index 가 본문 마커(``[[IMG:pX:iY]]``)와 1:1 이고,
    비 PDF 는 ``page=None``(문서 단위 메타·배지만 — 청크 정밀 연결은 PDF 전용).
    """
    from app.imaging.extractors import extract_images_sync

    return [
        {
            "index": im.index, "page": im.page, "locator": im.locator,
            "png": im.png, "width": im.width, "height": im.height,
            "y_frac": im.y_frac if im.y_frac is not None else 1.0,
            "unit": im.unit,
        }
        for im in extract_images_sync(filename, data, with_png=True)
    ]


def _cap_largest(images: list[dict], cap: int) -> list[dict]:
    """상한 초과 시 **면적이 큰 것부터** cap 장을 남긴다(원래 순서 유지).

    차트/표는 대체로 크고 아이콘·장식은 작다 — 문서 앞쪽 순서로 자르면 뒤쪽의 큰 도표를
    잃으므로 크기 기준으로 선별한다.
    """
    if not cap or len(images) <= cap:
        return images
    keep = sorted(images, key=lambda im: im["width"] * im["height"], reverse=True)[:cap]
    keep_ids = {id(im) for im in keep}
    return [im for im in images if id(im) in keep_ids]


def classify_document_images(
    filename: str, data: bytes, *, endpoint_override: dict | None = None
) -> dict:
    """문서 내 이미지를 분류해 요약 결과를 반환한다(인제스천 메타데이터용).

    반환::

        {
          "count": <분류한 이미지 수>,
          "counts_by_type": {"chart": 2, "photo": 1, ...},
          "items": [{"index", "page", "type", "confidence", "summary", "width", "height"}],
        }

    ``index`` 는 enumerate_pdf_images 가 부여한 안정적 id 로, 본문 마커(``[[IMG:p…:i…]]``)와
    동일하다. 이미지가 없으면 ``{"count": 0, ...}``. 호출 측은 예외를 삼켜 best-effort 로 둔다.
    """
    import httpx

    from app.core.config import settings

    # 엔드포인트/모델을 먼저 확인(미설정이면 추출 전 fail-fast).
    url, _model, headers, timeout = _resolve_endpoint(endpoint_override)

    images = _enumerate_images_for_classify(filename, data)
    if not images:
        return {"count": 0, "counts_by_type": {}, "items": []}

    cap = settings.image_classification_max_images
    if cap and len(images) > cap:
        logger.info("이미지 분류: %d장 중 큰 이미지 %d장만 분류(max_images)", len(images), cap)
        images = _cap_largest(images, cap)

    items: list[dict] = []
    counts: dict[str, int] = {}
    with httpx.Client(timeout=timeout, headers=headers) as client:
        for im in images:
            png = im.get("png")
            if not png:  # 디코드 실패 — index 는 보존(마커와 정합), 분류만 건너뜀
                continue
            try:
                res = classify_image_bytes(png, client=client, endpoint_override=endpoint_override)
            except Exception as e:  # noqa: BLE001 — 한 장 실패가 전체를 막지 않음
                logger.warning("이미지 분류 실패(index=%s, page=%s): %s", im["index"], im["page"], e)
                continue
            counts[res["type"]] = counts.get(res["type"], 0) + 1
            item = {
                "index": im["index"],
                "page": im["page"],
                "locator": im.get("locator", ""),  # 비 PDF 출처 표기(예: word/media/image2.png)
                "width": im["width"],
                "height": im["height"],
                **res,
            }
            if im.get("unit"):  # page 단위 표기(예: pptx "slide" → 화면·주입 블록 "슬라이드 N")
                item["unit"] = im["unit"]
            items.append(item)
    logger.info("이미지 분류 완료: file=%s images=%d classified=%d", filename, len(images), len(items))
    return {"count": len(items), "counts_by_type": counts, "items": items}


# ── 본문 이미지 마커(파싱 시 삽입) ────────────────────────────────────────────
# 파서가 이미지의 페이지 내 위치에 ``[[IMG:p{page}:i{index}]]`` 를 본문에 끼워 넣으면, 그 마커를
# 포함한 청크가 정확히 해당 이미지에 연결된다(텍스트 변형과 무관). index 는 enumerate_pdf_images
# 기준이라 분류 결과(items[*].index)와 1:1 대응한다. 마커는 검색·임베딩 전에 본문에서 제거한다.

_MARKER_FMT = "[[IMG:p{page}:i{index}]]"
MARKER_RE = re.compile(r"\[\[IMG:p(\d+):i(\d+)\]\]")


def pdf_image_layout(data: bytes) -> dict[int, list[dict]]:
    """PDF 페이지별 이미지 위치를 반환한다 → ``{page: [{index, page, y_frac}]}`` (분류 cap 적용).

    파서가 마커를 어디에 삽입할지 결정하는 데 쓴다. 분류와 동일한 enumerate_pdf_images·cap 을
    써서 index 가 일치한다. PyMuPDF 미설치/오류 시 빈 dict(파서는 마커 없이 진행).
    """
    from app.core.config import settings

    try:
        items = enumerate_pdf_images(data, with_png=False)
    except Exception:  # noqa: BLE001
        return {}
    cap = settings.image_classification_max_images
    if cap and len(items) > cap:
        items = items[:cap]
    by_page: dict[int, list[dict]] = {}
    for it in items:
        by_page.setdefault(it["page"], []).append(
            {"index": it["index"], "page": it["page"], "y_frac": it["y_frac"]}
        )
    return by_page


def media_image_layout(filename: str, data: bytes) -> dict[int, list[dict]]:
    """zip 미디어 포맷의 앵커별 이미지 목록 → ``{앵커: [{index, page}]}``.

    앵커는 추출기가 매핑한 위치 번호 — PPTX 는 슬라이드, DOCX 는 문단. 파서가 마커를
    삽입하는 데 쓴다. 분류와 동일한 추출·cap(``_cap_largest`` — 큰 이미지 우선)을
    적용해 index 가 items 와 일치한다. 앵커 매핑이 안 된 이미지(관계 파싱 실패·표 안
    이미지 등)는 제외. 실패 시 빈 dict(마커 없이 진행).
    """
    from app.core.config import settings
    from app.imaging.extractors import extract_images_sync

    try:
        imgs = [
            {"index": im.index, "page": im.page, "width": im.width, "height": im.height}
            for im in extract_images_sync(filename, data, with_png=False)
        ]
    except Exception:  # noqa: BLE001
        return {}
    cap = settings.image_classification_max_images
    if cap and len(imgs) > cap:
        imgs = _cap_largest(imgs, cap)
    by_anchor: dict[int, list[dict]] = {}
    for it in imgs:
        if isinstance(it["page"], int):
            by_anchor.setdefault(it["page"], []).append({"index": it["index"], "page": it["page"]})
    return by_anchor


def media_ref_map(filename: str, data: bytes) -> dict[str, dict]:
    """zip 미디어 멤버명(소문자) → ``{page, index}`` (분류 cap 적용, 앵커 있는 것만).

    외부 파서(rhwp)가 만난 이미지 참조를 우리 분류 items 의 (page, index) 마커 키로
    역매핑하는 데 쓴다. ``media_image_layout`` 과 동일한 추출·cap 이라 index 정합.
    """
    from app.core.config import settings
    from app.imaging.extractors import extract_images_sync

    try:
        imgs = [
            {"index": im.index, "page": im.page, "width": im.width, "height": im.height,
             "member": im.member}
            for im in extract_images_sync(filename, data, with_png=False)
        ]
    except Exception:  # noqa: BLE001
        return {}
    cap = settings.image_classification_max_images
    if cap and len(imgs) > cap:
        imgs = _cap_largest(imgs, cap)
    return {
        im["member"].lower(): {"page": im["page"], "index": im["index"]}
        for im in imgs
        if im.get("member") and isinstance(im["page"], int)
    }


_SLIDE_HEADER_RE = re.compile(r"^## 슬라이드 (\d+)\s*$", re.M)


def append_slide_markers(text: str, layout: dict[int, list[dict]]) -> str:
    """PPTX 파싱 텍스트의 각 ``## 슬라이드 N`` 섹션 끝에 이미지 마커를 덧붙인다.

    마커는 PDF 와 동일 형식(``[[IMG:p{슬라이드}:i{index}]]``)이라 청크↔이미지 연결
    (link_and_strip_markers)과 캡션 주입(image_captions)이 무수정으로 동작한다.
    본문 섹션이 없는 슬라이드(이미지 전용 슬라이드 — 로더가 섹션을 생략)는 문서 말미에
    마커만 추가한다(주입 시 그 자리에 블록, 미주입 시 마커 제거로 흔적 없음).
    """
    if not layout:
        return text
    remaining = {int(k): v for k, v in layout.items()}
    matches = list(_SLIDE_HEADER_RE.finditer(text))
    for i in range(len(matches) - 1, -1, -1):  # 뒤에서부터 삽입해 오프셋 보존
        slide = int(matches[i].group(1))
        items = remaining.pop(slide, None)
        if not items:
            continue
        markers = "\n".join(
            _MARKER_FMT.format(page=it["page"], index=it["index"]) for it in items
        )
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        text = text[:end].rstrip() + f"\n\n{markers}\n\n" + text[end:]
    if remaining:
        tail = "\n".join(
            _MARKER_FMT.format(page=it["page"], index=it["index"])
            for slide in sorted(remaining)
            for it in remaining[slide]
        )
        text = text.rstrip() + f"\n\n{tail}\n"
    return text


def insert_page_markers(page_text: str, layout_items: list[dict]) -> str:
    """페이지 텍스트의 이미지 위치(y_frac)에 마커 줄을 끼워 넣는다.

    각 이미지를 본문 줄 수 대비 y_frac 비율 위치의 줄에 삽입한다(상단 이미지=앞쪽 줄). 빈
    페이지여도 이미지가 있으면 마커만 남긴다. 마커는 인제스천 후 본문에서 제거된다."""
    if not layout_items:
        return page_text
    lines = page_text.split("\n")
    n = len(lines)
    # (줄 위치, 마커) — 아래에서 위로 삽입해 위치 인덱스가 어긋나지 않게 한다.
    inserts: list[tuple[int, str]] = []
    for it in sorted(layout_items, key=lambda x: x["y_frac"]):
        pos = min(n, max(0, round(float(it["y_frac"]) * n)))
        inserts.append((pos, _MARKER_FMT.format(page=it["page"], index=it["index"])))
    for pos, marker in sorted(inserts, key=lambda x: -x[0]):
        lines[pos:pos] = [marker]
    return "\n".join(lines)


def strip_markers(text: str) -> str:
    """본문에서 이미지 마커를 제거하고 그로 인해 생긴 빈 줄을 정리한다."""
    cleaned = MARKER_RE.sub("", text)
    # 마커만 있던 줄이 빈 줄로 남는 경우 + 3줄 이상 연속 공백 줄을 2줄로 축소.
    cleaned = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", cleaned)
    return cleaned.strip("\n")


def link_and_strip_markers(
    chunk_texts: list[str], classification: dict
) -> tuple[list[tuple[str, list[dict]]], bool]:
    """청크 본문의 마커로 이미지 참조를 만들고 마커를 제거한다.

    반환 ``([(clean_text, [{index, page, type, summary}]), ...], any_marker)``.
    ``any_marker`` 가 False 면 마커가 전혀 없었다는 뜻(파서가 안 넣음/비PDF) — 호출 측이
    페이지 휴리스틱으로 폴백할 수 있다. 마커가 가리키는 이미지가 분류 items 에 없으면(캡 초과 등)
    참조는 건너뛰되 마커는 동일하게 제거한다.
    """
    items = classification.get("items") if isinstance(classification, dict) else None
    by_key: dict[tuple[int, int], dict] = {}
    for it in items or []:
        p, ix = it.get("page"), it.get("index")
        if isinstance(p, int) and isinstance(ix, int):
            by_key[(p, ix)] = it

    out: list[tuple[str, list[dict]]] = []
    any_marker = False
    for ct in chunk_texts:
        keys = MARKER_RE.findall(ct)
        if keys:
            any_marker = True
        clean = strip_markers(ct)
        refs: list[dict] = []
        seen: set[tuple[int, int]] = set()
        for ps, ixs in keys:
            key = (int(ps), int(ixs))
            if key in seen:
                continue
            seen.add(key)
            it = by_key.get(key)
            if it:
                ref = {
                    "index": it["index"], "page": it["page"],
                    "type": it.get("type"), "summary": it.get("summary", ""),
                    "ocr_text": it.get("ocr_text", ""), "details": it.get("details", ""),
                }
                if it.get("unit"):  # 단위 표기(pptx "slide" — 화면에서 "슬라이드 N")
                    ref["unit"] = it["unit"]
                refs.append(ref)
        out.append((clean, refs))
    return out, any_marker


# ── 청크 ↔ 이미지 연결(페이지 기준) ──────────────────────────────────────────
# 이미지는 추출 시 페이지 번호를 갖는다. 청크에 페이지를 부여하면 같은 페이지의 이미지를
# 청크에 연결할 수 있다. 청크 텍스트를 PDF 페이지 텍스트와 (공백 무시) 부분일치로 매칭해
# 페이지를 추정한다 — 파서가 텍스트를 크게 바꾸는 경우(vlm 등) 매칭이 안 되면 연결을 비운다.

def extract_page_texts(filename: str, data: bytes) -> dict[int, str]:
    """PDF 페이지별 텍스트를 ``{페이지(1-based): text}`` 로 추출한다(PDF 외에는 빈 dict).

    청크→페이지 매칭의 기준 텍스트로만 쓰인다(저장하지 않음). PyMuPDF 미설치면 빈 dict.
    """
    if _ext(filename) != ".pdf":
        return {}
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return {}
    out: dict[int, str] = {}
    with fitz.open(stream=data, filetype="pdf") as doc:
        for pno, page in enumerate(doc, start=1):
            try:
                out[pno] = page.get_text() or ""
            except Exception:  # noqa: BLE001
                out[pno] = ""
    return out


def _norm_match(s: str) -> str:
    """매칭용 정규화 — 공백 전부 제거 + 소문자(파서 간 공백/개행 차이 흡수)."""
    return re.sub(r"\s+", "", (s or "")).lower()


def link_chunks_to_pages(chunk_texts: list[str], page_texts: dict[int, str]) -> list[list[int]]:
    """각 청크가 속한 페이지(들)를 추정한다 → 청크별 페이지 번호 리스트.

    청크 시작/끝 스니펫(공백 제거 후 앞·뒤 50자)을 각 페이지 텍스트에 부분일치로 찾는다.
    경계에 걸친 청크는 두 페이지에 매칭될 수 있다. 어디에도 안 맞으면 빈 리스트(연결 없음).
    """
    norm_pages = {p: _norm_match(t) for p, t in page_texts.items()}
    ordered_pages = sorted(norm_pages)
    results: list[list[int]] = []
    for ct in chunk_texts:
        nt = _norm_match(ct)
        matched: list[int] = []
        if nt:
            head = nt[:50]
            tail = nt[-50:]
            for p in ordered_pages:
                pt = norm_pages[p]
                if not pt:
                    continue
                if (head and head in pt) or (tail and tail in pt):
                    matched.append(p)
        results.append(matched)
    return results


def build_chunk_image_refs(
    chunk_texts: list[str],
    classification: dict,
    page_texts: dict[int, str],
    *,
    max_refs: int = 8,
) -> list[list[dict]]:
    """청크별로 연결된 이미지 참조 목록을 만든다 → 청크별 ``[{index, page, type, summary}]``.

    분류 결과(``classification["items"]``)를 페이지로 묶고, 청크가 매칭된 페이지의 이미지를
    그 청크에 연결한다. 페이지 정보가 없으면(비PDF 등) 전부 빈 리스트.
    """
    items = classification.get("items") if isinstance(classification, dict) else None
    if not items or not page_texts:
        return [[] for _ in chunk_texts]

    by_page: dict[int, list[dict]] = {}
    for it in items:
        page = it.get("page")
        if not isinstance(page, int):
            continue
        by_page.setdefault(page, []).append({
            "index": it.get("index"),
            "page": page,
            "type": it.get("type"),
            "summary": it.get("summary", ""),
            "ocr_text": it.get("ocr_text", ""),
            "details": it.get("details", ""),
        })

    chunk_pages = link_chunks_to_pages(chunk_texts, page_texts)
    out: list[list[dict]] = []
    for pages in chunk_pages:
        refs: list[dict] = []
        seen: set = set()
        for p in pages:
            for ref in by_page.get(p, []):
                key = (ref["page"], ref["index"])
                if key in seen:
                    continue
                seen.add(key)
                refs.append(ref)
                if len(refs) >= max_refs:
                    break
            if len(refs) >= max_refs:
                break
        out.append(refs)
    return out
