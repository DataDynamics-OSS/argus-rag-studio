# SPDX-License-Identifier: Apache-2.0
"""청킹 — 컬렉션별 전략 교체형(recursive / sentence / paragraph / section / fixed / markdown).

- ``recursive``: 구분자 우선순위(문단 → 줄 → 문장 → 공백)로 ``chunk_size`` 이내로 자른다.
  구조를 최대한 보존하는 범용 기본값.
- ``sentence``: 문장 경계로 나눈 뒤 ``chunk_size`` 이내가 되도록 문장을 그리디로 묶는다.
  문장이 잘리지 않아 FAQ·QA 류에 적합(긴 문장은 recursive 로 폴백).
- ``paragraph``: 빈 줄(문단 경계)로 나눈 뒤 ``chunk_size`` 이내가 되도록 문단을 그리디로 묶는다.
  문단이 잘리지 않아 산문·보고서에 적합(한 문단이 너무 길면 recursive 로 폴백).
- ``section``: 섹션 헤더(마크다운 헤딩·setext·번호/장·절·Chapter 등)를 경계로 나누고,
  각 청크에 상위 섹션 경로(breadcrumb)를 메타로 단다. 헤딩 외에도 일반 텍스트의 번호 헤더를
  인식해 markdown 보다 넓게 적용된다(헤더 없는 평문은 recursive 와 유사).
- ``fixed``: 구분자 무시, 고정 윈도우로 하드 컷. 균일 길이가 필요할 때.
- ``markdown``: 마크다운 구조 인식 — 표·코드블록을 원자 단위로 보존(중간에서 안 자름)하고,
  헤딩을 경계로 쓰며, 각 청크에 상위 헤딩 컨텍스트(breadcrumb)를 덧붙인다. ``layout``/``docai``/
  ``vlm`` 파서가 만든 Markdown(표·헤딩)과 짝을 이룬다. 마크다운 구조가 없는 텍스트는 recursive 와 동일.

크기 단위(``unit``)는 ``char``(문자, 기본) 또는 ``token``(tiktoken cl100k_base) 이다. ``token`` 은
임베딩 모델의 토큰 윈도우(보통 512)에 맞춰 자르는 데 유리하다(언어별 문자↔토큰 비율 차이 흡수).
tiktoken 미설치 시 char 로 폴백한다. ``recursive``/``sentence``/``fixed`` 는 마지막에 ``overlap``
만큼 인접 청크 꼬리를 덧붙이되, 꼬리 시작을 *문장→단어 경계로 스냅* 해 부분 단어/문장 조각을 피한다
(스마트 절단). ``markdown`` 은 헤딩 컨텍스트로 연속성을 확보하므로 오버랩을 적용하지 않는다.
"""

import logging
import math
import os
import re

from app.core.config import settings

logger = logging.getLogger(__name__)

_SEPARATORS = ["\n\n", "\n", ". ", "。", " "]

STRATEGIES = ("auto", "recursive", "sentence", "paragraph", "section", "fixed", "markdown", "semantic")
UNITS = ("char", "token")

# 마크다운 구조 인식 청킹 — 청크에 상위 헤딩 경로(breadcrumb)를 덧붙일지
_MD_PREPEND_HEADINGS = True
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")


# ── 길이 측정(Sizer) — char ↔ token 교체 ──────────────────────────────────────
class _CharSizer:
    """문자 기준 측정/분할(기본)."""

    def count(self, s: str) -> int:
        return len(s)

    def windows(self, text: str, size: int) -> list[str]:
        return [text[i : i + size] for i in range(0, len(text), size)]

    def tail(self, text: str, n: int) -> str:
        return text[-n:]


class _TokenSizer:
    """토큰(tiktoken) 기준 측정/분할 — 임베딩 토큰 윈도우에 맞춤."""

    def __init__(self, enc) -> None:
        self._enc = enc

    def count(self, s: str) -> int:
        return len(self._enc.encode(s))

    def windows(self, text: str, size: int) -> list[str]:
        ids = self._enc.encode(text)
        return [self._enc.decode(ids[i : i + size]) for i in range(0, len(ids), size)]

    def tail(self, text: str, n: int) -> str:
        ids = self._enc.encode(text)
        return self._enc.decode(ids[-n:]) if ids else text


_CHAR_SIZER = _CharSizer()
_token_sizer: _TokenSizer | None = None
_token_unavailable = False


