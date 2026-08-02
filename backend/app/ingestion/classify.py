# SPDX-License-Identifier: Apache-2.0
"""문서 자동 분류(P2) — 규칙 기반 doc_type + 통제어휘 정규화.

ingest 시점에 비-보안 메타데이터(문서유형·언어 등)를 ``metadata_json`` 에 채워, 검색
필터(P1, retrieval/filterspec.py)가 실제로 쓸 수 있게 한다. **격리 분류(보안등급/DRM)는
다루지 않는다** — 그것은 컬렉션 경계가 담당(knowledge-base-design.md §5).

설계: design/document-classification.md §3(통제어휘)·§4(결정 방법)·§5(스키마). 이 모듈은
규칙(출처메타 → 파일명/확장자) 기반만 — 내용 기반(임베딩/LLM) 분류는 P3 에서 붙인다.

best-effort: 어떤 경우에도 예외를 던지지 않게 호출부에서 감싼다(분류 실패가 인제스천을 막지 않음).
"""

from __future__ import annotations

import math
import os

# 통제어휘(§3). 임의 신규값 금지 — 모르면 other.
DOC_TYPES = {"report", "rfp", "proposal", "presentation", "minutes", "other"}

# 내용 기반 분류(P3)용 유형 앵커 — 각 유형의 의미를 담은 대표 문장. 규칙이 other 로 둔
# 문서의 선두 텍스트 임베딩과 코사인 비교해 유형을 추정한다(에어갭, 학습 불필요).
# other 는 앵커가 없다(폴백). 컬렉션 임베딩 모델로 함께 임베딩해 같은 벡터공간에서 비교.
DOC_TYPE_ANCHORS: dict[str, str] = {
    "report": "분석 결과와 현황을 정리한 보고서. 배경, 분석 내용, 결론과 시사점, 향후 계획.",
    "rfp": "발주 기관이 요구사항을 정의해 제안을 요청하는 제안요청서. 과업 범위, 요구사항 명세, "
           "제출 안내, 평가 기준, 입찰.",
    "proposal": "수주사가 제출하는 사업 제안서. 사업 이해, 수행 방안, 추진 일정, 투입 인력, 견적과 비용.",
    "presentation": "슬라이드 중심의 발표 자료. 목차, 핵심 요약, 도표와 그래프, 페이지별 요점.",
    "minutes": "회의록. 일시와 장소, 참석자, 안건, 논의 내용, 결정 사항, 액션 아이템과 담당자.",
}

# 표기 흔들림 → 코드. "규칙이 아니라 정규화 룩업이 다양성을 흡수"(§4.3).
# 순서 의존: RFP 와 제안서는 둘 다 "제안" 을 포함하므로 rfp 변형을 **먼저** 매칭해야 한다
# (제안요청서 → rfp 가 제안서 → proposal 보다 우선). 위에서부터 first-match-wins.
_DOC_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("rfp", ["제안요청서", "제안요청", "과업지시서", "과업지시", "rfp"]),
    ("proposal", ["제안서", "제안", "proposal"]),
    ("minutes", ["회의록", "미팅노트", "회의결과", "minutes", "mom"]),
    ("presentation", ["발표자료", "발표", "슬라이드", "presentation"]),
    ("report", ["보고서", "결과보고", "현황", "report"]),
]

# 확장자 폴백(파일명 키워드가 없을 때만) — 슬라이드 포맷 → presentation.
_PRESENTATION_EXTS = {".pptx", ".ppt", ".key"}

# 언어 코드 정규화(있을 때만). 표기 흔들림을 ko/en/ja/zh 로 통일.
_LANG_NORMALIZE = {
    "ko": "ko", "kor": "ko", "korean": "ko", "ko-kr": "ko", "한국어": "ko",
    "en": "en", "eng": "en", "english": "en", "en-us": "en", "영어": "en",
    "ja": "ja", "jpn": "ja", "japanese": "ja", "일본어": "ja",
    "zh": "zh", "chi": "zh", "chinese": "zh", "중국어": "zh",
}


def normalize_doc_type(raw) -> str | None:
    """표기/별칭 → 통제어휘 코드. 인식 못 하면 None(임의 신규값 금지)."""
    if not raw:
        return None
    s = str(raw).strip().lower()
    if s in DOC_TYPES:
        return s
    for code, variants in _DOC_TYPE_RULES:
        if any(s == v.lower() for v in variants):
            return code
    return None


