# SPDX-License-Identifier: Apache-2.0
"""임베딩 라우팅 Phase 2 — content_embedding 라우터·centroid(순수 로직) 테스트.

설계: design/embedding-routing.md §8 Phase 2. DB/임베딩 서버 비의존 —
라우터는 호출부(decide)가 ctx 에 넣어준 lead_embedding/profiles 로만 계산한다.
"""

from app.routing.base import REGISTRY, RouteContext, RouteInput, run_policy
from app.routing.profiles import centroid_of, normalize

DOC = RouteInput(filename="아무거나.txt", lead_text="계약 해지 조항 검토")


def _ctx(lead, profiles):
    return RouteContext(lead_embedding=lead, profiles=profiles)


def _profiles():
    # 정규화된 2차원 공간 — 계약(1,0) / 인사(0,1)
    return [
        {"collection_id": 41, "centroid": [1.0, 0.0], "source": "chunks"},
        {"collection_id": 42, "centroid": [0.0, 1.0], "source": "description"},
    ]


def test_registered():
    assert "content_embedding" in REGISTRY


def test_cosine_ranking_and_score_mapping():
    r = REGISTRY["content_embedding"]
    lead = normalize([0.9, 0.1])
    cands = r.route(DOC, {"min_similarity": -1}, _ctx(lead, _profiles()))
    assert [c.collection_id for c in cands] == [41, 42]
    # 기본 하한(0.3)은 직교에 가까운 42(cos≈0.11)를 걸러낸다.
    assert [c.collection_id for c in r.route(DOC, {}, _ctx(lead, _profiles()))] == [41]
    # 점수 = (cos+1)/2 — 0~1 사상.
    assert 0.9 < cands[0].score <= 1.0
    assert "cos=" in cands[0].reason and "chunks" in cands[0].reason


def test_min_similarity_and_top_k():
    r = REGISTRY["content_embedding"]
    lead = normalize([0.9, 0.1])
    # 코사인 하한을 올리면 직교에 가까운 인사(42)는 제외.
    cands = r.route(DOC, {"min_similarity": 0.5}, _ctx(lead, _profiles()))
    assert [c.collection_id for c in cands] == [41]
    # top_k=1 이면 최상위만.
    cands = r.route(DOC, {"min_similarity": -1, "top_k": 1}, _ctx(lead, _profiles()))
    assert len(cands) == 1 and cands[0].collection_id == 41


def test_skips_without_ctx_or_mismatched_dim():
    r = REGISTRY["content_embedding"]
    assert r.route(DOC, {}, None) == []
    assert r.route(DOC, {}, _ctx(None, _profiles())) == []
    assert r.route(DOC, {}, _ctx([1.0, 0.0], [])) == []
    # 차원 불일치 프로파일은 무시(방어).
    bad = [{"collection_id": 9, "centroid": [1.0, 0.0, 0.0], "source": "chunks"}]
    assert r.route(DOC, {}, _ctx([1.0, 0.0], bad)) == []


def test_run_policy_first_match_with_content_stage():
    policy = {
        "mode": "first_match",
        "stages": [{"id": "content_embedding", "min_confidence": 0.7}],
        "fallback_collection_id": 43,
        "review_below": 0.5,
    }
    ctx = _ctx(normalize([1.0, 0.05]), _profiles())
    res = run_policy(policy, DOC, ctx)
    assert res["collection_id"] == 41 and not res["fallback_used"]
    # 선두 임베딩이 없으면(프로파일 미계산 등) 폴백으로.
    res2 = run_policy(policy, DOC, _ctx(None, []))
    assert res2["collection_id"] == 43 and res2["fallback_used"]


# ── centroid 계산(순수) ──────────────────────────────────────────────────────

def test_centroid_normalized_mean():
    c = centroid_of([[1.0, 0.0], [0.0, 1.0]])
    assert abs(c[0] - c[1]) < 1e-9                    # 평균 방향
    assert abs(sum(x * x for x in c) - 1.0) < 1e-9    # L2 정규화
    assert centroid_of([]) == []


def test_normalize_zero_vector_safe():
    assert normalize([0.0, 0.0]) == [0.0, 0.0]


# ── llm_classify (Phase 3) — 프롬프트/파싱 순수 로직 ─────────────────────────

