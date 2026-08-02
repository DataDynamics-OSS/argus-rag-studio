# SPDX-License-Identifier: Apache-2.0
"""image_captions transform 테스트 — VLM 인식 결과의 본문 주입(순수 로직).

설계: design/image-content-indexing.md §4. 주입 위치(PDF 마커 옆/비 PDF 부록), 필터
(유형·확신도), 상한, 마커 보존(청크↔이미지 연결용)을 검증한다.
"""

from app.ingestion.transforms import REGISTRY
from app.ingestion.transforms.image_captions import inject_captions


def _item(index=0, page=None, typ="chart", conf=0.9, summary="분기별 매출 차트",
          ocr="1Q 12 2Q 15", details="| 분기 | 매출 |"):
    return {"index": index, "page": page, "type": typ, "confidence": conf,
            "summary": summary, "ocr_text": ocr, "details": details}


def test_registered_in_transform_registry():
    assert "image_captions" in REGISTRY
    assert REGISTRY["image_captions"].phase == "post_parse"


def test_non_pdf_appended_as_appendix_section():
    out = inject_captions("본문입니다.", [_item()])
    assert out.startswith("본문입니다.")
    assert "## 문서 내 이미지" in out
    assert "[이미지 1 — 차트] 분기별 매출 차트" in out
    assert "OCR: 1Q 12 2Q 15" in out and "| 분기 | 매출 |" in out


def test_pdf_marker_gets_block_next_to_it_and_marker_kept():
    text = "앞 문단\n[[IMG:p3:i0]]\n뒷 문단"
    out = inject_captions(text, [_item(index=0, page=3)])
    # 마커는 보존(청크↔이미지 정밀 연결이 소비) + 블록이 마커 바로 뒤에.
    assert "[[IMG:p3:i0]]" in out
    assert out.index("[[IMG:p3:i0]]") < out.index("[이미지 1 (p.3) — 차트]") < out.index("뒷 문단")
    assert "## 문서 내 이미지" not in out  # 전부 마커 옆 배치 → 부록 없음


def test_pptx_slide_marker_and_label():
    # pptx(Step 3): 마커 page=슬라이드 번호, unit="slide" → 라벨이 "슬라이드 N" 으로.
    text = "## 슬라이드 2\n\n둘째 장 본문\n[[IMG:p2:i0]]"
    item = {**_item(index=0, page=2), "unit": "slide"}
    out = inject_captions(text, [item])
    assert "[[IMG:p2:i0]]" in out
    assert "[이미지 1 (슬라이드 2) — 차트]" in out
    assert "## 문서 내 이미지" not in out  # 마커 옆 배치 → 부록 없음


def test_docx_para_marker_and_label():
    # docx(Step 3): 마커 page=문단 번호, unit="para" → 라벨이 "문단 N" 으로.
    text = "서론 문단\n[[IMG:p2:i0]]\n본론 문단"
    item = {**_item(index=0, page=2), "unit": "para"}
    out = inject_captions(text, [item])
    assert out.index("[[IMG:p2:i0]]") < out.index("[이미지 1 (문단 2) — 차트]") < out.index("본론 문단")
    assert "## 문서 내 이미지" not in out


def test_html_img_marker_no_location_label():
    # html(Step 3): 블록이 img 자리에 in-place 주입되므로 위치 라벨은 생략.
    text = "첫 문단\n[[IMG:p1:i0]]\n둘째 문단"
    item = {**_item(index=0, page=1), "unit": "img"}
    out = inject_captions(text, [item])
    assert out.index("[[IMG:p1:i0]]") < out.index("[이미지 1 — 차트]") < out.index("둘째 문단")
    assert "(p.1)" not in out and "## 문서 내 이미지" not in out


def test_type_filter_excludes_logo_by_default():
    out = inject_captions("본문", [_item(typ="logo", summary="회사 로고")])
    assert out == "본문"
    # 명시적으로 허용하면 주입된다.
    out2 = inject_captions("본문", [_item(typ="logo", summary="회사 로고")], {"types": "logo"})
    assert "[이미지 1 — 로고]" in out2


def test_low_confidence_and_empty_content_skipped():
    assert inject_captions("본문", [_item(conf=0.3)]) == "본문"
    assert inject_captions("본문", [_item(summary="", ocr="", details="")]) == "본문"


def test_max_images_cap():
    items = [_item(index=i, summary=f"이미지{i}") for i in range(5)]
    out = inject_captions("본문", items, {"max_images": 2})
    assert "[이미지 1 " in out and "[이미지 2 " in out and "[이미지 3 " not in out


def test_config_toggles():
    out = inject_captions("본문", [_item()], {"include_ocr": False, "include_details": False})
    assert "OCR:" not in out and "| 분기 |" not in out and "차트" in out


def test_transform_apply_reads_ctx():
    t = REGISTRY["image_captions"]
    out = t.apply("본문", {}, {"image_classification": {"items": [_item()]}})
    assert "## 문서 내 이미지" in out
    assert t.apply("본문", {}, None) == "본문"  # ctx 없음 → 무변경
