# SPDX-License-Identifier: Apache-2.0
"""이미지 내용 주입 transform — VLM 인식 결과를 본문에 삽입(post_parse).

이미지 분류(1-c 단계)가 만든 결과를 오케스트레이터가 ``ctx["image_classification"]`` 로
주입한다(PII 규칙과 동일한 ctx 사전 주입 패턴 — 이 transform 은 원본 바이트/DB 에 접근하지
않는 순수 텍스트 변환). 설계: design/image-content-indexing.md §4.

주입 위치:
  - PDF: 본문의 위치 마커(``[[IMG:pX:iY]]``) **바로 뒤**에 삽입하고 마커는 남긴다 —
    기존 청크↔이미지 정밀 연결(link_and_strip)이 무수정으로 동작한다.
  - 비 PDF(마커 없음): 본문 말미에 ``## 문서 내 이미지`` 섹션으로 일괄 추가.

주입 형식은 원문과 구분되는 명시적 블록(``[이미지 N — 차트] …``) — VLM 산출임이 드러나야
환각 오염을 검수할 수 있다. 사실성 높은 OCR 을 우선하고 logo·photo·other 는 기본 제외.
"""

from app.ingestion.transforms.base import Transform, register_transform

# 기본 주입 대상 — 내용 정보가 있는 유형만(로고·사진·기타는 검색 가치 대비 노이즈).
DEFAULT_TYPES = ("chart", "table", "diagram", "screenshot", "formula")

_TYPE_LABEL = {
    "chart": "차트", "table": "표", "diagram": "다이어그램", "photo": "사진",
    "screenshot": "화면 캡처", "formula": "수식", "logo": "로고", "other": "기타",
}

_MARKER_FMT = "[[IMG:p{page}:i{index}]]"
_APPENDIX_HEADER = "## 문서 내 이미지"


def _build_block(item: dict, *, include_ocr: bool, include_details: bool) -> str:
    """이미지 1장의 주입 블록을 만든다(빈 산출은 줄 자체를 생략)."""
    n = int(item.get("index", 0)) + 1
    page = item.get("page")
    if isinstance(page, int):
        # unit — pptx 는 슬라이드, docx 는 문단 번호(페이지 아님). html("img")은 블록이
        # img 자리에 in-place 주입되므로 위치 라벨을 생략. 없으면 페이지.
        unit = item.get("unit")
        if unit == "slide":
            where = f" (슬라이드 {page})"
        elif unit == "para":
            where = f" (문단 {page})"
        elif unit == "img":
            where = ""
        else:
            where = f" (p.{page})"
    else:
        where = ""
    label = _TYPE_LABEL.get(str(item.get("type", "")), str(item.get("type", "")))
    lines = [f"[이미지 {n}{where} — {label}] {str(item.get('summary') or '').strip()}".rstrip()]
    ocr = str(item.get("ocr_text") or "").strip()
    if include_ocr and ocr:
        lines.append(f"OCR: {ocr}")
    details = str(item.get("details") or "").strip()
    if include_details and details:
        lines.append(details)
    return "\n".join(lines)


def inject_captions(text: str, items: list[dict], cfg: dict | None = None) -> str:
    """VLM 분석 items 를 본문에 주입한 텍스트를 반환한다(순수 함수 — 테스트 용이).

    필터(유형·최소 확신도)와 상한을 거친 항목만 주입한다. 마커가 본문에 있으면 그 옆에,
    없으면(비 PDF·마커 미삽입) 말미 부록 섹션에 넣는다. 주입할 것이 없으면 원문 그대로.
    """
    cfg = cfg or {}
    types_raw = str(cfg.get("types") or "").strip()
    allowed = {t.strip().lower() for t in types_raw.split(",") if t.strip()} or set(DEFAULT_TYPES)
    try:
        min_conf = float(cfg.get("min_confidence", 0.5))
    except (TypeError, ValueError):
        min_conf = 0.5
    include_ocr = bool(cfg.get("include_ocr", True))
    include_details = bool(cfg.get("include_details", True))
    try:
        max_images = int(cfg.get("max_images", 20))
    except (TypeError, ValueError):
        max_images = 20

    selected: list[dict] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        if str(it.get("type", "")).lower() not in allowed:
            continue
        try:
            conf = float(it.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        if conf < min_conf:
            continue
        # 주입할 내용이 하나도 없으면(요약·OCR·표 전부 빈) 스킵.
        if not any(str(it.get(k) or "").strip() for k in ("summary", "ocr_text", "details")):
            continue
        selected.append(it)
        if max_images and len(selected) >= max_images:
            break
    if not selected:
        return text

    appendix: list[str] = []
    for it in selected:
        block = _build_block(it, include_ocr=include_ocr, include_details=include_details)
        page = it.get("page")
        marker = (
            _MARKER_FMT.format(page=page, index=it.get("index"))
            if isinstance(page, int) else None
        )
        if marker and marker in text:
            # 마커는 남긴다 — 청크↔이미지 정밀 연결(link_and_strip)이 마커를 소비한다.
            text = text.replace(marker, f"{marker}\n\n{block}\n", 1)
        else:
            appendix.append(block)

    if appendix:
        text = f"{text.rstrip()}\n\n{_APPENDIX_HEADER}\n\n" + "\n\n".join(appendix) + "\n"
    return text


@register_transform
class ImageCaptionsTransform(Transform):
    id = "image_captions"
    label = "이미지 내용 주입(VLM)"
    description = (
        "VLM 이미지 인식 결과(요약·OCR·표)를 본문에 삽입해 차트/표 이미지 속 정보를 "
        "검색·답변에 쓸 수 있게 합니다(파싱 후). 이미지 분류(VLM 서버) 구성이 필요하며, "
        "이미지당 VLM 1회 호출이 추가됩니다."
    )
    phase = "post_parse"
    config_schema = {
        "types": {"type": "string", "label": "주입 유형(쉼표 — 비우면 chart,table,diagram,screenshot,formula)"},
        "min_confidence": {"type": "number", "label": "최소 확신도(기본 0.5)"},
        "include_ocr": {"type": "boolean", "label": "OCR 텍스트 포함(기본 켬)"},
        "include_details": {"type": "boolean", "label": "표/수식 구조화 포함(기본 켬)"},
        "max_images": {"type": "number", "label": "문서당 주입 상한(기본 20)"},
        # VLM 지정(선택) — 비우면 전역 설정(image_classification.*). 오케스트레이터가 분석
        # 단계(1-c)에서 이 값을 읽어 엔드포인트를 오버라이드한다(컬렉션별 VLM 비교 테스트용).
        "server_url": {"type": "string", "label": "VLM 서버 URL(비우면 전역 설정)"},
        "model": {"type": "string", "label": "VLM 모델명(비우면 전역 설정)"},
        "api_key": {"type": "string", "label": "API 키(비우면 전역 설정)"},
    }

    def available(self) -> bool:
        # VLM 엔드포인트/모델이 구성돼야 분석 결과가 생긴다(미구성 시 UI 비활성).
        from app.core.config import settings

        return bool(
            (settings.image_classification_server_url or settings.llm_server_url)
            and (settings.image_classification_model or settings.llm_model)
        )

    def apply(self, data, cfg: dict, ctx=None):
        clf = (ctx or {}).get("image_classification") or {}
        return inject_captions(data, clf.get("items") or [], cfg)