def _make_sizer(unit: str):
    """단위에 맞는 Sizer 반환. token 인데 tiktoken 미설치면 char 로 폴백(경고 1회)."""
    global _token_sizer, _token_unavailable
    if (unit or "char").lower() != "token":
        return _CHAR_SIZER
    if _token_sizer is not None:
        return _token_sizer
    if _token_unavailable:
        return _CHAR_SIZER
    try:
        import tiktoken

        _token_sizer = _TokenSizer(tiktoken.get_encoding("cl100k_base"))
        return _token_sizer
    except Exception as e:  # 미설치/로딩 실패 → char 폴백
        logger.warning("토큰 사이징 사용 불가 → char 폴백: %s", e)
        _token_unavailable = True
        return _CHAR_SIZER


def _split_recursive(text: str, chunk_size: int, separators: list[str], sizer=_CHAR_SIZER) -> list[str]:
    """구분자를 우선순위대로 적용해 chunk_size(단위: sizer) 이내 조각으로 자른다."""
    if sizer.count(text) <= chunk_size:
        return [text]
    if not separators:  # 더 이상 쪼갤 구분자가 없으면 hard-cut(단위 윈도우)
        return sizer.windows(text, chunk_size)

    sep = separators[0]
    rest = separators[1:]
    parts = text.split(sep) if sep else list(text)
    last = len(parts) - 1

    chunks: list[str] = []
    buf = ""
    for idx, part in enumerate(parts):
        # 구분자는 조각 사이에만 재부착(마지막 조각 뒤엔 원문에 없으므로 붙이지 않음)
        piece = part + sep if (sep and idx < last) else part
        if sizer.count(buf) + sizer.count(piece) <= chunk_size:
            buf += piece
        else:
            if buf:
                chunks.append(buf)
            if sizer.count(piece) > chunk_size:
                chunks.extend(_split_recursive(piece, chunk_size, rest, sizer))
                buf = ""
            else:
                buf = piece
    if buf:
        chunks.append(buf)
    return [c.strip() for c in chunks if c.strip()]


# 오버랩 스마트 절단 — 꼬리 시작을 깨끗한 경계로 스냅(부분 단어/문장 조각 방지)
_OVERLAP_SENT_RE = re.compile(r"(?:[.。!?！？]\s+|\n)")
_OVERLAP_WORD_RE = re.compile(r"\s")


def _smart_overlap_start(tail: str) -> str:
    """오버랩 꼬리의 시작을 경계로 스냅한다.

    원시 꼬리는 단어/문장 중간에서 잘려 깨진 조각("…면 검색이 됩니다")이 되기 쉽다. 경계 우선순위:
    ① 문장 경계(첫 문장 종결자 다음 — 경계에 인접한 *완결 문장* 만 남김),
    ② 단어 경계(첫 공백 다음 — 부분 단어 제거), ③ 경계 없으면 원시 꼬리 그대로(폴백).
    """
    t = tail.strip()
    if not t:
        return ""
    m = _OVERLAP_SENT_RE.search(t)
    if m and m.end() < len(t):
        snapped = t[m.end():].lstrip()
        if snapped:
            return snapped
    w = _OVERLAP_WORD_RE.search(t)
    if w and w.end() < len(t):
        snapped = t[w.end():].lstrip()
        if snapped:
            return snapped
    return t


def _apply_overlap(chunks: list[str], overlap: int, sizer=_CHAR_SIZER) -> list[str]:
    """인접 청크 앞에 직전 청크의 꼬리(overlap 단위)를 덧붙인다(경계로 스마트 스냅)."""
    if overlap <= 0 or len(chunks) <= 1:
        return chunks
    out = [chunks[0]]
    for i in range(1, len(chunks)):
        tail = _smart_overlap_start(sizer.tail(chunks[i - 1], overlap))
        out.append((f"{tail} {chunks[i]}").strip() if tail else chunks[i])
    return out


def _split_fixed(text: str, chunk_size: int, sizer=_CHAR_SIZER) -> list[str]:
    """구분자 무시, 고정 윈도우(단위: sizer)로 하드 컷."""
    return [c.strip() for c in sizer.windows(text, chunk_size) if c.strip()]


# ── 문장 분리(한국어 인식) ────────────────────────────────────────────────────
# 영어 약어/이니셜 — 마침표 뒤를 문장 끝으로 오인하지 않도록 보호
_ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "st", "vs", "etc", "e.g", "i.e", "fig",
    "vol", "no", "pp", "inc", "ltd", "co", "jr", "sr", "approx", "dept", "univ",
}
# 종결 부호(다국어) + 닫는 따옴표/괄호(선택) 뒤의 공백 위치 = 문장 경계 후보
_SENT_BOUNDARY_RE = re.compile(r"(?<=[.!?。！？…])[\"'”’」』）)\]]*(?=\s)")
_kss_split = None  # kss.split_sentences 캐시(또는 False=미사용)
# kss 는 한국어 문장 분리가 정확하지만, mecab 백엔드가 없으면 pecab(순수 파이썬)로 동작해
# 매우 느리다(측정: 약 1,000자당 6초+). 이 길이를 넘으면 빠른 규칙 기반으로 폴백해
# semantic/sentence 인제스천이 멈추지 않게 한다(대부분의 실제 문서는 규칙 기반으로 처리).
# kss 정확도를 빠르게 쓰려면 mecab(python-mecab-kor 또는 konlpy.tag.Mecab) 설치를 권장.
# 길이 임계는 settings.ingestion_max_kss_chars (설정 UI 에서 조정).


