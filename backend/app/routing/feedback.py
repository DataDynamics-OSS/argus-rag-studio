# SPDX-License-Identifier: Apache-2.0
"""수정 피드백 루프(Phase 3 마지막 조각) — 수동 재배정 내역에서 규칙을 제안한다.

검토 큐에서 사람이 재배정(corrected)한 결정들을 신호(확장자·파일명 토큰·doc_type·
소스 경로)별로 집계해, 같은 신호가 같은 컬렉션으로 반복 수정되면(지지도·순도 임계)
해당 규칙 라우터의 규칙으로 제안한다. 반영은 활성 정책의 새 버전 생성(append-only —
언제든 롤백 가능)이라 안전하다.

신호 추출·집계·병합은 순수 함수(테스트 대상), DB 접근은 async 래퍼로 분리한다.
"""

import json
import logging
import posixpath
import re
from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 제안 대상 규칙 라우터 ↔ 규칙의 값 목록 키
_VALUES_KEY = {
    "extension_rule": "extensions",
    "filename_rule": "keywords",
    "path_rule": "patterns",
}
FEEDBACK_ROUTERS = {*_VALUES_KEY, "metadata_match"}

# 파일명 토큰 — 한글·영문·숫자 런을 분리해 자른다("계약서A" → "계약서"+"a" — 접미
# 버전문자에 토큰이 갈라지지 않게). 너무 짧거나 숫자뿐인 토큰·상투어는 신호로 안 쓴다.
_TOKEN_RE = re.compile(r"[가-힣]+|[A-Za-z]+|[0-9]+")
_TOKEN_STOPWORDS = {"final", "copy", "draft", "new", "old", "temp", "test", "file", "doc"}


def extract_signals(filename: str, metadata: dict) -> list[dict]:
    """수정 1건에서 규칙화 가능한 신호들을 뽑는다.

    반환 항목: ``{kind, router, value, field?, storage?}``
      - extension      → extension_rule
      - filename_token → filename_rule(substring)
      - doc_type       → metadata_match(field=doc_type) — 'other'(미분류)는 신호가 아님
      - source_path    → path_rule(prefix, 소스 논리명 한정)
    """
    out: list[dict] = []
    name = (filename or "").strip()
    stem, dot, ext = name.rpartition(".")
    # 확장자 판정 가드: 8자 초과("2026.상반기보고" 류 마침표 포함 이름)나 점으로 시작하는
    # 숨김 파일(stem 이 빈 문자열)은 확장자로 보지 않는다.
    if dot and ext and len(ext) <= 8 and not stem == "":
        out.append({"kind": "extension", "router": "extension_rule", "value": ext.lower()})
    else:
        stem = name
    for tok in _TOKEN_RE.findall(stem):
        low = tok.lower()
        if len(low) < 2 or low.isdigit() or low in _TOKEN_STOPWORDS:
            continue
        out.append({"kind": "filename_token", "router": "filename_rule", "value": low})
    meta = metadata or {}
    doc_type = str(meta.get("doc_type") or "").strip().lower()
    if doc_type and doc_type != "other":
        out.append({
            "kind": "doc_type", "router": "metadata_match",
            "value": doc_type, "field": "doc_type",
        })
    origin_path = str(meta.get("origin_path") or "").replace("\\", "/").strip().lstrip("/")
    folder = posixpath.dirname(origin_path)
    if folder:
        out.append({
            "kind": "source_path", "router": "path_rule",
            "value": folder.lower() + "/",
            "storage": str(meta.get("origin_source") or "") or None,
        })
    return out


