# SPDX-License-Identifier: Apache-2.0
"""문서 자동 분류(P2) 단위 테스트 — 규칙·정규화·우선순위·멱등.

설계: design/document-classification.md §3·§4.
"""

from app.ingestion.classify import (
    DOC_TYPES,
    classify_by_anchors,
    classify_document,
    needs_content_refinement,
    normalize_doc_type,
    normalize_language,
)


# ── normalize_doc_type ────────────────────────────────────────────────────────

def test_normalize_known_variants():
    assert normalize_doc_type("회의록") == "minutes"
    assert normalize_doc_type("제안요청서") == "rfp"
    assert normalize_doc_type("제안서") == "proposal"
    assert normalize_doc_type("발표자료") == "presentation"
    assert normalize_doc_type("보고서") == "report"
    assert normalize_doc_type("REPORT") == "report"  # 코드 대소문자 무시


def test_normalize_unknown_returns_none():
    assert normalize_doc_type("계약서") is None
    assert normalize_doc_type("") is None
    assert normalize_doc_type(None) is None


# ── 파일명 규칙 + 우선순위 ────────────────────────────────────────────────────

def test_classify_by_filename_minutes():
    r = classify_document("2026-06 주간 회의록.hwp")
    assert r["doc_type"] == "minutes"
    assert r["doc_type_source"] == "rule"
    assert r["doc_type_confidence"] == 0.7


def test_rfp_beats_proposal_ordering():
    # "제안요청서" 는 "제안" 을 포함하지만 rfp 로 분류돼야 한다(순서 의존).
    assert classify_document("XX사업_제안요청서_v2.pdf")["doc_type"] == "rfp"
    assert classify_document("과업지시서.hwp")["doc_type"] == "rfp"


def test_proposal_filename():
    assert classify_document("우리회사_사업제안서.pptx")["doc_type"] == "proposal"


def test_filename_keyword_beats_extension():
    # .pptx 지만 파일명이 제안서 → proposal(확장자 폴백보다 파일명 우선).
    assert classify_document("제안서_최종.pptx")["doc_type"] == "proposal"


def test_extension_fallback_presentation():
    # 파일명에 단서 없음 + .pptx → presentation(확장자 폴백, 낮은 신뢰도).
    r = classify_document("deck_final.pptx")
    assert r["doc_type"] == "presentation"
    assert r["doc_type_confidence"] == 0.5


def test_unclassified_is_other():
    r = classify_document("무제.txt")
    assert r["doc_type"] == "other"
    assert r["doc_type_confidence"] == 0.0
    assert r["doc_type"] in DOC_TYPES


# ── 출처/사람 확정값 보존 + reindex 멱등 ──────────────────────────────────────

def test_source_provided_doc_type_trusted():
    r = classify_document("아무거나.bin", source_meta={"doc_type": "보고서"})
    assert r["doc_type"] == "report"
    assert r["doc_type_source"] == "source"
    assert r["doc_type_confidence"] == 1.0


def test_human_confirmed_preserved():
    r = classify_document(
        "제안서.pdf",
        source_meta={"doc_type": "report", "doc_type_source": "human", "doc_type_confidence": 1.0},
    )
    # 파일명은 proposal 단서지만 사람이 확정한 report 를 보존.
    assert r["doc_type"] == "report"
    assert r["doc_type_source"] == "human"


def test_prior_rule_guess_is_rederived_not_frozen():
    # 이전 자동추정(source=rule)은 신뢰하지 않고 파일명으로 재도출(reindex 멱등).
    r = classify_document(
        "제안서.pdf",
        source_meta={"doc_type": "minutes", "doc_type_source": "rule", "doc_type_confidence": 0.7},
    )
    assert r["doc_type"] == "proposal"
    assert r["doc_type_source"] == "rule"


# ── 언어 정규화 / 통과 필드 ───────────────────────────────────────────────────

def test_language_normalized():
    assert classify_document("a.pdf", source_meta={"language": "KOR"})["language"] == "ko"
    assert normalize_language("English") == "en"
    assert normalize_language("klingon") is None


def test_dept_and_source_system_passthrough():
    r = classify_document("회의록.hwp", source_meta={"dept": "영업본부", "source_system": "nifi:flow-12"})
    assert r["dept"] == "영업본부"
    assert r["source_system"] == "nifi:flow-12"


def test_no_security_keys_emitted():
    # 분류는 보안/DRM 류 키를 절대 생성하지 않는다.
    r = classify_document("대외비_보고서.hwp", source_meta={"security": "대외비", "drm": True})
    assert "security" not in r
    assert "drm" not in r
    assert r["doc_type"] == "report"


# ── 내용 기반(앵커 임베딩) 분류 P3 ───────────────────────────────────────────

def test_classify_by_anchors_picks_nearest():
    # 직교 단위벡터로 앵커를 구성 — doc_vec 이 minutes 앵커와 정렬되면 minutes 채택.
    anchors = {
        "report": [1.0, 0.0, 0.0],
        "minutes": [0.0, 1.0, 0.0],
        "proposal": [0.0, 0.0, 1.0],
    }
    hit = classify_by_anchors([0.1, 0.9, 0.0], anchors, threshold=0.45)
    assert hit is not None
    assert hit[0] == "minutes"
    assert hit[1] > 0.9


def test_classify_by_anchors_below_threshold_returns_none():
    anchors = {"report": [1.0, 0.0], "minutes": [0.0, 1.0]}
    # 45도(=cos 0.707) 근처지만 threshold 0.9 보다 낮아 채택 안 됨.
    assert classify_by_anchors([1.0, 1.0], anchors, threshold=0.9) is None


def test_classify_by_anchors_empty_vec():
    assert classify_by_anchors([], {"report": [1.0]}, threshold=0.1) is None


def test_needs_content_refinement():
    assert needs_content_refinement({"doc_type": "other", "doc_type_source": "rule"})
    assert needs_content_refinement({"doc_type": "other"})
    # 규칙이 유형을 정했으면 보강 안 함
    assert not needs_content_refinement({"doc_type": "report", "doc_type_source": "rule"})
    # 사람/출처 확정 other 는 건드리지 않음
    assert not needs_content_refinement({"doc_type": "other", "doc_type_source": "human"})