def _get_kss():
    global _kss_split
    if _kss_split is None:
        try:
            import kss

            _kss_split = kss.split_sentences
            logger.info("문장 분리: kss 사용(한국어 정확)")
        except Exception as e:  # 미설치/로딩 실패 → 규칙 기반 폴백
            logger.info("문장 분리: 규칙 기반 폴백(kss 미사용: %s)", e)
            _kss_split = False
    return _kss_split or None


def _regex_sentences(text: str) -> list[str]:
    """규칙 기반 문장 분리(폴백) — 종결 부호+공백 경계. 소수점·약어·이니셜은 분리하지 않는다."""
    sents: list[str] = []
    last = 0
    for m in _SENT_BOUNDARY_RE.finditer(text):
        prev = text[:m.start()]
        word = re.split(r"[\s(\[\"']", prev)[-1].rstrip(".").lower() if prev else ""
        if word in _ABBREV or (len(word) == 1 and word.isascii() and word.isalpha()):
            continue  # 약어/이니셜 → 문장 끝 아님
        sents.append(text[last:m.end()])
        last = m.end()
    if last < len(text):
        sents.append(text[last:])
    # 부호 없는 문장도 줄바꿈으로 분리
    out: list[str] = []
    for s in sents:
        out.extend(s.split("\n"))
    return [s.strip() for s in out if s.strip()]


def _kss_call(splitter, text: str) -> list[str]:
    """kss 호출 — num_workers=1 로 멀티프로세싱 폭주(스레드·프로세스 폭증)를 막는다.
    구버전 등으로 num_workers 인자를 모르면 기본 호출로 폴백."""
    try:
        return splitter(text, num_workers=1)
    except TypeError:
        return splitter(text)


def _split_into_sentences(text: str) -> list[str]:
    """문장 분리 — kss(있으면 한국어 정확) 우선, 없으면 규칙 기반 폴백.

    대용량 텍스트(ingestion_max_kss_chars 초과)는 kss(pecab) 지연을 피해 규칙 기반으로 처리한다.
    """
    max_kss = settings.ingestion_max_kss_chars
    if len(text) <= max_kss:
        splitter = _get_kss()
        if splitter is not None:
            try:
                return [s for s in _kss_call(splitter, text) if s and s.strip()]
            except Exception as e:  # kss 가 특정 입력에서 실패 → 규칙 폴백
                logger.warning("kss 문장 분리 실패 → 규칙 폴백: %s", e)
    else:
        # 대용량은 kss(pecab) 로드/처리 자체가 느리므로 호출하지 않고 바로 규칙 기반.
        logger.info("문장 분리: 텍스트 %d자(>%d) → 규칙 기반(지연 방지)", len(text), max_kss)
    return _regex_sentences(text)


def _split_sentence(text: str, chunk_size: int, sizer=_CHAR_SIZER) -> list[str]:
    """문장 경계로 나눈 뒤 chunk_size 이내로 문장을 그리디로 묶는다(문장 보존)."""
    sentences = _split_into_sentences(text)

    chunks: list[str] = []
    buf = ""
    for s in sentences:
        if sizer.count(s) > chunk_size:
            if buf:
                chunks.append(buf.strip())
                buf = ""
            chunks.extend(_split_recursive(s, chunk_size, _SEPARATORS, sizer))
        elif sizer.count(f"{buf} {s}".strip()) <= chunk_size:
            buf = f"{buf} {s}".strip()
        else:
            if buf:
                chunks.append(buf.strip())
            buf = s
    if buf:
        chunks.append(buf.strip())
    return [c for c in chunks if c]


# ── paragraph(문단 단위) ──────────────────────────────────────────────────────
def _split_paragraphs_raw(text: str) -> list[str]:
    """빈 줄(연속 줄바꿈)을 경계로 문단을 나눈다. 단일 줄바꿈은 같은 문단으로 본다."""
    parts = re.split(r"\n[ \t]*\n+", text)
    return [p.strip() for p in parts if p.strip()]