def aggregate_corrections(
    corrections: list[dict], min_support: int = 2, min_purity: float = 0.75
) -> list[dict]:
    """수정 내역을 신호별로 집계해 규칙 제안을 만든다.

    corrections 항목: ``{document_name, metadata, collection_id(수정 대상), collection_name}``.
    같은 (신호, 값)이 min_support 회 이상 같은 컬렉션으로 수정됐고 그 비율(순도)이
    min_purity 이상이면 제안한다. 지지도 내림차순 정렬.
    """
    groups: dict[tuple, dict] = {}
    for c in corrections:
        target = c.get("collection_id")
        if target is None:
            continue
        for s in extract_signals(c.get("document_name") or "", c.get("metadata") or {}):
            key = (s["router"], s.get("field"), s.get("storage"), s["value"])
            g = groups.setdefault(key, {"signal": s, "targets": {}, "samples": {}})
            g["targets"][target] = g["targets"].get(target, 0) + 1
            g["samples"].setdefault(target, [])
            if len(g["samples"][target]) < 3 and c.get("document_name"):
                g["samples"][target].append(c["document_name"])
    out: list[dict] = []
    for g in groups.values():
        total = sum(g["targets"].values())
        target, support = max(g["targets"].items(), key=lambda kv: kv[1])
        purity = support / total if total else 0.0
        if support < min_support or purity < min_purity:
            continue
        s = g["signal"]
        out.append({
            "router": s["router"], "kind": s["kind"], "value": s["value"],
            "field": s.get("field"), "storage": s.get("storage"),
            "collection_id": target, "support": support, "total": total,
            "purity": round(purity, 3), "samples": g["samples"].get(target, []),
        })
    out.sort(key=lambda x: (-x["support"], -x["purity"], x["value"]))
    return out


def covered_by_policy(config: dict, suggestion: dict) -> bool:
    """활성 정책에 같은 매핑(값 → 컬렉션)이 이미 있으면 True — 중복 제안을 거른다."""
    router, value = suggestion["router"], suggestion["value"].lower()
    cid = suggestion["collection_id"]
    for st in (config.get("stages") or []):
        if (st.get("id") if isinstance(st, dict) else st) != router:
            continue
        for r in ((st.get("config") or {}).get("rules") or []):
            if r.get("collection_id") != cid:
                continue
            if router == "metadata_match":
                if (r.get("field") == suggestion.get("field")
                        and str(r.get("equals", "")).lower() == value):
                    return True
            else:
                vals = [str(x).lower() for x in (r.get(_VALUES_KEY[router]) or [])]
                if value in vals:
                    return True
    return False


def merge_suggestion(config: dict, suggestion: dict) -> dict:
    """제안을 정책 config 에 병합한 새 dict 를 돌려준다(원본 불변).

    같은 라우터 단계가 있으면 그 규칙 목록에 병합(같은 컬렉션 규칙에 값 추가), 없으면
    단계를 새로 만들어 **내용/LLM 단계 앞**에 끼운다(비용 사다리 유지).
    """
    from app.routing.service import CONTENT_ROUTERS

    router, value = suggestion["router"], suggestion["value"]
    cid = suggestion["collection_id"]
    cfg = deepcopy(config)
    stages: list = cfg.setdefault("stages", [])
    stage = next(
        (s for s in stages if isinstance(s, dict) and s.get("id") == router), None
    )
    if stage is None:
        stage = {"id": router, "config": {}, "weight": 1.0, "min_confidence": 0.5}
        idx = next(
            (i for i, s in enumerate(stages)
             if (s.get("id") if isinstance(s, dict) else s) in CONTENT_ROUTERS),
            len(stages),
        )
        stages.insert(idx, stage)
    stage_cfg = stage.setdefault("config", {})
    rules: list = stage_cfg.setdefault("rules", [])
    if router == "metadata_match":
        field = suggestion.get("field") or "doc_type"
        if not any(
            r.get("field") == field
            and str(r.get("equals", "")).lower() == value.lower()
            and r.get("collection_id") == cid
            for r in rules
        ):
            rules.append({"field": field, "equals": value, "collection_id": cid})
        return cfg
    key = _VALUES_KEY[router]
    storage = suggestion.get("storage")
    rule = next(
        (r for r in rules if r.get("collection_id") == cid
         and (router != "path_rule" or (r.get("storage") or None) == (storage or None))),
        None,
    )
    if rule is None:
        rule = {key: [], "collection_id": cid}
        if router == "path_rule" and storage:
            rule["storage"] = storage
        rules.append(rule)
    vals: list = rule.setdefault(key, [])
    if not any(str(v).lower() == value.lower() for v in vals):
        vals.append(value)
    return cfg


# ---------------------------------------------------------------------------
# DB 래퍼 — 수정 내역 로딩 + 제안 생성 + 정책 반영
# ---------------------------------------------------------------------------

