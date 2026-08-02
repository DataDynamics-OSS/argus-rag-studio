# SPDX-License-Identifier: Apache-2.0
"""실제 HWP/HWPX 샘플(rhwp 저장소의 합성 픽스처) 회귀 테스트.

두 추출 경로를 검증한다:
  - 순수 Python 로더(``app.ingestion.loaders``) — 의존성 가볍고 CI 에서 항상 실행
  - rhwp 전략(``rhwp_py`` 네이티브 확장) — 설치된 경우에만(미설치 시 skip)

샘플 출처/라이선스(rhwp, MIT)는 ``samples/hwp/README.md`` 참조.
"""

import importlib.util
from pathlib import Path

import pytest

from app.ingestion.loaders import extract_text
from app.ingestion.parsers import parse_document

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples" / "hwp"

COMPLEX_TABLE = "hwpers_test4_complex_table.hwp"
FOOTNOTE = "footnote-tbox-01.hwp"
HWPX_TABLE = "표-텍스트.hwpx"
BUDGET_TABLE = "table-complex.hwp"          # 공개 자료: 실제 예산서(병합 표)
EXAM_HWPX = "3-09월_교육_통합_2023.hwpx"     # 공개 자료: 모의고사(대용량 다페이지)
ALL_SAMPLES = [COMPLEX_TABLE, FOOTNOTE, HWPX_TABLE, BUDGET_TABLE, EXAM_HWPX]


def _has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def _read(name: str) -> bytes:
    return (SAMPLES_DIR / name).read_bytes()


def test_samples_present():
    for name in ALL_SAMPLES:
        assert (SAMPLES_DIR / name).is_file(), f"샘플 누락: {name}"


# ── 순수 Python 로더(CI 상시 실행) ────────────────────────────────────────────
@pytest.mark.parametrize("name", ALL_SAMPLES)
def test_python_loader_extracts(name):
    out = extract_text(name, _read(name))
    assert out.strip(), f"{name} 추출 결과가 비어 있음"


def test_python_loader_hwpx_table_markdown():
    out = extract_text(HWPX_TABLE, _read(HWPX_TABLE))
    assert "| ---" in out  # HWPX 표 → Markdown 표


def test_python_loader_footnote_labeled():
    out = extract_text(FOOTNOTE, _read(FOOTNOTE))
    assert "[각주]" in out


# ── rhwp 전략(rhwp_py 설치 시) ────────────────────────────────────────────────
@pytest.mark.skipif(not _has("rhwp_py"), reason="rhwp_py 미빌드(backend/native/rhwp_py)")
@pytest.mark.parametrize("name", ALL_SAMPLES)
def test_rhwp_extracts(name):
    import rhwp_py

    md = rhwp_py.extract_markdown(_read(name))
    assert md.strip(), f"{name} rhwp 추출 결과가 비어 있음"


@pytest.mark.skipif(not _has("rhwp_py"), reason="rhwp_py 미빌드")
def test_rhwp_hwpx_table_markdown():
    import rhwp_py

    md = rhwp_py.extract_markdown(_read(HWPX_TABLE))
    assert "| ---" in md


@pytest.mark.skipif(not _has("rhwp_py"), reason="rhwp_py 미빌드")
def test_rhwp_real_budget_table_markdown():
    """실제 예산서(병합 표)를 rhwp 가 Markdown 표로 보존하는지(공개 자료)."""
    import rhwp_py

    md = rhwp_py.extract_markdown(_read(BUDGET_TABLE))
    assert "| ---" in md


# ── 두 경로 모두 parse_document 진입점으로 동작 ───────────────────────────────
@pytest.mark.skipif(not _has("rhwp_py"), reason="rhwp_py 미빌드")
@pytest.mark.parametrize("name", ALL_SAMPLES)
def test_both_strategies_via_parse_document(name):
    data = _read(name)
    assert parse_document(name, data, "text").strip()   # 순수 Python 경로
    assert parse_document(name, data, "rhwp").strip()    # Rust 바인딩 경로