def _split_paragraph(text: str, chunk_size: int, sizer=_CHAR_SIZER) -> list[str]:
    """문단 경계로 나눈 뒤 chunk_size 이내가 되도록 문단을 그리디로 묶는다(문단 보존).

    한 문단이 chunk_size 를 넘으면 그 문단만 recursive 로 폴백 분할한다."""
    paras = _split_paragraphs_raw(text)
    chunks: list[str] = []
    buf = ""
    for p in paras:
        if sizer.count(p) > chunk_size:
            if buf:
                chunks.append(buf.strip())
                buf = ""
            chunks.extend(_split_recursive(p, chunk_size, _SEPARATORS, sizer))
        elif not buf:
            buf = p
        elif sizer.count(buf) + sizer.count(p) + 2 <= chunk_size:  # "\n\n"
            buf = f"{buf}\n\n{p}"
        else:
            chunks.append(buf.strip())
            buf = p
    if buf:
        chunks.append(buf.strip())
    return [c for c in chunks if c]


# ── section(섹션/헤딩 단위) ───────────────────────────────────────────────────
# 일반 텍스트의 섹션 헤더 패턴(마크다운 헤딩 외에도 번호·장/절·키워드 헤더를 인식).
# setext: 본문 줄 아래에 ===(레벨1) 또는 ---(레벨2) 밑줄.
_SETEXT_RE = re.compile(r"^\s{0,3}(=+|-+)\s*$")
# 번호 헤더: "1." / "1.2" / "2.3.1" 로 시작하는 짧은 단독 라인(목록 항목 오인을 줄이려 길이 제한).
_NUM_HEADER_RE = re.compile(r"^\s{0,3}(\d+(?:\.\d+)*)\.?\s+\S.{0,78}$")
# 키워드 헤더: Chapter/Section/Part/Appendix(영문) 또는 제N장·제N절·제N편·제N부(한글).
_KEYWORD_HEADER_RE = re.compile(
    r"^\s{0,3}(?:(?:chapter|section|part|appendix)\s+[\divxlc]+|제\s*\d+\s*[장절편부])\b.{0,78}$",
    re.IGNORECASE,
)


def _section_header(line: str, next_line: str | None) -> tuple[int, str, int] | None:
    """라인이 섹션 헤더면 (level, title, lines_consumed) 반환, 아니면 None.

    title 은 원본 헤더 라인 그대로(오프셋 보존). setext 는 밑줄까지 2줄 소비한다."""
    m = _HEADING_RE.match(line)
    if m:
        return len(m.group(1)), line.strip(), 1
    if next_line is not None and line.strip() and _SETEXT_RE.match(next_line):
        return (1 if next_line.strip().startswith("=") else 2), line.strip(), 2
    nm = _NUM_HEADER_RE.match(line)
    if nm:
        return nm.group(1).count(".") + 1, line.strip(), 1  # 점 개수로 깊이(1. →1, 1.2 →2)
    if _KEYWORD_HEADER_RE.match(line):
        return 1, line.strip(), 1
    return None


def _section_blocks(text: str) -> list[tuple[int, str, str]]:
    """텍스트를 섹션으로 분해: (level, header, body).

    header 는 헤더 라인(선두 preamble 은 ""), body 는 다음 헤더 전까지의 본문."""
    lines = text.split("\n")
    n = len(lines)
    blocks: list[tuple[int, str, str]] = []
    cur_level, cur_header = 0, ""
    body: list[str] = []

    def flush() -> None:
        nonlocal body
        txt = "\n".join(body).strip()
        if cur_header or txt:
            blocks.append((cur_level, cur_header, txt))
        body = []

    i = 0
    while i < n:
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < n else None
        hit = _section_header(line, nxt)
        if hit is not None:
            flush()
            cur_level, cur_header, consumed = hit
            i += consumed
            continue
        body.append(line)
        i += 1
    flush()
    return blocks


