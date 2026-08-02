# SPDX-License-Identifier: Apache-2.0
"""PII 보강 transform — 등록된 정규식 규칙으로 본문 개인정보를 마스킹(post_parse).

규칙은 'PII Rule' 관리 화면(rag_pii_rules)에서 등록하고, 오케스트레이터가 enabled 규칙을
``ctx["pii_rules"]`` 로 주입한다. 이 transform 은 DB 에 직접 접근하지 않는다(순수·테스트 용이).
"""

from app.ingestion.transforms.base import Transform, register_transform
from app.pii import checks
from app.pii.redact import apply_rules
from app.pii.sandbox import run_function


@register_transform
class PiiRegexTransform(Transform):
    id = "pii_regex"
    label = "PII 정규식 마스킹"
    description = "등록된 정규식 규칙으로 본문의 개인정보를 마스킹합니다(파싱 후). 규칙은 'PII Rule' 화면에서 관리. 본문 보강에서 규칙을 선택합니다(비우면 전체)."
    phase = "post_parse"
    config_schema = {
        # rule_id 는 빌더에서 규칙 콤보로 선택(전용 UI). 비우면 enabled 규칙 전체 적용.
        "on_error": {"type": "string", "label": "실패 시(skip|fail)"},
    }

    def apply(self, data, cfg: dict, ctx=None):
        rules = (ctx or {}).get("pii_rules") or []
        rid = (cfg or {}).get("rule_id")
        if rid:
            rules = [r for r in rules if r.get("rule_id") == rid]
            # 특정 규칙 선택 시에만 마스크 오버라이드(전체는 규칙별 등록 마스크 사용).
            mask = (cfg or {}).get("mask")
            if mask:
                rules = [{**r, "mask": mask} for r in rules]
        else:
            # 하위호환: categories(쉼표) 가 있으면 분류 필터.
            cats_raw = (cfg or {}).get("categories") or ""
            cats = [c.strip() for c in str(cats_raw).split(",") if c.strip()]
            if cats:
                rules = [r for r in rules if r.get("category") in cats]
        return apply_rules(data, rules)


# ── 확장 함수 — 정규식으로 표현 못 하는 체크섬/형식 검증 기반 마스킹(단계 1개 + 함수 선택) ──────

# function 선택값 → (기본 마스크, 마스킹 함수)
_BUILTINS = {
    "card": ("[CARD]", checks.mask_cards),    # 신용카드 (Luhn 검증)
    "bizno": ("[BIZNO]", checks.mask_bizno),  # 사업자등록번호 (검증식)
    "rrn": ("[RRN]", checks.mask_rrn),        # 주민/외국인등록번호 (검증)
}


@register_transform
class PiiBuiltinTransform(Transform):
    id = "pii_builtin"
    label = "PII 확장 함수"
    description = "체크섬·형식 검증 기반 마스킹(정규식보다 오탐↓). 본문 보강에서 함수(신용카드·사업자등록번호·주민/외국인등록번호)를 선택합니다."
    phase = "post_parse"
    config_schema = {
        # function 은 빌더에서 콤보로 선택(전용 UI). card | bizno | rrn
        "mask": {"type": "string", "label": "마스크(비우면 기본값)"},
        "on_error": {"type": "string", "label": "실패 시(skip|fail)"},
    }

    def apply(self, data, cfg: dict, ctx=None):
        fn = (cfg or {}).get("function")
        spec = _BUILTINS.get(fn)
        if spec is None:
            return data  # 함수 미선택 — no-op
        default_mask, masker = spec
        return masker(data, (cfg or {}).get("mask") or default_mask)


@register_transform
class PiiFunctionTransform(Transform):
    id = "pii_function"
    label = "PII 사용자 함수"
    description = "관리자가 작성한 사용자 정의 함수(redact(text))를 샌드박스에서 실행해 본문을 마스킹합니다. 함수는 'PII Rule > 사용자 함수'에서 관리. on_error=fail 권장."
    phase = "post_parse"
    config_schema = {
        # function_id 는 빌더에서 함수 콤보로 선택(전용 UI). 비우면 enabled 함수 전체 실행.
        "on_error": {"type": "string", "label": "실패 시(skip|fail)"},
    }

    def apply(self, data, cfg: dict, ctx=None):
        funcs = (ctx or {}).get("pii_functions") or []
        fid = (cfg or {}).get("function_id")
        if fid:
            funcs = [f for f in funcs if f.get("function_id") == fid]
        for f in funcs:
            out, err = run_function(f["code"], data, int(f.get("timeout_ms") or 2000))
            if err is not None:
                raise RuntimeError(f"PII 함수 '{f.get('name')}' 실행 실패: {err}")
            data = out
        return data
