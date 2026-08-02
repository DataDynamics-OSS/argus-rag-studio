# SPDX-License-Identifier: Apache-2.0
"""수정 피드백 루프 단위 테스트 — 신호 추출·집계·정책 병합(순수 로직, DB 비의존).

설계: design/embedding-routing.md Phase 3 — 재배정(corrected) 내역의 반복 신호를
규칙 제안으로 만들고, 활성 정책에 병합(비용 사다리 위치 유지)한다.
"""

from app.routing.feedback import (
    aggregate_corrections,
    covered_by_policy,
    extract_signals,
    merge_suggestion,
)


# ── 신호 추출 ────────────────────────────────────────────────────────────────

def test_extract_signals_extension_and_tokens():
    sig = extract_signals("2026-계약서_final.hwp", {})
    kinds = {(s["kind"], s["value"]) for s in sig}
    assert ("extension", "hwp") in kinds
    assert ("filename_token", "계약서") in kinds
    # 숫자뿐인 토큰·상투어(final)는 제외
    assert not any(s["value"] == "2026" for s in sig)
    assert not any(s["value"] == "final" for s in sig)


def test_extract_signals_doc_type_excludes_other():
    assert any(
        s["kind"] == "doc_type" and s["value"] == "presentation"
        for s in extract_signals("a.pptx", {"doc_type": "presentation"})
    )
    assert not any(
        s["kind"] == "doc_type" for s in extract_signals("a.docx", {"doc_type": "other"})
    )


def test_extract_signals_source_path_prefix():
    sig = extract_signals(
        "보고서.pdf", {"origin_path": "drop/contracts/2026/보고서.pdf", "origin_source": "nas1"}
    )
    path = next(s for s in sig if s["kind"] == "source_path")
    assert path["value"] == "drop/contracts/2026/"
    assert path["storage"] == "nas1"
    # 경로 메타데이터가 없으면(직접 업로드) 경로 신호 없음
    assert not any(s["kind"] == "source_path" for s in extract_signals("보고서.pdf", {}))


# ── 집계(지지도·순도) ─────────────────────────────────────────────────────────

def _corr(name: str, cid: int, meta: dict | None = None) -> dict:
    return {"document_name": name, "metadata": meta or {}, "collection_id": cid}


def test_aggregate_requires_min_support():
    out = aggregate_corrections([_corr("계약서A.hwp", 41)], min_support=2)
    assert out == []
    out = aggregate_corrections([_corr("계약서A.hwp", 41), _corr("계약서B.hwp", 41)], min_support=2)
    ext = next(s for s in out if s["kind"] == "extension")
    assert (ext["router"], ext["value"], ext["collection_id"]) == ("extension_rule", "hwp", 41)
    assert ext["support"] == 2 and ext["purity"] == 1.0
    tok = next(s for s in out if s["kind"] == "filename_token")
    assert (tok["router"], tok["value"]) == ("filename_rule", "계약서")


def test_aggregate_purity_filters_split_signal():
    # 같은 확장자가 서로 다른 컬렉션으로 갈리면(순도 미달) 제안하지 않는다.
    rows = [_corr("a.pdf", 41), _corr("b.pdf", 42)]
    assert aggregate_corrections(rows, min_support=1, min_purity=0.75) == [] or all(
        s["kind"] != "extension" for s in aggregate_corrections(rows, min_support=1, min_purity=0.75)
    )
    # 3:1 이면 순도 0.75 로 지배 컬렉션이 제안된다.
    rows = [_corr("a.pdf", 41), _corr("b.pdf", 41), _corr("c.pdf", 41), _corr("d.pdf", 42)]
    ext = next(s for s in aggregate_corrections(rows, min_support=2) if s["kind"] == "extension")
    assert ext["collection_id"] == 41 and ext["support"] == 3 and ext["total"] == 4


def test_aggregate_samples_capped_at_three():
    rows = [_corr(f"계약{i}.hwp", 41) for i in range(5)]
    ext = next(s for s in aggregate_corrections(rows) if s["kind"] == "extension")
    assert len(ext["samples"]) == 3


# ── 정책 커버리지 검사 ─────────────────────────────────────────────────────────

