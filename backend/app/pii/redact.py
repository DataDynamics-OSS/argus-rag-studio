# SPDX-License-Identifier: Apache-2.0
"""PII 정규식 마스킹 — DB 비의존 순수 로직(transform·테스트 엔드포인트 공용).

규칙은 plain dict 목록으로 받는다: ``{rule_id?, name?, category?, pattern, flags, mask}``.
잘못된(컴파일 실패) 규칙은 건너뛴다 — 규칙은 등록 시점에 검증되지만 방어적으로 처리.
"""

import re


def parse_flags(flags: str) -> int:
    f = 0
    s = (flags or "").lower()
    if "i" in s:
        f |= re.IGNORECASE
    if "m" in s:
        f |= re.MULTILINE
    if "s" in s:
        f |= re.DOTALL
    return f


def apply_rules(text: str, rules: list[dict]) -> str:
    """enabled 규칙들을 순서대로 적용해 마스킹한 텍스트를 반환."""
    for r in rules:
        try:
            text = re.sub(r["pattern"], r.get("mask") or "[REDACTED]", text, flags=parse_flags(r.get("flags", "")))
        except re.error:
            continue
    return text


def apply_rules_with_stats(text: str, rules: list[dict]) -> tuple[str, list[dict], list[str]]:
    """마스킹 + 규칙별 매치 수 + 컴파일 실패 rule_id 목록(테스트용)."""
    matches: list[dict] = []
    invalid: list[str] = []
    for r in rules:
        try:
            flags = parse_flags(r.get("flags", ""))
            count = len(re.findall(r["pattern"], text, flags=flags))
            if count:
                matches.append({
                    "rule_id": r.get("rule_id", ""), "name": r.get("name", ""),
                    "category": r.get("category", ""), "count": count,
                })
            text = re.sub(r["pattern"], r.get("mask") or "[REDACTED]", text, flags=flags)
        except re.error:
            invalid.append(r.get("rule_id", ""))
    return text, matches, invalid


def validate_pattern(pattern: str, flags: str = "") -> str | None:
    """정규식 컴파일 검증. 유효하면 None, 아니면 오류 메시지."""
    try:
        re.compile(pattern, parse_flags(flags))
        return None
    except re.error as e:
        return str(e)
