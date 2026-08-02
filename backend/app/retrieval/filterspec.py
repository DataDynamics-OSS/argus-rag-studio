# SPDX-License-Identifier: Apache-2.0
"""검색 메타데이터 필터 — 통제 필드 레지스트리 + SQL WHERE 변환(P1).

비-보안 메타데이터(문서유형·부서·기간 등)로 검색을 좁히기 위한 모듈. 보안등급/DRM 은
이 경로로 격리하지 않는다(격리는 컬렉션 경계 — knowledge-base-design.md §5). 설계 전반은
``design/search-metadata-filter.md`` 참고.

핵심:
  - 필터 가능한 필드는 ``FILTERABLE_FIELDS`` 화이트리스트로만 제한(미등록 → 거부 = fail-closed).
  - 값은 ``rag_documents.metadata_json``(Text) 을 JSONB 로 캐스팅해 ``->>`` 로 추출 후 비교.
  - 검색의 세 지점(렉시컬 SQL · pgvector ANN · 하이드레이션)이 동일 WHERE 절을 공유한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, cast
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.elements import ColumnElement

from app.documents.models import RagDocument
from app.retrieval.schemas import FilterCond, FilterOp


@dataclass(frozen=True)
class FilterField:
    """필터 가능한 필드 1건 — metadata_json 안의 키와 스코프/타입."""

    key: str            # metadata_json 안의 JSON 키
    scope: str          # "document" (P1) | "chunk" (P3 확장용)
    type: str           # "str" | "date" | "int"


# 통제된 필터 가능 필드. 보안/DRM 키는 의도적으로 절대 등록하지 않는다(§0 가드레일).
# 확장은 이 테이블 갱신으로만 — 자유 필드 금지.
FILTERABLE_FIELDS: dict[str, FilterField] = {
    "doc_type": FilterField("doc_type", "document", "str"),
    "dept": FilterField("dept", "document", "str"),
    "language": FilterField("language", "document", "str"),
    "source_system": FilterField("source_system", "document", "str"),
    "format": FilterField("format", "document", "str"),
    "created": FilterField("created", "document", "date"),
    "modified": FilterField("modified", "document", "date"),
}


class UnknownFilterField(ValueError):
    """등록되지 않은 필드를 필터로 요청했을 때(라우터가 400 으로 매핑)."""


def validate_fields(conds: list[FilterCond]) -> None:
    """필터 조건의 필드가 모두 화이트리스트에 있는지 검사. 없으면 즉시 예외(fail-closed)."""
    for c in conds:
        if c.field not in FILTERABLE_FIELDS:
            raise UnknownFilterField(
                f"필터 불가 필드: {c.field!r} (허용: {sorted(FILTERABLE_FIELDS)})"
            )


def _col(field: FilterField):
    """metadata_json(Text) → JSONB → ``->> key`` 텍스트 추출식. 문서에 키가 없으면 NULL."""
    return cast(RagDocument.metadata_json, JSONB).op("->>")(field.key)


def build_where(conds: list[FilterCond] | None) -> ColumnElement | None:
    """FilterCond 목록 → RagDocument 대상 SQLAlchemy WHERE 절(AND 결합).

    조건이 없으면 ``None`` 을 반환한다(필터 없음). 미등록 필드는 ``UnknownFilterField``.
    반환 절은 ``rag_documents`` 가 FROM/JOIN 에 포함된 모든 쿼리(렉시컬·벡터·하이드레이션)에서
    재사용한다.
    """
    if not conds:
        return None
    validate_fields(conds)
    clauses: list[ColumnElement] = []
    for c in conds:
        field = FILTERABLE_FIELDS[c.field]
        col = _col(field)
        if c.op == FilterOp.EQ:
            if c.value is None:
                continue
            clauses.append(col == str(c.value))
        elif c.op == FilterOp.IN:
            values = [str(v) for v in (c.value or []) if v is not None]
            if values:
                clauses.append(col.in_(values))
        elif c.op == FilterOp.RANGE:
            if c.gte is not None:
                clauses.append(col >= str(c.gte))
            if c.lte is not None:
                clauses.append(col <= str(c.lte))
    return and_(*clauses) if clauses else None