_POLICY = {
    "mode": "first_match",
    "stages": [
        {"id": "extension_rule", "config": {"rules": [{"extensions": ["hwp"], "collection_id": 44}]}},
        {"id": "metadata_match", "config": {"rules": [{"field": "doc_type", "equals": "contract", "collection_id": 41}]}},
    ],
    "fallback_collection_id": 43,
    "review_below": 0.5,
}


def test_covered_by_policy_matches_existing_mappings():
    assert covered_by_policy(_POLICY, {"router": "extension_rule", "value": "HWP", "collection_id": 44})
    # 같은 값이라도 다른 컬렉션 제안이면 커버 아님(상충 — 사용자 판단 대상)
    assert not covered_by_policy(_POLICY, {"router": "extension_rule", "value": "hwp", "collection_id": 41})
    assert covered_by_policy(_POLICY, {
        "router": "metadata_match", "field": "doc_type", "value": "contract", "collection_id": 41,
    })
    assert not covered_by_policy(_POLICY, {"router": "filename_rule", "value": "계약서", "collection_id": 41})


# ── 병합 ────────────────────────────────────────────────────────────────────

def test_merge_appends_value_to_existing_collection_rule():
    merged = merge_suggestion(_POLICY, {"router": "extension_rule", "value": "hwpx", "collection_id": 44})
    exts = merged["stages"][0]["config"]["rules"][0]["extensions"]
    assert exts == ["hwp", "hwpx"]
    # 원본 불변 + 중복 값은 다시 넣지 않음(대소문자 무시)
    assert _POLICY["stages"][0]["config"]["rules"][0]["extensions"] == ["hwp"]
    again = merge_suggestion(merged, {"router": "extension_rule", "value": "HWPX", "collection_id": 44})
    assert again["stages"][0]["config"]["rules"][0]["extensions"] == ["hwp", "hwpx"]


def test_merge_creates_stage_before_content_routers():
    policy = {
        "mode": "first_match",
        "stages": [
            {"id": "extension_rule", "config": {"rules": []}},
            {"id": "content_embedding", "config": {}},
            {"id": "llm_classify", "config": {}},
        ],
        "fallback_collection_id": None,
        "review_below": 0.5,
    }
    merged = merge_suggestion(policy, {"router": "filename_rule", "value": "계약서", "collection_id": 41})
    ids = [s["id"] for s in merged["stages"]]
    # 새 규칙 단계는 내용/LLM 단계 앞(비용 사다리 유지)
    assert ids == ["extension_rule", "filename_rule", "content_embedding", "llm_classify"]
    rule = merged["stages"][1]["config"]["rules"][0]
    assert rule == {"keywords": ["계약서"], "collection_id": 41}


def test_merge_path_rule_respects_storage_separation():
    policy = {
        "mode": "first_match",
        "stages": [{"id": "path_rule", "config": {"rules": [
            {"patterns": ["drop/hr/"], "storage": "nas1", "collection_id": 42},
        ]}}],
        "fallback_collection_id": None,
        "review_below": 0.5,
    }
    # 같은 컬렉션이라도 storage 가 다르면 별도 규칙으로 추가된다.
    merged = merge_suggestion(policy, {
        "router": "path_rule", "value": "drop/hr2/", "storage": "nas2", "collection_id": 42,
    })
    rules = merged["stages"][0]["config"]["rules"]
    assert len(rules) == 2 and rules[1] == {"patterns": ["drop/hr2/"], "storage": "nas2", "collection_id": 42}
    # 같은 storage 면 기존 규칙의 patterns 에 병합된다.
    merged2 = merge_suggestion(policy, {
        "router": "path_rule", "value": "drop/hr-archive/", "storage": "nas1", "collection_id": 42,
    })
    assert merged2["stages"][0]["config"]["rules"][0]["patterns"] == ["drop/hr/", "drop/hr-archive/"]


def test_merge_metadata_match_dedupes():
    merged = merge_suggestion(_POLICY, {
        "router": "metadata_match", "field": "doc_type", "value": "Contract", "collection_id": 41,
    })
    rules = merged["stages"][1]["config"]["rules"]
    assert len(rules) == 1  # 대소문자만 다른 기존 매핑 — 추가 안 함
    merged = merge_suggestion(_POLICY, {
        "router": "metadata_match", "field": "doc_type", "value": "report", "collection_id": 46,
    })
    assert {"field": "doc_type", "equals": "report", "collection_id": 46} in merged["stages"][1]["config"]["rules"]
