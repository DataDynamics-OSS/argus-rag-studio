# SPDX-License-Identifier: Apache-2.0
"""문서 라우팅(Phase 1) 단위 테스트 — 레지스트리·빌트인 라우터·정책 조합(순수 로직, DB 비의존).

설계: design 의 라우팅 개념(레지스트리 + 선언적 정책 + 폴백/검토). 라우터·run_policy 는 서버/DB
비의존이라 여기서 직접 검증한다(분류 test_classify.py 와 동형).
"""

from app.routing.base import (
    REGISTRY,
    Candidate,
    RouteInput,
    list_routers,
    normalize_policy,
    run_policy,
    validate_policy,
)


# ── 레지스트리 ────────────────────────────────────────────────────────────────

def test_builtin_routers_registered():
    ids = {r["id"] for r in list_routers()}
    assert {"filename_rule", "metadata_match", "extension_rule", "path_rule"} <= ids


def test_validate_policy_detects_unknown_router():
    errors = validate_policy({"stages": [{"id": "filename_rule"}, {"id": "nope"}]})
    assert any("nope" in e for e in errors)
    assert validate_policy({"stages": [{"id": "filename_rule"}]}) == []


# ── normalize_policy ──────────────────────────────────────────────────────────

def test_normalize_policy_defaults_and_coercion():
    norm = normalize_policy({"mode": "bogus", "stages": ["filename_rule"]})
    assert norm["mode"] == "first_match"  # 알 수 없는 모드 → 기본
    assert norm["stages"][0] == {"id": "filename_rule", "config": {}, "weight": 1.0, "min_confidence": 0.5}
    assert norm["fallback_collection_id"] is None
    assert norm["review_below"] == 0.5


# ── 빌트인 라우터 ──────────────────────────────────────────────────────────────

def test_filename_rule_substring_and_regex():
    r = REGISTRY["filename_rule"]
    cfg = {"rules": [{"keywords": ["제안요청서", "rfp"], "collection_id": 3, "score": 0.9}]}
    hits = r.route(RouteInput(filename="2026_제안요청서_v2.hwp"), cfg)
    assert hits and hits[0].collection_id == 3 and hits[0].score == 0.9
    assert r.route(RouteInput(filename="readme.txt"), cfg) == []
    # regex 모드
    cfg_rx = {"match": "regex", "rules": [{"keywords": [r"rfp[-_]\d+"], "collection_id": 7}]}
    assert r.route(RouteInput(filename="RFP-12.pdf"), cfg_rx)[0].collection_id == 7


def test_extension_rule_normalizes_dot_and_case():
    r = REGISTRY["extension_rule"]
    cfg = {"rules": [
        {"extensions": ["pdf", ".PDF"], "collection_id": 3, "score": 0.9},
        {"extensions": ["pptx", "ppt"], "collection_id": 7},
    ]}
    assert r.route(RouteInput(filename="report.pdf"), cfg)[0].collection_id == 3
    assert r.route(RouteInput(filename="deck.PPTX"), cfg)[0].collection_id == 7
    assert r.route(RouteInput(filename="plan.PdF"), cfg)[0].score == 0.9
    assert r.route(RouteInput(filename="noext"), cfg) == []
    assert r.route(RouteInput(filename="a.docx"), cfg) == []


def test_path_rule_prefix_boundary_and_storage_filter():
    r = REGISTRY["path_rule"]
    cfg = {"match": "prefix", "rules": [
        {"patterns": ["contracts/"], "collection_id": 3, "score": 0.95},
        {"patterns": ["hr"], "storage": "사업부NAS", "collection_id": 7},
    ]}
    # 프리픽스는 디렉터리 경계 기준 — "contracts-old/…" 는 미매칭.
    hits = r.route(RouteInput(source_path="Contracts/2026/a.pdf", storage="docs"), cfg)
    assert hits and hits[0].collection_id == 3 and hits[0].score == 0.95
    assert r.route(RouteInput(source_path="contracts-old/a.pdf"), cfg) == []
    # storage 필터 — 소스명이 일치할 때만 매칭.
    assert r.route(RouteInput(source_path="hr/policy.pdf", storage="사업부NAS"), cfg)[0].collection_id == 7
    assert r.route(RouteInput(source_path="hr/policy.pdf", storage="docs"), cfg) == []
    # 일반 업로드(source_path 없음)는 후보 없음.
    assert r.route(RouteInput(filename="contracts.pdf"), cfg) == []


def test_path_rule_glob_and_regex():
    r = REGISTRY["path_rule"]
    glob_cfg = {"match": "glob", "rules": [{"patterns": ["hr/**/policy/*.pdf"], "collection_id": 7}]}
    assert r.route(RouteInput(source_path="hr/2026/policy/a.pdf"), glob_cfg)[0].collection_id == 7
    assert r.route(RouteInput(source_path="hr/policy/a.pdf"), glob_cfg)[0].collection_id == 7  # ** = 0단계 허용
    assert r.route(RouteInput(source_path="hr/policy/sub/a.pdf"), glob_cfg) == []  # * 는 '/' 통과 금지
    assert r.route(RouteInput(source_path="hr/policy/a.txt"), glob_cfg) == []
    rx_cfg = {"match": "regex", "rules": [{"patterns": [r"contracts/\d{4}/"], "collection_id": 3}]}
    assert r.route(RouteInput(source_path="legal/contracts/2026/a.pdf"), rx_cfg)[0].collection_id == 3
    assert r.route(RouteInput(source_path="contracts/x/a.pdf"), rx_cfg) == []