async def load_corrections(session: AsyncSession) -> list[dict]:
    """재배정된 결정(corrected_collection_id 존재) 전부 — 문서명·메타데이터 포함."""
    from app.documents.models import RagDocument
    from app.routing.models import RagRoutingDecision

    rows = (await session.execute(
        select(RagRoutingDecision, RagDocument)
        .join(RagDocument, RagDocument.id == RagRoutingDecision.document_id, isouter=True)
        .where(RagRoutingDecision.corrected_collection_id.isnot(None))
        .order_by(RagRoutingDecision.id.desc())
    )).all()
    out: list[dict] = []
    for d, doc in rows:
        meta: dict = {}
        if doc is not None and doc.metadata_json:
            try:
                parsed = json.loads(doc.metadata_json)
                if isinstance(parsed, dict):
                    meta = parsed
            except (TypeError, ValueError):
                # 메타데이터 손상은 해당 건의 doc_type/경로 신호만 잃는다 — 분석은 계속.
                logger.warning(
                    "수정 내역 메타데이터 파싱 실패(신호 일부 제외): document=%d", d.document_id
                )
        out.append({
            "document_name": doc.name if doc else None,
            "metadata": meta,
            "collection_id": d.corrected_collection_id,
        })
    logger.debug("수정 내역 로딩: %d건(재배정된 결정)", len(out))
    return out


async def build_suggestions(
    session: AsyncSession, min_support: int, min_purity: float
) -> dict:
    """수정 내역 → 규칙 제안(활성 정책에 이미 있는 매핑은 제외). UI 응답 dict."""
    from app.collections.models import RagCollection
    from app.routing import service

    corrections = await load_corrections(session)
    suggestions = aggregate_corrections(corrections, min_support, min_purity)
    policy = await service.get_default_policy(session)
    config = (await service.policy_response(session, policy)).config.model_dump()
    fresh = [s for s in suggestions if not covered_by_policy(config, s)]
    names = dict((await session.execute(
        select(RagCollection.id, RagCollection.name)
    )).all())
    for s in fresh:
        s["collection_name"] = names.get(s["collection_id"])
    logger.debug(
        "피드백 제안 생성: 수정 %d건 → 후보 %d건(정책 커버 %d건 제외, 임계 support≥%d purity≥%.2f)",
        len(corrections), len(fresh), len(suggestions) - len(fresh), min_support, min_purity,
    )
    return {
        "total_corrections": len(corrections),
        "already_covered": len(suggestions) - len(fresh),
        "suggestions": fresh,
    }


async def apply_suggestion(
    session: AsyncSession, suggestion: dict, username: str | None
):
    """제안 1건을 활성 정책에 병합해 새 버전을 만든다(append-only — 롤백 가능).

    Raises:
        ValueError: 병합 결과가 정책 검증에 실패(라우터가 400 으로 변환).
    """
    from app.routing import service
    from app.routing.base import validate_policy
    from app.routing.schemas import RoutingPolicyConfig

    policy = await service.get_default_policy(session)
    config = (await service.policy_response(session, policy)).config.model_dump()
    merged = merge_suggestion(config, suggestion)
    errors = validate_policy(merged)
    if errors:
        # 병합 결과가 스키마/레지스트리 검증에 걸리면 반영하지 않는다(정책 무결성 우선).
        logger.warning(
            "피드백 제안 반영 거부(정책 검증 실패): %s '%s' → %s errors=%s",
            suggestion["router"], suggestion["value"], suggestion["collection_id"], errors,
        )
        raise ValueError("제안 반영 실패: " + "; ".join(errors))
    note = (
        f"feedback: {suggestion['router']} '{suggestion['value']}' → "
        f"컬렉션 {suggestion['collection_id']} (수정 {suggestion.get('support', '?')}건 근거)"
    )
    logger.info(
        "피드백 제안 반영: %s '%s' → 컬렉션 %s (수정 %s건 근거) by %s",
        suggestion["router"], suggestion["value"], suggestion["collection_id"],
        suggestion.get("support", "?"), username,
    )
    return await service.update_config(
        session, policy, RoutingPolicyConfig(**merged), note, username
    )