def _split_section(text: str, chunk_size: int, sizer=_CHAR_SIZER) -> list[tuple[str, str | None]]:
    """섹션(헤더) 경계로 분할. 반환: ``[(chunk_text, section_path)]``.

    작은 섹션은 같은 상위 경로 안에서 그리디로 묶고, 한 섹션이 chunk_size 를 넘으면 본문을
    recursive 로 쪼개되 헤더를 각 조각 앞에 반복(컨텍스트 유지)한다. ``section_path`` 는
    상위 헤더들을 'A > B > C' 로 이은 breadcrumb(헤더의 ``#``·번호 표기는 그대로 둔다)."""
    blocks = _section_blocks(text)
    stack: list[tuple[int, str]] = []
    out: list[tuple[str, str | None]] = []
    buf = ""
    buf_path: str | None = None

    def flush() -> None:
        nonlocal buf, buf_path
        if buf.strip():
            out.append((buf.strip(), buf_path))
        buf, buf_path = "", None

    for level, header, body in blocks:
        if header:
            stack[:] = [h for h in stack if h[0] < level]
            stack.append((level, header))
        path = " > ".join(h for _, h in stack) or None
        sec_text = "\n".join(x for x in (header, body) if x).strip()
        if not sec_text:
            continue
        if sizer.count(sec_text) > chunk_size:
            flush()
            if header and body:
                # 본문을 (chunk_size - 헤더) 폭으로 쪼개 헤더를 각 조각에 반복(헤더+조각 ≤ chunk_size)
                head = f"{header}\n"
                room = max(1, chunk_size - sizer.count(head))
                for piece in _split_recursive(body, room, _SEPARATORS, sizer):
                    out.append((f"{head}{piece}".strip(), path))
            else:
                for piece in _split_recursive(body or header, chunk_size, _SEPARATORS, sizer):
                    if piece.strip():
                        out.append((piece.strip(), path))
            continue
        # 보통/작은 섹션 → 같은 경로면 그리디로 묶어 잔챙이 청크를 줄인다
        if buf and buf_path == path and sizer.count(buf) + sizer.count(sec_text) + 2 <= chunk_size:
            buf = f"{buf}\n\n{sec_text}"
        else:
            flush()
            buf, buf_path = sec_text, path
    flush()
    return out


