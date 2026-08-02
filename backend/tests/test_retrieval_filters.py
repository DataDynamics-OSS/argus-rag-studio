# SPDX-License-Identifier: Apache-2.0
"""검색 메타데이터 필터(P1) 단위 테스트 — DSL 검증 + SQL WHERE 변환 + 보안 회귀.

DB 없이 검증 가능한 순수 로직(필드 화이트리스트, build_where 의 SQL 절 생성)을 대상으로 한다.
설계: design/search-metadata-filter.md
"""

import pytest
from sqlalchemy.dialects import postgresql

from app.retrieval.filterspec import (
    FILTERABLE_FIELDS,
    UnknownFilterField,
    build_where,
    validate_fields,
)
from app.retrieval.schemas import FilterCond, FilterOp


def _sql(clause) -> str:
    """WHERE 절을 PostgreSQL 방언으로 컴파일(값 인라인)해 문자열로."""
    return str(clause.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    ))


# ── 화이트리스트 / fail-closed ────────────────────────────────────────────────

def test_unknown_field_rejected():
    with pytest.raises(UnknownFilterField):
        validate_fields([FilterCond(field="nope", value="x")])


def test_known_fields_pass():
    conds = [FilterCond(field="doc_type", value="report"),
             FilterCond(field="dept", value="영업본부")]
    validate_fields(conds)  # 예외 없으면 통과


def test_security_keys_not_filterable():
    """보안/DRM 류 키는 레지스트리에 없어야 한다(필터로 격리 금지 — fail-open 차단)."""
    for key in ("security", "security_level", "보안등급", "drm", "DRM"):
        assert key not in FILTERABLE_FIELDS
        with pytest.raises(UnknownFilterField):
            validate_fields([FilterCond(field=key, value="대외비")])


# ── build_where: 빈 입력 ──────────────────────────────────────────────────────

def test_empty_filters_return_none():
    assert build_where(None) is None
    assert build_where([]) is None


def test_eq_value_none_is_skipped():
    # 값이 없는 eq 는 무시 → 결과 절 없음
    assert build_where([FilterCond(field="doc_type", op=FilterOp.EQ, value=None)]) is None


# ── build_where: 연산자별 SQL ─────────────────────────────────────────────────

def test_eq_builds_jsonb_extract_equality():
    sql = _sql(build_where([FilterCond(field="doc_type", value="report")]))
    assert "metadata_json" in sql
    assert "JSONB" in sql.upper()
    assert "->>" in sql
    assert "doc_type" in sql
    assert "report" in sql


def test_in_builds_in_clause():
    sql = _sql(build_where([
        FilterCond(field="doc_type", op=FilterOp.IN, value=["report", "minutes"])
    ]))
    assert "IN " in sql.upper()
    assert "report" in sql and "minutes" in sql


def test_range_builds_bounds():
    sql = _sql(build_where([
        FilterCond(field="created", op=FilterOp.RANGE, gte="2026-01-01", lte="2026-12-31")
    ]))
    assert ">=" in sql and "<=" in sql
    assert "2026-01-01" in sql and "2026-12-31" in sql


def test_multiple_conditions_are_anded():
    sql = _sql(build_where([
        FilterCond(field="doc_type", value="report"),
        FilterCond(field="dept", value="영업본부"),
    ]))
    assert " AND " in sql.upper()


def test_build_where_raises_on_unknown_field():
    with pytest.raises(UnknownFilterField):
        build_where([FilterCond(field="작성자비밀", value="x")])
