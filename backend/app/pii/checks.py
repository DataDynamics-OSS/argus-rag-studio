# SPDX-License-Identifier: Apache-2.0
"""PII 내장 함수 — 정규식으로 표현 못 하는 체크섬/형식 검증 기반 마스킹(DB 비의존, 순수).

후보를 정규식으로 느슨히 찾은 뒤 검증을 통과한 것만 마스킹한다 → 정규식 단독보다 오탐이 적다.
``pii_card_luhn`` / ``pii_bizno`` / ``pii_rrn`` transform 이 사용한다.
"""

import re

# 후보 패턴(느슨) — 검증으로 거른다. 앞뒤 숫자 경계로 더 긴 숫자열의 일부 매칭을 방지.
_CARD_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")
_BIZNO_RE = re.compile(r"(?<!\d)\d{3}-?\d{2}-?\d{5}(?!\d)")
_RRN_RE = re.compile(r"(?<!\d)\d{6}-?\d{7}(?!\d)")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def luhn_ok(d: str) -> bool:
    """신용카드 Luhn(modulo 10) 검증."""
    if not d.isdigit() or not (13 <= len(d) <= 19):
        return False
    total, alt = 0, False
    for ch in reversed(d):
        n = int(ch)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


def bizno_ok(d: str) -> bool:
    """사업자등록번호(10자리) 검증식."""
    if len(d) != 10 or not d.isdigit():
        return False
    w = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    s = sum(int(d[i]) * w[i] for i in range(9))
    s += (int(d[8]) * 5) // 10
    check = (10 - (s % 10)) % 10
    return check == int(d[9])


def rrn_ok(d: str) -> bool:
    """주민/외국인등록번호(13자리) — 월·일·성별 + 체크섬 검증.

    주의: 2020년 이후 부여분은 뒤 6자리가 임의화되어 체크섬이 맞지 않을 수 있다(미탐 가능).
    완전 재현율이 필요하면 형식 정규식 규칙을 함께 쓰십시오.
    """
    if len(d) != 13 or not d.isdigit():
        return False
    mm, dd, g = int(d[2:4]), int(d[4:6]), int(d[6])
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return False
    if g not in (1, 2, 3, 4, 5, 6, 7, 8):  # 내국인 1~4, 외국인 5~8
        return False
    w = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    s = sum(int(d[i]) * w[i] for i in range(12))
    return (11 - (s % 11)) % 10 == int(d[12])


def _mask_validated(text: str, pattern: re.Pattern, ok, mask: str) -> str:
    def repl(m: re.Match) -> str:
        return mask if ok(_digits(m.group(0))) else m.group(0)
    return pattern.sub(repl, text)


def mask_cards(text: str, mask: str = "[CARD]") -> str:
    return _mask_validated(text, _CARD_RE, luhn_ok, mask)


def mask_bizno(text: str, mask: str = "[BIZNO]") -> str:
    return _mask_validated(text, _BIZNO_RE, bizno_ok, mask)


def mask_rrn(text: str, mask: str = "[RRN]") -> str:
    return _mask_validated(text, _RRN_RE, rrn_ok, mask)