# ── markdown(구조 인식) ───────────────────────────────────────────────────────
def _is_table_line(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


_SEP_CELL = re.compile(r"^:?-{2,}:?$")  # 마크다운 표 구분선 셀(예: ---, :--:)


def _clean_table_rows(text: str) -> str:
    """마크다운 표에서 빈칸 위주 행을 정리한다 — 양식 문서(빈 셀 많은 표)의 검색 노이즈 감소.

    - 내용 셀이 하나도 없는 행(``| | | |``)은 삭제한다.
    - 내용이 있는 행은 빈 셀을 제거(압축)해 내용 셀만 남긴다 → 밀집 표(빈 셀 없음)는 그대로.
    - 구분선(``| --- | --- |``) 행은 삭제한다(압축으로 그리드가 깨지고 검색 내용이 없음).
    - 표가 아닌 줄은 전혀 건드리지 않는다.

    렌더 그리드보다 검색 텍스트 품질이 목적이라, 압축으로 열 정렬이 달라지는 것은 허용한다.
    """
    out: list[str] = []
    for line in text.split("\n"):
        if not _is_table_line(line):
            out.append(line)
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        # 내용 셀만 추출(빈 셀·구분선 셀 제외). 없으면 행 삭제(빈 행·구분선 행).
        content = [c for c in cells if c and not _SEP_CELL.match(c)]
        if content:
            out.append("| " + " | ".join(content) + " |")
    return "\n".join(out)


def _md_blocks(text: str) -> list[tuple[str, str, int]]:
    """마크다운을 블록으로 분해: (kind, content, level).

    kind: ``heading``(level=1~6) / ``table`` / ``code`` / ``prose``. 표·코드펜스는 원자 블록으로
    묶어 중간 분할을 막는다. 연속한 일반 줄은 하나의 prose 블록으로 모은다(빈 줄 보존)."""
    lines = text.split("\n")
    blocks: list[tuple[str, str, int]] = []
    prose: list[str] = []
    n = len(lines)
    i = 0

    def flush_prose() -> None:
        if prose:
            txt = "\n".join(prose).strip()
            if txt:
                blocks.append(("prose", txt, 0))
            prose.clear()

    while i < n:
        line = lines[i]
        if line.lstrip().startswith("```"):  # 코드펜스 — 닫힐 때까지 원자 블록
            flush_prose()
            fence = [line]
            i += 1
            while i < n and not lines[i].lstrip().startswith("```"):
                fence.append(lines[i])
                i += 1
            if i < n:
                fence.append(lines[i])
                i += 1
            blocks.append(("code", "\n".join(fence), 0))
            continue
        m = _HEADING_RE.match(line)
        if m:
            flush_prose()
            blocks.append(("heading", line.strip(), len(m.group(1))))
            i += 1
            continue
        if _is_table_line(line):  # 표 — 연속 파이프 줄을 원자 블록으로
            flush_prose()
            tbl = []
            while i < n and _is_table_line(lines[i]):
                tbl.append(lines[i].rstrip())
                i += 1
            blocks.append(("table", "\n".join(tbl).strip(), 0))
            continue
        prose.append(line)
        i += 1
    flush_prose()
    return blocks


def _strip_leading_headings(body: str) -> str:
    """본문 앞쪽의 연속된 헤딩·빈 줄을 제거한다(crumb 중복 방지용)."""
    lines = body.split("\n")
    k = 0
    while k < len(lines) and (lines[k].strip() == "" or _HEADING_RE.match(lines[k])):
        k += 1
    return "\n".join(lines[k:]).strip()


def _split_table_rows(table: str, chunk_size: int, sizer=_CHAR_SIZER) -> list[str]:
    """오버사이즈 표를 행 단위로 쪼개되 헤더+구분선을 각 조각에 반복(유효한 표 유지)."""
    rows = table.split("\n")
    if len(rows) <= 2:
        return [table]
    header, body = rows[:2], rows[2:]
    head_len = sizer.count("\n".join(header))
    out: list[str] = []
    cur, cur_len = list(header), head_len
    for r in body:
        if cur_len + sizer.count(r) + 1 > chunk_size and len(cur) > 2:
            out.append("\n".join(cur))
            cur, cur_len = list(header), head_len
        cur.append(r)
        cur_len += sizer.count(r) + 1
    if len(cur) > 2:
        out.append("\n".join(cur))
    return out or [table]


def _split_markdown(text: str, chunk_size: int, sizer=_CHAR_SIZER) -> list[str]:
    """마크다운 구조를 보존하며 청킹(표·코드 원자 보존 + 헤딩 경계 + 헤딩 컨텍스트 전파).

    헤딩은 *지연 배치* 한다: 본문 블록이 올 때 함께 배치해, 청크 끝에 헤딩만 매달리는 것을 막는다.
    """
    blocks = _md_blocks(text)
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0
    stack: list[tuple[int, str]] = []  # 현재 활성 헤딩 [(level, line)]
    buf_stack: list[tuple[int, str]] = []  # buf 시작 시점의 헤딩 스택
    pending: list[str] = []  # 아직 본문에 붙지 않은 헤딩들

    def flush() -> None:
        nonlocal buf, buf_len, buf_stack
        body = "\n\n".join(buf).strip()
        buf, buf_len = [], 0
        if not body:
            buf_stack = []
            return
        if _MD_PREPEND_HEADINGS and buf_stack:
            crumb = [h for _, h in buf_stack]
            rest = _strip_leading_headings(body)
            body = "\n".join(crumb) + (f"\n\n{rest}" if rest else "")
        chunks.append(body)
        buf_stack = []

    def add(unit: str) -> None:
        nonlocal buf, buf_len, buf_stack
        if not buf:
            buf_stack = list(stack)
        buf.append(unit)
        buf_len += sizer.count(unit) + 2

    for kind, content, level in blocks:
        if kind == "heading":
            stack[:] = [h for h in stack if h[0] < level]
            stack.append((level, content))
            pending.append(content)  # 본문이 올 때까지 보류(매달림 방지)
            continue

        # 본문 블록 — 큰 블록은 분할, 표/코드는 원자(오버사이즈만 행 분할)
        if kind == "prose" and sizer.count(content) > chunk_size:
            pieces = _split_recursive(content, chunk_size, _SEPARATORS, sizer)
        elif kind == "table" and sizer.count(content) > chunk_size:
            pieces = _split_table_rows(content, chunk_size, sizer)
        else:
            pieces = [content]

        for idx, piece in enumerate(pieces):
            lead = pending if idx == 0 else []  # 보류 헤딩은 첫 조각에만 부착
            need = sum(sizer.count(h) + 2 for h in lead) + sizer.count(piece)
            if buf and buf_len + need > chunk_size:
                flush()
            for h in lead:
                add(h)
            add(piece)
        pending = []
    flush()  # 끝에 남은 pending(본문 없는 헤딩)은 버린다
    return [c for c in chunks if c.strip()]


# ── 위치 메타데이터 ───────────────────────────────────────────────────────────
def _locate_spans(source: str, chunks: list[str]) -> list[tuple[int | None, int | None]]:
    """각 청크의 (char_start, char_end) 를 소스에서 순방향 검색해 계산(부분문자열 가정).

    overlap/breadcrumb 로 정확한 부분문자열이 아닐 수 있어 앞부분으로 폴백 검색하며, 못 찾으면 None."""
    spans: list[tuple[int | None, int | None]] = []
    cursor = 0
    for ch in chunks:
        key = ch.strip()
        pos = source.find(key, cursor) if key else -1
        if pos < 0 and len(key) > 40:  # 정규화 차이 폴백: 앞 40자
            pos = source.find(key[:40], cursor)
        if pos < 0:
            spans.append((None, None))
        else:
            spans.append((pos, pos + len(key)))
            cursor = pos + 1
    return spans


def _chunk_section_path(chunk: str) -> str | None:
    """마크다운 청크 선두의 헤딩(breadcrumb) 라인을 'A > B > C' 경로로 추출."""
    heads: list[str] = []
    for ln in chunk.split("\n"):
        if _HEADING_RE.match(ln):
            heads.append(re.sub(r"^\s*#+\s*", "", ln).strip())
        elif ln.strip() == "":
            continue
        else:
            break
    return " > ".join(h for h in heads if h) or None


# ── 품질 가드 ─────────────────────────────────────────────────────────────────
# 최소 청크 크기 비율 — 이보다 작은 청크는 노이즈로 보고 이웃에 병합(한도 내).
def _min_chunk(chunk_size: int) -> int:
    return max(1, int(chunk_size * settings.ingestion_min_chunk_ratio))


def _merge_small(
    chunks: list[str], spans: list, sizer, min_size: int, max_size: int
) -> tuple[list[str], list]:
    """min_size 미만 청크를 이웃에 병합(노이즈 벡터 방지). 단 합쳐도 max_size 를 넘지 않을 때만.

    텍스트와 (start,end) 스팬을 함께 병합한다(스팬 합집합). 병합 못 한 작은 청크는 그대로 둔다."""
    if len(chunks) <= 1:
        return chunks, spans
    out_t: list[str] = []
    out_s: list = []
    for ch, sp in zip(chunks, spans):
        if (
            out_t
            and sizer.count(ch) < min_size
            and sizer.count(out_t[-1]) + sizer.count(ch) + 1 <= max_size
        ):
            out_t[-1] = (out_t[-1] + " " + ch).strip()
            if sp[1] is not None:
                out_s[-1] = (out_s[-1][0], sp[1])
        else:
            out_t.append(ch)
            out_s.append(sp)
    # 첫 청크가 작으면 다음과 병합(한도 내)
    if (
        len(out_t) > 1
        and sizer.count(out_t[0]) < min_size
        and sizer.count(out_t[0]) + sizer.count(out_t[1]) + 1 <= max_size
    ):
        out_t[1] = (out_t[0] + " " + out_t[1]).strip()
        if out_s[0][0] is not None:
            out_s[1] = (out_s[0][0], out_s[1][1])
        out_t, out_s = out_t[1:], out_s[1:]
    return out_t, out_s


def auto_chunk_strategy(text: str) -> str:
    """파싱 결과 내용으로 청킹 전략을 자동 선택한다(auto).

    마크다운 표(헤더+구분선) 또는 헤딩이 있으면 ``markdown``, 아니면 ``recursive``.
    (``semantic`` 은 임베딩 비용이 큰 의도적 선택이라 자동 선택하지 않는다.)"""
    lines = text.split("\n")
    has_heading = any(_HEADING_RE.match(ln) for ln in lines)
    has_table = sum(1 for ln in lines if _is_table_line(ln)) >= 2
    return "markdown" if (has_heading or has_table) else "recursive"


def chunk_text_with_meta(
    text: str, chunk_size: int, overlap: int, strategy: str = "recursive", unit: str = "char"
) -> list[dict]:
    """청킹 결과를 위치 메타데이터와 함께 반환한다.

    각 항목: ``{text, section_path, char_start, char_end, char_count, token_count}``.
    ``section_path`` 는 markdown/section 전략에서 헤딩(섹션) 경로, char offset 은 best-effort(못 찾으면 None).
    ``auto`` 면 내용으로 markdown/recursive 를 자동 선택한다.

    품질 가드(markdown 외): ① 예산 캡 — base 를 ``chunk_size - overlap`` 으로 잘라 최종 청크가
    ``chunk_size`` 를 넘지 않게 한다. ② 작은 청크 병합 — ``chunk_size`` 의 10% 미만 조각을 이웃에 병합."""
    # 표 빈칸 정리 등 본문 보강은 인제스천 파이프라인의 post_parse transform 으로 이관됨
    # (app/ingestion/transforms). chunk_body 가 청킹 전에 적용한다.
    strat = (strategy or "recursive").lower()
    if strat == "auto":
        strat = auto_chunk_strategy(text)
    sizer = _make_sizer(unit)
    is_token = (unit or "char").lower() == "token"

    if strat == "markdown":
        # 구조 우선 — 표·헤딩 보존이 핵심이라 예산 캡/병합 가드는 적용하지 않는다.
        chunks = _split_markdown(text, chunk_size, sizer)
        cores = [_strip_leading_headings(c) or c for c in chunks]
        spans = _locate_spans(text, cores)
        sections = [_chunk_section_path(c) for c in chunks]
    elif strat == "section":
        # 섹션 경계 보존 — markdown 과 마찬가지로 구조 우선이라 오버랩/예산 캡을 쓰지 않는다.
        pairs = _split_section(text, chunk_size, sizer)
        chunks = [t for t, _ in pairs]
        sections = [p for _, p in pairs]
        spans = _locate_spans(text, chunks)
    else:
        base_size = max(1, chunk_size - overlap) if overlap > 0 else chunk_size  # 예산 캡
        if strat == "fixed":
            base = _split_fixed(text, base_size, sizer)
        elif strat == "sentence":
            base = _split_sentence(text, base_size, sizer)
        elif strat == "paragraph":
            base = _split_paragraph(text, base_size, sizer)
        else:
            base = _split_recursive(text, base_size, _SEPARATORS, sizer)
        spans = _locate_spans(text, base)  # overlap 적용 전(부분문자열)에 offset 계산
        base, spans = _merge_small(base, spans, sizer, _min_chunk(chunk_size), chunk_size)
        chunks = _apply_overlap(base, overlap, sizer)
        sections = [None] * len(chunks)

    out: list[dict] = []
    for ch, (st, en), section in zip(chunks, spans, sections):
        out.append({
            "text": ch,
            "section_path": section,
            "char_start": st,
            "char_end": en,
            "char_count": len(ch),
            "token_count": sizer.count(ch) if is_token else None,
        })
    return out


# ── semantic(시맨틱 — 의미 경계 분할) ─────────────────────────────────────────
# 인접 문장 거리의 상위 (100-percentile)% 지점을 의미 경계로 본다(문서별 적응형 임계).
# 임계 백분위는 settings.ingestion_semantic_percentile (설정 UI 에서 조정).


def split_sentences(text: str) -> list[str]:
    """시맨틱 청킹용 문장 분리(공개 API) — kss/규칙 기반."""
    return _split_into_sentences(text)


def _cosine(a, b) -> float:
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct / 100.0
    lo = int(math.floor(k))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _semantic_group(sentences: list[str], embeddings: list, chunk_size: int, sizer) -> list[str]:
    """문장 임베딩의 인접 거리가 임계를 넘는 지점(의미 경계)과 chunk_size 한도로 그룹화한다."""
    n = len(sentences)
    if n <= 1:
        return [s for s in sentences if s.strip()]
    dists = [1.0 - _cosine(embeddings[i], embeddings[i + 1]) for i in range(n - 1)]
    threshold = _percentile(dists, settings.ingestion_semantic_percentile)

    groups: list[str] = []
    cur: list[str] = [sentences[0]]
    cur_len = sizer.count(sentences[0])
    for i in range(1, n):
        s = sentences[i]
        slen = sizer.count(s)
        is_break = dists[i - 1] > threshold  # 의미 경계
        if cur and (is_break or cur_len + slen + 1 > chunk_size):  # 경계 또는 크기 초과
            groups.append(" ".join(cur))
            cur, cur_len = [s], slen
        else:
            cur.append(s)
            cur_len += slen + 1
    if cur:
        groups.append(" ".join(cur))

    # 오버사이즈 그룹(한 문장이 chunk_size 초과 등)은 recursive 로 분할
    out: list[str] = []
    for g in groups:
        if sizer.count(g) > chunk_size:
            out.extend(_split_recursive(g, chunk_size, _SEPARATORS, sizer))
        else:
            out.append(g)
    return [g.strip() for g in out if g.strip()]


def semantic_chunk(
    text: str, sentences: list[str], embeddings: list, chunk_size: int, unit: str = "char"
) -> list[dict]:
    """사전 계산된 문장 임베딩으로 시맨틱 청킹 + 위치 메타데이터를 만든다.

    임베딩(문장별, 컬렉션 임베더로 계산)은 호출 측에서 비동기로 준비해 넘긴다. 반환 형식은
    ``chunk_text_with_meta`` 와 동일하다(품질 가드: chunk_size 캡 + 작은 그룹 병합 적용)."""
    sizer = _make_sizer(unit)
    is_token = (unit or "char").lower() == "token"
    groups = _semantic_group(sentences, embeddings, chunk_size, sizer)
    spans = _locate_spans(text, groups)
    groups, spans = _merge_small(groups, spans, sizer, _min_chunk(chunk_size), chunk_size)
    out: list[dict] = []
    for g, (st, en) in zip(groups, spans):
        out.append({
            "text": g,
            "section_path": None,
            "char_start": st,
            "char_end": en,
            "char_count": len(g),
            "token_count": sizer.count(g) if is_token else None,
        })
    return out


def chunk_text(
    text: str, chunk_size: int, overlap: int, strategy: str = "recursive", unit: str = "char"
) -> list[str]:
    """텍스트를 지정 전략·단위로 청킹한다(청크 문자열만).

    ``chunk_text_with_meta`` 에 위임해 동일한 청킹(품질 가드 포함)을 보장한다.
    unit: ``char``(문자, 기본) | ``token``(tiktoken). token 인데 tiktoken 미설치면 char 로 폴백.
    """
    return [p["text"] for p in chunk_text_with_meta(text, chunk_size, overlap, strategy, unit)]
