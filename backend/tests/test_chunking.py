# SPDX-License-Identifier: Apache-2.0
"""청킹 전략 테스트 — 특히 markdown 구조 인식(표·헤딩 보존)."""

import re

import pytest

from app.ingestion.chunking import STRATEGIES, chunk_text, chunk_text_with_meta

MD = """# 2026 연간 보고서

## 개요

이 보고서는 2026 회계연도의 분기별 실적을 요약한다. 회사는 견조한 성장을 이어갔다.

## 분기 실적

아래 표는 분기별 매출과 성장률이다.

| 분기 | 매출 | 성장률 |
| --- | --- | --- |
| Q1 | 100 | 5% |
| Q2 | 120 | 20% |
| Q3 | 150 | 25% |
| Q4 | 180 | 20% |

## 전망

내년에도 두 자릿수 성장을 목표로 한다.
"""


def test_markdown_is_registered():
    assert "markdown" in STRATEGIES


def test_markdown_keeps_table_intact():
    # 표(110자+)보다 작은 chunk_size 라도 표는 중간에서 잘리지 않는다
    chunks = chunk_text(MD, chunk_size=120, overlap=20, strategy="markdown")
    assert any(
        "| 분기 | 매출 | 성장률 |" in c and "| Q1 | 100 | 5% |" in c and "| Q4 | 180 | 20% |" in c
        for c in chunks
    ), "표 헤더+전체 행이 한 청크에 온전해야 함"


def test_markdown_prepends_heading_context_without_duplication():
    chunks = chunk_text(MD, chunk_size=120, overlap=20, strategy="markdown")
    # 표 청크가 소속 섹션 헤딩 경로를 포함
    table_chunk = next(c for c in chunks if "| Q1 | 100 | 5% |" in c)
    assert "# 2026 연간 보고서" in table_chunk
    assert "## 분기 실적" in table_chunk
    # 어떤 청크에도 동일 헤딩 라인이 중복되지 않는다
    for c in chunks:
        heads = [ln for ln in c.split("\n") if re.match(r"#{1,6} ", ln)]
        assert len(heads) == len(set(heads)), f"헤딩 중복: {c!r}"


def test_markdown_oversized_table_splits_with_header_repeated():
    big = "| a | b |\n| --- | --- |\n" + "\n".join(f"| r{i} | v{i} |" for i in range(40))
    chunks = chunk_text(big, chunk_size=120, overlap=0, strategy="markdown")
    assert len(chunks) > 1
    assert all("| a | b |" in c for c in chunks), "분할된 각 조각이 헤더를 반복해야 함"


def test_markdown_on_plaintext_behaves_safely():
    # 마크다운 구조가 없는 평문도 안전하게 청킹(예외/빈 결과 없음)
    chunks = chunk_text("문장 하나. 문장 둘. " * 30, chunk_size=100, overlap=10, strategy="markdown")
    assert len(chunks) >= 1
    assert all(c.strip() for c in chunks)


def test_other_strategies_still_work():
    text = "문단 하나.\n\n문단 둘.\n\n" + "가나다라마바사 " * 50
    for strat in ("recursive", "sentence", "fixed"):
        chunks = chunk_text(text, chunk_size=100, overlap=10, strategy=strat)
        assert len(chunks) >= 1 and all(c.strip() for c in chunks)