def test_llm_prompt_contains_candidates_and_doc_signals():
    from app.routing.builtins import build_llm_messages

    cols = [{"id": 41, "name": "계약 문서", "description": "법무 계약 원본"},
            {"id": 42, "name": "인사 규정", "description": ""}]
    doc = RouteInput(filename="해지통보.hwpx", lead_text="귀사와 체결한 계약을",
                     source_path="inbox/해지통보.hwpx", metadata={"doc_type": "official"})
    msgs = build_llm_messages(doc, cols, max_chars=100)
    user = msgs[1]["content"]
    assert "id=41" in user and "법무 계약 원본" in user
    assert "id=42" in user and "인사 규정" in user
    assert "해지통보.hwpx" in user and "귀사와 체결한" in user and "official" in user


def test_llm_parse_choice_lenient_and_validates_id():
    from app.routing.builtins import parse_llm_choice

    ids = {41, 42}
    assert parse_llm_choice('{"id": 41, "confidence": 0.9}', ids) == (41, 0.9)
    # JSON 앞뒤 잡음·범위 밖 confidence 도 관대하게.
    assert parse_llm_choice('답: {"id": 42, "confidence": 1.7} 입니다', ids) == (42, 1.0)
    # 무효 id(0 = 해당 없음)·파싱 불가 → (None, 0).
    assert parse_llm_choice('{"id": 0, "confidence": 0.9}', ids) == (None, 0.0)
    assert parse_llm_choice("모르겠음", ids) == (None, 0.0)
    assert parse_llm_choice('{"id": 99, "confidence": 0.9}', ids) == (None, 0.0)


def test_llm_route_skips_without_server_config(monkeypatch):
    from app.core.config import settings

    r = REGISTRY["llm_classify"]
    ctx = RouteContext(collections=[{"id": 41, "name": "계약", "description": ""}])
    monkeypatch.setattr(settings, "llm_server_url", "")
    monkeypatch.setattr(settings, "llm_model", "")
    assert r.route(DOC, {}, ctx) == []          # 전역·오버라이드 모두 없음 → 빈 후보
    assert r.route(DOC, {}, None) == []


# ── custom_function (Phase 3) — AST 검증·샌드박스 실행 ──────────────────────

def test_custom_validate_blocks_dangerous_code():
    from app.routing.sandbox import validate_code

    assert validate_code("def route(doc):\n    return 41") is None
    assert "import" in validate_code("import os\ndef route(doc):\n    return 1")
    assert "route" in validate_code("def other(doc):\n    return 1")
    assert validate_code("def route(doc):\n    return eval('1')") is not None
    assert validate_code("def route(doc):\n    return doc.__class__") is not None


def test_custom_sandbox_runs_and_normalizes():
    from app.routing.sandbox import run_route_function

    doc = {"filename": "2026_계약서.hwpx", "metadata": {}, "lead_text": ""}
    # id 만 반환
    out, err = run_route_function(
        "def route(doc):\n    return 41 if '계약' in doc['filename'] else None", doc)
    assert err is None and out == {"id": 41, "score": None}
    # (id, score) 반환 + 클램프
    out, err = run_route_function("def route(doc):\n    return (42, 1.5)", doc)
    assert err is None and out == {"id": 42, "score": 1.0}
    # 해당 없음
    out, err = run_route_function("def route(doc):\n    return None", doc)
    assert err is None and out == {"id": None, "score": None}
    # 런타임 예외는 오류로
    out, err = run_route_function("def route(doc):\n    return doc['없는키']", doc)
    assert out is None and "KeyError" in err


def test_custom_router_candidate_and_ctx_guard():
    r = REGISTRY["custom_function"]
    ctx = RouteContext(collections=[{"id": 41, "name": "계약", "description": ""}])
    doc = RouteInput(filename="계약서.hwpx")
    cfg = {"code": "def route(doc):\n    return 41 if '계약' in doc['filename'] else None"}
    cands = r.route(doc, cfg, ctx)
    assert len(cands) == 1 and cands[0].collection_id == 41 and cands[0].score == 0.9
    # 활성 컬렉션 밖 id 는 무시.
    cfg2 = {"code": "def route(doc):\n    return 999"}
    assert r.route(doc, cfg2, ctx) == []
    # 코드 없으면 빈 후보.
    assert r.route(doc, {}, ctx) == []