def normalize_language(raw) -> str | None:
    """언어 표기 → ko/en/ja/zh. 인식 못 하면 None."""
    if not raw:
        return None
    return _LANG_NORMALIZE.get(str(raw).strip().lower())


def _classify_by_filename(filename: str | None) -> str | None:
    """파일명에 통제어휘 변형이 들어 있으면 해당 코드(우선순위 순 first-match)."""
    name = (filename or "").lower()
    for code, variants in _DOC_TYPE_RULES:
        if any(v.lower() in name for v in variants):
            return code
    return None


def _resolve_doc_type(filename: str | None, meta: dict) -> tuple[str, str, float]:
    """(doc_type, doc_type_source, confidence) 결정.

    우선순위(§4): 출처/사람 확정값 보존 → 파일명 규칙 → 확장자 폴백 → other.
    이전 자동추정값(source=rule/embedding/llm)은 신뢰하지 않고 재도출한다(reindex 멱등).
    """
    raw = meta.get("doc_type")
    raw_src = meta.get("doc_type_source")
    # 1) 확정값 보존 — 사람/출처가 준 값(또는 source 미표기 외부 제공). 정규화 후 사용.
    if raw and raw_src in (None, "source", "human"):
        code = normalize_doc_type(raw)
        if code:
            try:
                conf = float(meta.get("doc_type_confidence", 1.0))
            except (TypeError, ValueError):
                conf = 1.0
            return code, (raw_src or "source"), conf
    # 2) 파일명 키워드 규칙
    code = _classify_by_filename(filename)
    if code:
        return code, "rule", 0.7
    # 3) 확장자 폴백(슬라이드 포맷)
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in _PRESENTATION_EXTS:
        return "presentation", "rule", 0.5
    # 4) 미분류 — other 도 명시 저장(검색/검토 큐가 찾을 수 있게)
    return "other", "rule", 0.0


def _cosine(a: list[float], b: list[float]) -> float:
    """코사인 유사도(순수 파이썬). 빈/영벡터는 0.0."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def classify_by_anchors(
    doc_vec: list[float],
    anchor_vecs: dict[str, list[float]],
    threshold: float,
) -> tuple[str, float] | None:
    """문서 벡터와 가장 유사한 유형 앵커를 (code, score) 로 반환. threshold 미만이면 None.

    벡터는 호출부가 컬렉션 임베딩 모델로 만든다(이 함수는 서버 비의존 — 테스트 용이).
    """
    best_code, best_score = None, -1.0
    for code, vec in anchor_vecs.items():
        s = _cosine(doc_vec, vec)
        if s > best_score:
            best_code, best_score = code, s
    if best_code is None or best_score < threshold:
        return None
    return best_code, best_score


def needs_content_refinement(meta: dict) -> bool:
    """규칙 결과를 내용 기반으로 보강할지 — other 이고 사람/출처 확정이 아닐 때만."""
    return (
        meta.get("doc_type") == "other"
        and meta.get("doc_type_source") not in ("source", "human")
    )


def classify_document(
    filename: str | None,
    source_meta: dict | None = None,
    extracted_meta: dict | None = None,
) -> dict:
    """문서 분류 결과를 ``metadata_json`` 에 merge 할 dict 로 반환한다.

    ``source_meta`` 는 현재까지의 metadata_json(출처 제공 + 파일 속성 추출 병합). doc_type 은
    여기서 결정/정규화하고, language 는 정규화, dept/source_system 은 출처 제공값을 통과시킨다.
    보안등급/DRM 류 키는 절대 생성하지 않는다.
    """
    meta = source_meta or {}
    extracted = extracted_meta or {}
    out: dict = {}

    code, src, conf = _resolve_doc_type(filename, meta)
    out["doc_type"] = code
    out["doc_type_source"] = src
    out["doc_type_confidence"] = conf

    # language — 정규화(있을 때만)
    lang = normalize_language(meta.get("language") or extracted.get("language"))
    if lang:
        out["language"] = lang

    # dept / source_system — 출처 제공값 통과(정규화는 P2 범위 밖). 값 있을 때만.
    for key in ("dept", "source_system"):
        val = meta.get(key)
        if val:
            out[key] = str(val)[:200]

    return out
