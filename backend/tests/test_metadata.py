# SPDX-License-Identifier: Apache-2.0
"""문서 메타데이터 추출(extract_metadata) 회귀 테스트.

HWP/HWPX 는 리포의 samples/hwp 실파일로, PDF 는 tests/fixtures 픽스처로 검증한다.
best-effort 계약(미지원/깨진 입력 → 빈 dict, 예외 없음)도 확인한다.
"""

from pathlib import Path

import pytest

from app.ingestion.metadata import extract_metadata

_REPO = Path(__file__).resolve().parents[2]
HWP_DIR = _REPO / "samples" / "hwp"
TABLE_PDF = Path(__file__).parent / "fixtures" / "table.pdf"


def _read(p: Path) -> bytes:
    return p.read_bytes()


@pytest.mark.skipif(not (HWP_DIR / "footnote-tbox-01.hwp").exists(), reason="samples/hwp 없음")
def test_hwp_summary_metadata():
    meta = extract_metadata("footnote-tbox-01.hwp", _read(HWP_DIR / "footnote-tbox-01.hwp"))
    assert meta["format"] == "hwp"
    assert meta["app"].startswith("HWP 5.")
    assert "각주" in meta["title"]
    assert meta["author"] == "edward"
    assert meta["created"].startswith("2026-03-18")


@pytest.mark.skipif(not (HWP_DIR / "hwpers_test4_complex_table.hwp").exists(), reason="samples/hwp 없음")
def test_hwp_without_summary_stream():
    # HwpSummaryInformation 스트림이 없는 HWP — FileHeader 정보만, 예외 없이 동작
    meta = extract_metadata("hwpers_test4_complex_table.hwp", _read(HWP_DIR / "hwpers_test4_complex_table.hwp"))
    assert meta["format"] == "hwp"
    assert "app" in meta and "title" not in meta


@pytest.mark.skipif(not (HWP_DIR / "3-09월_교육_통합_2023.hwpx").exists(), reason="samples/hwp 없음")
def test_hwpx_opf_metadata():
    meta = extract_metadata("3-09월_교육_통합_2023.hwpx", _read(HWP_DIR / "3-09월_교육_통합_2023.hwpx"))
    assert meta["format"] == "hwpx"
    assert "모의고사" in meta["title"]
    assert meta["author"] == "장수연 박장엽"
    assert meta["last_saved_by"] == "admin"
    assert meta["language"] == "ko"


def test_pdf_metadata():
    meta = extract_metadata("table.pdf", _read(TABLE_PDF))
    assert meta["format"] == "pdf"
    assert meta["pages"] == 1


def test_unsupported_format_returns_empty():
    assert extract_metadata("a.txt", b"hello world") == {}


def test_broken_input_returns_empty():
    # OLE 가 아닌 .hwp / ZIP 이 아닌 .hwpx → 예외 없이 빈 dict
    assert extract_metadata("x.hwp", b"not an ole file") == {}
    assert extract_metadata("x.hwpx", b"not a zip file") == {}