def test_metadata_match_case_insensitive_equals():
    r = REGISTRY["metadata_match"]
    cfg = {"rules": [{"field": "doc_type", "equals": "rfp", "collection_id": 3, "score": 0.85}]}
    hits = r.route(RouteInput(filename="x", metadata={"doc_type": "RFP"}), cfg)
    assert hits and hits[0].collection_id == 3 and hits[0].score == 0.85
    assert r.route(RouteInput(filename="x", metadata={"doc_type": "report"}), cfg) == []
    assert r.route(RouteInput(filename="x", metadata={}), cfg) == []


# ── run_policy: first_match ───────────────────────────────────────────────────

_POLICY = {
    "mode": "first_match",
    "stages": [
        {"id": "filename_rule",
         "config": {"rules": [{"keywords": ["제안요청서", "rfp"], "collection_id": 3, "score": 0.9}]},
         "min_confidence": 0.7},
        {"id": "metadata_match",
         "config": {"rules": [{"field": "doc_type", "equals": "minutes", "collection_id": 5}]},
         "min_confidence": 0.6},
    ],
    "fallback_collection_id": 99,
    "review_below": 0.5,
}


def test_first_match_picks_first_confident_stage():
    d = run_policy(_POLICY, RouteInput(filename="제안요청서.pdf", metadata={"doc_type": "minutes"}))
    assert d["collection_id"] == 3
    assert d["matched_router"] == "filename_rule"
    assert d["review"] is False
    assert d["fallback_used"] is False


def test_first_match_falls_through_to_metadata():
    d = run_policy(_POLICY, RouteInput(filename="memo.txt", metadata={"doc_type": "minutes"}))
    assert d["collection_id"] == 5
    assert d["matched_router"] == "metadata_match"


def test_below_min_confidence_does_not_match_stage():
    # metadata 기본 점수 0.8 → stage min_confidence 0.9 면 채택 안 됨 → 폴백.
    pol = {
        "mode": "first_match",
        "stages": [{"id": "metadata_match",
                    "config": {"rules": [{"field": "doc_type", "equals": "rfp", "collection_id": 3}]},
                    "min_confidence": 0.9}],
        "fallback_collection_id": 99, "review_below": 0.5,
    }
    d = run_policy(pol, RouteInput(filename="x", metadata={"doc_type": "rfp"}))
    assert d["collection_id"] == 99 and d["fallback_used"] is True and d["review"] is True


def test_no_match_uses_fallback_and_flags_review():
    d = run_policy(_POLICY, RouteInput(filename="unknown.bin"))
    assert d["collection_id"] == 99
    assert d["fallback_used"] is True
    assert d["review"] is True
    assert d["matched_router"] is None


def test_no_match_no_fallback_returns_none():
    pol = {**_POLICY, "fallback_collection_id": None}
    d = run_policy(pol, RouteInput(filename="unknown.bin"))
    assert d["collection_id"] is None
    assert d["fallback_used"] is False


def test_low_confidence_match_flagged_review_without_fallback():
    # 매칭은 됐지만(0.4) review_below(0.5) 미만 → review=True, 폴백 아님(결정 유지).
    pol = {
        "mode": "first_match",
        "stages": [{"id": "metadata_match",
                    "config": {"rules": [{"field": "doc_type", "equals": "rfp", "collection_id": 3, "score": 0.4}]},
                    "min_confidence": 0.3}],
        "fallback_collection_id": 99, "review_below": 0.5,
    }
    d = run_policy(pol, RouteInput(filename="x", metadata={"doc_type": "rfp"}))
    assert d["collection_id"] == 3 and d["review"] is True and d["fallback_used"] is False


# ── run_policy: weighted_vote ─────────────────────────────────────────────────

def test_weighted_vote_accumulates_scores():
    pol = {
        "mode": "weighted_vote",
        "stages": [
            {"id": "filename_rule",
             "config": {"rules": [{"keywords": ["rfp"], "collection_id": 3, "score": 0.6}]},
             "weight": 1.0},
            {"id": "metadata_match",
             "config": {"rules": [{"field": "doc_type", "equals": "rfp", "collection_id": 3, "score": 0.8}]},
             "weight": 1.0},
        ],
        "fallback_collection_id": 99, "review_below": 0.5,
    }
    d = run_policy(pol, RouteInput(filename="rfp.pdf", metadata={"doc_type": "rfp"}))
    assert d["collection_id"] == 3
    assert d["mode"] == "weighted_vote"
    # (0.6*1 + 0.8*1) / (1+1) = 0.7
    assert abs(d["confidence"] - 0.7) < 1e-6


def test_trace_records_every_stage():
    d = run_policy(_POLICY, RouteInput(filename="제안요청서.pdf"))
    assert [t["router"] for t in d["trace"]] == ["filename_rule", "metadata_match"]
