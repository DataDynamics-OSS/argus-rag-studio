# SPDX-License-Identifier: Apache-2.0
"""문서 라우팅 전략 레지스트리 — 인제스천 전 "어느 지식베이스(컬렉션)로 보낼지" 결정.

설계 의도: 라우팅 방법을 코드에 박지 않고 **플러그형 라우터(Router)** 로 둔다. 새 라우터 추가 =
``Router`` 서브클래스 1개 + ``@register_router`` 데코레이터(한 곳). 그러면 introspection API
(`GET /routing/routers`)와 UI 빌더에 자동 노출되고, 오케스트레이터·인테이크 코드는 손대지 않는다.
(인제스천 보강 ``app/ingestion/transforms`` 와 동일한 레지스트리 패턴.)

라우터는 입력 문서(``RouteInput``)를 보고 **후보(Candidate=컬렉션+점수+사유)** 목록을 낸다. 정책
(``run_policy``)이 여러 라우터의 후보를 조합 모드(first_match | weighted_vote)로 합쳐 최종 결정을
만든다. 라우터·조합 함수는 **DB/서버 비의존(순수)** — 테스트 용이(분류 ``classify_by_anchors`` 와 동형).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MODES = ("first_match", "weighted_vote")
REGISTRY: dict[str, "Router"] = {}


@dataclass
class RouteInput:
    """라우팅 판단 입력 — 본문 임베딩/파싱 **전에** 확보 가능한 신호만.

    Phase 1 라우터(filename_rule/metadata_match)는 ``filename`` 과 ``metadata`` 만 쓴다.
    ``lead_text`` 는 내용 기반 라우터(Phase 2)용 선두 텍스트 자리(현재 비어 있어도 됨).
    ``source_path``/``storage`` 는 참조 인테이크(스토리지 소스 pull)에서만 채워진다 —
    소스 내 정규화 경로와 소스 논리명(rag_storage_sources.name). path_rule 라우터가 사용.
    """

    filename: str = ""
    metadata: dict = field(default_factory=dict)
    lead_text: str = ""
    source_type: str = "upload"
    content_hash: str | None = None
    source_path: str = ""
    storage: str = ""


@dataclass
class Candidate:
    """라우터가 제안하는 후보 한 건."""

    collection_id: int
    score: float  # 0.0~1.0
    reason: str = ""


@dataclass
class RouteContext:
    """라우터 실행 컨텍스트 — DB 비의존이 되도록 호출부가 미리 채워 넘긴다.

    ``collections`` 는 라우팅 후보가 될 활성 컬렉션 메타([{id, name, description, ...}]).
    Phase 1 빌트인은 config 에 컬렉션 id 를 직접 적으므로 쓰지 않지만, 내용/LLM 라우터(Phase 2+)가
    "후보 컬렉션 집합" 으로 사용한다.

    ``lead_embedding``/``profiles`` 는 내용 임베딩 라우터(Phase 2)용 — 호출부(decide)가
    정책에 content_embedding 단계가 있을 때만 준비한다(불필요한 임베딩 비용 방지).
    profiles 항목: ``{collection_id, centroid(list[float] — L2 정규화), source}``.
    lead_embedding 도 L2 정규화되어 있어 라우터는 내적=코사인으로 계산한다.
    """

    collections: list[dict] = field(default_factory=list)
    lead_embedding: list[float] | None = None
    profiles: list[dict] = field(default_factory=list)


class Router:
    id: str = ""
    label: str = ""
    description: str = ""
    config_schema: dict = {}  # UI 폼 자동 생성용(파라미터 없으면 {})

    def available(self) -> bool:
        """의존성/서버 가용성(미가용이면 UI 비활성, 실행 시 건너뜀)."""
        return True

    def route(self, doc: RouteInput, cfg: dict, ctx: RouteContext | None = None) -> list[Candidate]:
        """문서를 보고 후보 목록을 반환. 해당 없으면 빈 리스트(예외 금지 — 호출부가 감싼다)."""
        raise NotImplementedError


def register_router(cls):
    """라우터 클래스를 레지스트리에 등록한다(데코레이터)."""
    inst = cls()
    if not inst.id:
        raise ValueError("Router.id 가 필요합니다")
    REGISTRY[inst.id] = inst
    return cls


def _safe_available(r: "Router") -> bool:
    try:
        return bool(r.available())
    except Exception:  # noqa: BLE001
        return False


def list_routers() -> list[dict]:
    """등록된 라우터 메타데이터(UI/introspection용)."""
    out = []
    for r in REGISTRY.values():
        out.append({
            "id": r.id, "label": r.label, "description": r.description,
            "config_schema": r.config_schema, "available": _safe_available(r),
        })
    return sorted(out, key=lambda x: x["id"])


# ---------------------------------------------------------------------------
# 정책(여러 라우터의 조합) 정규화·검증·실행
# ---------------------------------------------------------------------------

def normalize_policy(raw) -> dict:
    """임의 입력을 표준 정책 dict 로 정규화한다.

    표준형: ``{mode, stages:[{id,config,weight,min_confidence}], fallback_collection_id, review_below}``.
    stage 는 ``"id"`` 문자열 또는 ``{"id":..., "config":{...}, ...}`` 모두 허용.
    """
    raw = raw or {}
    mode = raw.get("mode") if raw.get("mode") in MODES else "first_match"
    stages: list[dict] = []
    for st in (raw.get("stages") or []):
        if isinstance(st, str):
            stages.append({"id": st, "config": {}, "weight": 1.0, "min_confidence": 0.5})
        elif isinstance(st, dict) and st.get("id"):
            try:
                weight = float(st.get("weight", 1.0))
            except (TypeError, ValueError):
                weight = 1.0
            try:
                min_conf = float(st.get("min_confidence", 0.5))
            except (TypeError, ValueError):
                min_conf = 0.5
            stages.append({
                "id": st["id"], "config": st.get("config") or {},
                "weight": weight, "min_confidence": min_conf,
            })
    fallback = raw.get("fallback_collection_id")
    try:
        fallback = int(fallback) if fallback is not None else None
    except (TypeError, ValueError):
        fallback = None
    try:
        review_below = float(raw.get("review_below", 0.5))
    except (TypeError, ValueError):
        review_below = 0.5
    return {
        "mode": mode, "stages": stages,
        "fallback_collection_id": fallback, "review_below": review_below,
    }


def validate_policy(raw) -> list[str]:
    """정책 stage 들을 레지스트리 기준으로 검증한다(오류 메시지 리스트, 빈 리스트면 유효)."""
    errors: list[str] = []
    norm = normalize_policy(raw)
    for st in norm["stages"]:
        if st["id"] not in REGISTRY:
            errors.append(f"알 수 없는 라우터: {st['id']}")
    return errors


def _run_stage(stage: dict, doc: RouteInput, ctx: RouteContext | None) -> list[Candidate]:
    """단일 stage 실행 — 미가용/실패 라우터는 빈 후보로 처리(라우팅이 막히지 않게)."""
    r = REGISTRY.get(stage["id"])
    if r is None or not _safe_available(r):
        return []
    try:
        cands = r.route(doc, stage.get("config") or {}, ctx) or []
    except Exception as e:  # noqa: BLE001
        logger.warning("라우터 %s 실행 실패(건너뜀): %s", stage["id"], e)
        return []
    # 점수 0~1 클램프 + collection_id 정수만.
    out: list[Candidate] = []
    for c in cands:
        try:
            cid = int(c.collection_id)
        except (TypeError, ValueError):
            continue
        out.append(Candidate(cid, max(0.0, min(1.0, float(c.score))), c.reason))
    return out


def run_policy(policy, doc: RouteInput, ctx: RouteContext | None = None) -> dict:
    """정책을 실행해 최종 라우팅 결정을 반환한다(순수 함수 — DB 비의존).

    반환: ``{collection_id, confidence, mode, matched_router, fallback_used, review, trace}``.
    - first_match: stage 순서대로, 후보 최고점이 stage.min_confidence 이상이면 그 컬렉션 채택(즉시 종료).
    - weighted_vote: 모든 stage 후보 점수를 컬렉션별 가중 합산해 최댓값 채택. confidence 는 정규화 점수.
    매칭 실패 또는 confidence < review_below 면 fallback_collection_id 로 보내고 review=True 로 표시한다.
    """
    pol = normalize_policy(policy)
    trace: list[dict] = []

    winner_cid: int | None = None
    confidence = 0.0
    matched_router: str | None = None

    if pol["mode"] == "weighted_vote":
        scores: dict[int, float] = {}
        weight_sum = 0.0
        for st in pol["stages"]:
            cands = _run_stage(st, doc, ctx)
            weight_sum += st["weight"]
            for c in cands:
                scores[c.collection_id] = scores.get(c.collection_id, 0.0) + c.score * st["weight"]
            trace.append({
                "router": st["id"],
                "candidates": [
                    {"collection_id": c.collection_id, "score": round(c.score, 4), "reason": c.reason}
                    for c in cands
                ],
            })
        if scores:
            winner_cid = max(scores, key=scores.get)
            # 가중 합 정규화(0~1) — 가중치 총합 기준.
            confidence = scores[winner_cid] / weight_sum if weight_sum > 0 else 0.0
            matched_router = "weighted_vote"
    else:  # first_match
        for st in pol["stages"]:
            cands = _run_stage(st, doc, ctx)
            trace.append({
                "router": st["id"],
                "candidates": [
                    {"collection_id": c.collection_id, "score": round(c.score, 4), "reason": c.reason}
                    for c in cands
                ],
            })
            if winner_cid is not None:
                continue  # 이미 확정 — 남은 stage 는 trace 기록만
            best = max(cands, key=lambda c: c.score, default=None)
            if best is not None and best.score >= st["min_confidence"]:
                winner_cid, confidence, matched_router = best.collection_id, best.score, st["id"]

    confidence = max(0.0, min(1.0, confidence))
    fallback_used = False
    review = False
    final_cid = winner_cid

    if final_cid is None:
        # 매칭 실패 → 폴백(있으면). 폴백도 없으면 None(호출부가 422 처리).
        if pol["fallback_collection_id"] is not None:
            final_cid = pol["fallback_collection_id"]
            fallback_used = True
            review = True
    elif confidence < pol["review_below"]:
        # 매칭은 됐지만 저신뢰 → 검토 대상으로 표시(결정 자체는 유지).
        review = True

    return {
        "collection_id": final_cid,
        "confidence": round(confidence, 4),
        "mode": pol["mode"],
        "matched_router": matched_router,
        "fallback_used": fallback_used,
        "review": review,
        "trace": trace,
    }