# ── 토큰 기반 사이징 ──────────────────────────────────────────────────────────
def _has(mod: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(mod) is not None


@pytest.mark.skipif(not _has("tiktoken"), reason="tiktoken 미설치")
def test_token_unit_respects_token_budget():
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    text = "안녕하세요 RAG 스튜디오입니다. " * 30  # 한국어(문자당 토큰 많음)
    chunks = chunk_text(text, chunk_size=64, overlap=0, strategy="recursive", unit="token")
    assert len(chunks) > 1
    # 모든 청크가 토큰 예산(64) 이내여야 한다
    assert all(len(enc.encode(c)) <= 64 for c in chunks)


@pytest.mark.skipif(not _has("tiktoken"), reason="tiktoken 미설치")
def test_token_fixed_windows_exact():
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    text = "가나다라마바사아자차카타파하 " * 40
    chunks = chunk_text(text, chunk_size=50, overlap=0, strategy="fixed", unit="token")
    # fixed+token 은 토큰 윈도우라 마지막 외 각 조각이 정확히 50토큰
    assert all(len(enc.encode(c)) <= 50 for c in chunks)
    assert len(chunks) > 1


# ── 오버랩 스마트 절단 ────────────────────────────────────────────────────────
def test_smart_overlap_snaps_to_boundary():
    from app.ingestion.chunking import _smart_overlap_start

    # 부분 단어 시작 → 단어 경계로 스냅(앞 조각 제거)
    assert _smart_overlap_start("면 검색이 됩니다") == "검색이 됩니다"
    # 문장 경계 → 경계에 인접한 완결 문장만
    assert _smart_overlap_start("환불됩니다. 단어가 달라도") == "단어가 달라도"
    # 줄바꿈 경계
    assert _smart_overlap_start("끝.\n다음 시작") == "다음 시작"
    # 경계 없으면 그대로(폴백)
    assert _smart_overlap_start("한단어만") == "한단어만"
    assert _smart_overlap_start("   ") == ""


def test_overlap_chunks_do_not_start_mid_word():
    text = (
        "환불 정책은 다음과 같습니다. 구매 후 7일 이내 가능합니다. "
        "영수증이 필요합니다. 반품 배송비는 고객 부담입니다. 교환은 동일 상품만 가능합니다."
    )
    chunks = chunk_text(text, chunk_size=45, overlap=15, strategy="recursive", unit="char")
    assert len(chunks) > 1
    # 오버랩이 붙은 청크(0번 제외)가 공백/깨진 조각으로 시작하지 않음
    for c in chunks[1:]:
        assert c and not c[0].isspace()


def test_unknown_unit_falls_back_to_char():
    # 미지원 단위는 char 로 폴백(예외 없음)
    chunks = chunk_text("hello world " * 20, chunk_size=30, overlap=0, strategy="recursive", unit="weird")
    assert len(chunks) >= 1 and all(c.strip() for c in chunks)


# ── 시맨틱 청킹 ───────────────────────────────────────────────────────────────
def test_semantic_group_splits_at_meaning_change():
    from app.ingestion.chunking import _make_sizer, _semantic_group

    sents = ["회사 소개입니다", "우리는 성장합니다", "직원이 많습니다",
             "제품은 우수합니다", "가격은 합리적입니다", "품질이 좋습니다"]
    a, b = [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]  # 앞 3 vs 뒤 3 의미 전환
    groups = _semantic_group(sents, [a, a, a, b, b, b], 1000, _make_sizer("char"))
    assert len(groups) == 2
    assert "회사 소개입니다" in groups[0] and "직원이 많습니다" in groups[0]
    assert "제품은 우수합니다" in groups[1] and "품질이 좋습니다" in groups[1]


def test_semantic_chunk_respects_size_and_meta():
    from app.ingestion.chunking import semantic_chunk

    sents = ["문장 하나입니다", "문장 둘입니다", "문장 셋입니다", "문장 넷입니다"]
    v = [1.0, 0.0]
    embs = [v, v, v, v]  # 모두 유사 → 의미 경계 없음, 크기로만 분할
    pieces = semantic_chunk(" ".join(sents), sents, embs, chunk_size=20, unit="char")
    assert len(pieces) >= 2  # chunk_size=20 로 크기 분할
    for p in pieces:
        assert set(p) >= {"text", "char_start", "char_end", "char_count"}
        assert p["char_count"] == len(p["text"])


def test_auto_chunk_strategy_detects_structure():
    from app.ingestion.chunking import auto_chunk_strategy

    assert auto_chunk_strategy("# 제목\n\n본문입니다.") == "markdown"
    assert auto_chunk_strategy("| a | b |\n| --- | --- |\n| 1 | 2 |") == "markdown"
    assert auto_chunk_strategy("그냥 평범한 문장. 표도 헤딩도 없습니다.") == "recursive"


def test_auto_chunk_text_routes():
    # auto 로 호출하면 내용에 따라 markdown/recursive 로 라우팅(표 보존)
    md = "# 보고서\n\n| 분기 | 매출 |\n| --- | --- |\n| Q1 | 100 |\n| Q2 | 120 |"
    chunks = chunk_text(md, chunk_size=200, overlap=0, strategy="auto", unit="char")
    assert any("| 분기 | 매출 |" in c and "| Q2 | 120 |" in c for c in chunks)  # 표 온전


def test_semantic_single_sentence_safe():
    from app.ingestion.chunking import _make_sizer, _semantic_group

    assert _semantic_group(["한 문장뿐"], [[1.0, 0.0]], 100, _make_sizer("char")) == ["한 문장뿐"]


# ── 품질 가드 ─────────────────────────────────────────────────────────────────
def test_budget_cap_overlap_does_not_exceed_chunk_size():
    import importlib.util

    if importlib.util.find_spec("tiktoken") is None:
        pytest.skip("tiktoken 미설치")
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    text = "안녕하세요 RAG 스튜디오입니다. 예산 가드를 검증합니다. " * 15
    # 오버랩이 있어도 최종 청크가 chunk_size(토큰)를 넘지 않아야 함
    chunks = chunk_text(text, chunk_size=64, overlap=16, strategy="recursive", unit="token")
    assert len(chunks) > 1
    assert all(len(enc.encode(c)) <= 64 for c in chunks)


def test_small_chunk_merged_not_standalone():
    text = "첫 번째 문장은 충분히 길어서 한 청크를 채웁니다 그리고 더 이어집니다. 끝."
    chunks = chunk_text(text, chunk_size=40, overlap=0, strategy="recursive", unit="char")
    # 아주 짧은 조각("끝.")이 독립 청크로 남지 않고 이웃에 병합됨
    assert all(len(c) >= 4 for c in chunks)


def test_merge_respects_budget():
    # 병합이 chunk_size 를 넘기지 않아야(한도 내 병합만)
    text = "가나다라마바사아자차카타파하 " * 10 + "끝."
    chunks = chunk_text(text, chunk_size=30, overlap=0, strategy="recursive", unit="char")
    assert all(len(c) <= 30 + 4 for c in chunks)  # +여유(병합 공백 등)


# ── 한국어 문장 분리 ──────────────────────────────────────────────────────────
def test_regex_sentences_protects_abbrev_and_decimal():
    from app.ingestion.chunking import _regex_sentences

    text = "김 박사는 3.14를 좋아한다. 그는 Dr. Kim이라 불린다. 환불은 7일 이내 가능합니다."
    sents = _regex_sentences(text)
    # 소수점(3.14)·약어(Dr.)에서 오분리하지 않는다
    assert "그는 Dr. Kim이라 불린다." in sents
    assert any("3.14" in s for s in sents)
    assert len(sents) == 3


def test_regex_sentences_splits_on_newline():
    from app.ingestion.chunking import _regex_sentences

    # 종결 부호 없이 줄바꿈만으로도 분리
    assert _regex_sentences("첫 줄\n둘째 줄\n셋째 줄") == ["첫 줄", "둘째 줄", "셋째 줄"]


def test_split_into_sentences_kss_or_fallback():
    from app.ingestion.chunking import _split_into_sentences

    text = "그는 Dr. Kim이라 불린다. 환불은 7일 이내 가능합니다."
    sents = _split_into_sentences(text)  # kss 있으면 kss, 없으면 규칙
    assert "그는 Dr. Kim이라 불린다." in sents
    assert "환불은 7일 이내 가능합니다." in sents


def test_sentence_strategy_keeps_sentences_whole():
    text = "첫 문장입니다. 두 번째 문장입니다. 세 번째 문장입니다. 네 번째 문장입니다."
    chunks = chunk_text(text, chunk_size=30, overlap=0, strategy="sentence", unit="char")
    # 각 청크가 문장 중간에서 잘리지 않음(마침표로 끝나거나 마지막 문장)
    assert len(chunks) > 1
    for c in chunks:
        assert c.strip()


# ── 청크 위치 메타데이터 ──────────────────────────────────────────────────────
def test_meta_recursive_offsets():
    text = "환불 정책입니다. 7일 이내 가능합니다. 영수증 필요합니다. 반품비 고객부담입니다. 교환 가능합니다."
    pieces = chunk_text_with_meta(text, chunk_size=40, overlap=10, strategy="recursive", unit="char")
    assert len(pieces) > 1
    for p in pieces:
        assert set(p) >= {"text", "section_path", "char_start", "char_end", "char_count"}
        assert p["char_count"] == len(p["text"])
        assert p["section_path"] is None  # 비마크다운은 섹션 없음
    # offset 이 잡힌 청크는 소스의 해당 구간과 일치
    p0 = pieces[0]
    assert p0["char_start"] == 0
    assert text[p0["char_start"]:p0["char_end"]] in text


def test_meta_markdown_section_path():
    md = "# 회사 규정\n\n## 휴가\n\n연차는 15일 부여됩니다.\n\n## 환불\n\n7일 이내 환불 가능합니다."
    pieces = chunk_text_with_meta(md, chunk_size=60, overlap=0, strategy="markdown", unit="char")
    # 모든 청크가 헤딩 경로(section_path)를 가진다
    assert all(p["section_path"] for p in pieces)
    joined = " ".join(p["section_path"] for p in pieces)
    assert "회사 규정" in joined
    assert any(">" in p["section_path"] for p in pieces)  # 'A > B' 경로 형식


def test_meta_token_count_present_in_token_unit():
    import importlib.util

    if importlib.util.find_spec("tiktoken") is None:
        pytest.skip("tiktoken 미설치")
    pieces = chunk_text_with_meta("토큰 카운트 테스트 " * 20, chunk_size=32, overlap=0, strategy="recursive", unit="token")
    assert all(p["token_count"] is not None and p["token_count"] <= 32 for p in pieces)


# ── paragraph(문단 단위) ──────────────────────────────────────────────────────
def test_paragraph_and_section_registered():
    assert "paragraph" in STRATEGIES
    assert "section" in STRATEGIES


def test_paragraph_keeps_paragraphs_whole():
    paras = [f"문단{i} 내용입니다 채움 채움." for i in range(6)]
    text = "\n\n".join(paras)
    chunks = chunk_text(text, chunk_size=40, overlap=0, strategy="paragraph")
    assert len(chunks) >= 2  # 여러 문단이 묶이되 chunk_size 로 여러 청크
    # 모든 원본 문단이 어떤 청크엔가 온전히 포함(중간 절단 없음)
    for p in paras:
        assert any(p in c for c in chunks), f"문단이 잘림: {p!r}"


def test_paragraph_oversized_falls_back_to_recursive():
    # 빈 줄이 없는 단일 거대 문단 → chunk_size 초과분은 recursive 로 폴백 분할
    big = "가나다라마바사아자차카타 " * 30
    chunks = chunk_text(big, chunk_size=50, overlap=0, strategy="paragraph")
    assert len(chunks) > 1
    assert all(len(c) <= 50 + 5 for c in chunks)  # +여유(병합 공백 등)


# ── section(섹션/헤딩 단위) ───────────────────────────────────────────────────
SECTION_DOC = """서론 문단입니다.

# 1장 개요

개요 본문입니다.

## 1.1 배경

배경 설명 본문입니다.

# 2장 방법

방법 본문입니다.
"""


def test_section_splits_on_headings_with_path():
    pieces = chunk_text_with_meta(SECTION_DOC, chunk_size=60, overlap=0, strategy="section")
    # 배경 청크의 섹션 경로가 상위 헤딩(1장 개요 > 1.1 배경)을 포함
    bg = next(p for p in pieces if "배경 설명" in p["text"])
    assert bg["section_path"] is not None
    assert "1장 개요" in bg["section_path"]
    assert "1.1 배경" in bg["section_path"]
    assert ">" in bg["section_path"]  # 'A > B' 경로 형식


def test_section_detects_numbered_headers_without_markdown():
    # 마크다운 '#' 이 없어도 번호 헤더(1. / 2.)를 섹션 경계로 인식
    text = "1. 총칙\n\n이 규정의 목적을 정한다.\n\n2. 적용범위\n\n전 직원에게 적용한다."
    pieces = chunk_text_with_meta(text, chunk_size=80, overlap=0, strategy="section")
    paths = [p["section_path"] for p in pieces]
    assert any(pp and "총칙" in pp for pp in paths)
    assert any(pp and "적용범위" in pp for pp in paths)


def test_section_oversized_repeats_header():
    body = "가나다라마바사아자차카타파하 " * 20
    text = f"# 큰 섹션\n\n{body}"
    pieces = chunk_text_with_meta(text, chunk_size=80, overlap=0, strategy="section")
    assert len(pieces) > 1
    # 분할된 각 조각이 헤더를 반복(섹션 컨텍스트 유지)
    assert all("# 큰 섹션" in p["text"] for p in pieces)


def test_section_on_plaintext_behaves_safely():
    # 헤더가 전혀 없는 평문도 안전하게 청킹(예외/빈 결과 없음)
    chunks = chunk_text("그냥 평범한 문장입니다. " * 20, chunk_size=80, overlap=0, strategy="section")
    assert len(chunks) >= 1
    assert all(c.strip() for c in chunks)
