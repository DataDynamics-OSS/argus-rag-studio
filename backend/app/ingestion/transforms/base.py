# SPDX-License-Identifier: Apache-2.0
"""인제스천 보강(transform) 레지스트리 — 파이프라인에 끼우는 합성 가능한 단계.

새 보강 추가 = ``Transform`` 서브클래스 1개 + ``@register_transform`` 데코레이터(한 곳). 그러면
introspection API(`GET /ingestion/transforms`)와 UI 빌더에 자동 노출되고, 오케스트레이터·라우터·
프론트 코드는 건드릴 필요가 없다.

phase 로 입출력 계약을 통일한다:
  - ``post_parse`` : 본문 텍스트 단계. ``apply(text: str, cfg, ctx) -> str``
  - ``post_chunk`` : 청크 단계.       ``apply(pieces: list[dict], cfg, ctx) -> list[dict]``
"""

import logging

logger = logging.getLogger(__name__)

PHASES = ("post_parse", "post_chunk")
REGISTRY: dict[str, "Transform"] = {}


class Transform:
    id: str = ""
    label: str = ""
    description: str = ""
    phase: str = "post_parse"          # post_parse(text→text) | post_chunk(pieces→pieces)
    config_schema: dict = {}            # UI 폼 자동 생성용(파라미터 없으면 {})

    def available(self) -> bool:
        """의존성/LLM 가용성(미가용이면 UI 비활성, 실행 시 건너뜀)."""
        return True

    def apply(self, data, cfg: dict, ctx=None):
        raise NotImplementedError


def register_transform(cls):
    """transform 클래스를 레지스트리에 등록한다(데코레이터)."""
    inst = cls()
    if not inst.id:
        raise ValueError("Transform.id 가 필요합니다")
    if inst.phase not in PHASES:
        raise ValueError(f"잘못된 phase: {inst.phase}")
    REGISTRY[inst.id] = inst
    return cls


def _safe_available(t: "Transform") -> bool:
    try:
        return bool(t.available())
    except Exception:  # noqa: BLE001
        return False


def list_transforms(phase: str | None = None) -> list[dict]:
    """등록된 보강 메타데이터(UI/introspection용). phase 로 필터 가능."""
    out = []
    for t in REGISTRY.values():
        if phase and t.phase != phase:
            continue
        out.append({
            "id": t.id, "label": t.label, "description": t.description,
            "phase": t.phase, "config_schema": t.config_schema,
            "available": _safe_available(t),
        })
    return sorted(out, key=lambda x: (x["phase"], x["id"]))


def normalize_pipeline(raw) -> dict:
    """임의 입력을 ``{post_parse:[{id,config}], post_chunk:[...]}`` 로 정규화한다.

    stage 는 ``"id"`` 문자열 또는 ``{"id":..., "config":{...}}`` 모두 허용."""
    raw = raw or {}
    out: dict[str, list[dict]] = {"post_parse": [], "post_chunk": []}
    for phase in PHASES:
        for st in (raw.get(phase) or []):
            if isinstance(st, str):
                out[phase].append({"id": st, "config": {}})
            elif isinstance(st, dict) and st.get("id"):
                out[phase].append({"id": st["id"], "config": st.get("config") or {}})
    return out


def validate_pipeline(raw) -> list[str]:
    """파이프라인 stage 들을 레지스트리 기준으로 검증한다(오류 메시지 리스트, 빈 리스트면 유효)."""
    errors: list[str] = []
    norm = normalize_pipeline(raw)
    for phase in PHASES:
        for st in norm[phase]:
            t = REGISTRY.get(st["id"])
            if t is None:
                errors.append(f"알 수 없는 transform: {st['id']}")
            elif t.phase != phase:
                errors.append(f"transform '{st['id']}' 는 {t.phase} 단계용입니다(요청 단계: {phase})")
    return errors


def run_transforms(phase: str, data, stages: list[dict] | None, ctx=None):
    """``stages``([{id, config}]) 를 순서대로 적용한다.

    기본은 실패·미가용 transform 을 건너뛴다(보강 실패가 인제스천을 막지 않음). 단,
    stage config 의 ``on_error="fail"`` 이면 예외를 전파해 잡을 실패시킨다(예: PII 마스킹이
    조용히 누락되면 안 되는 경우)."""
    for st in stages or []:
        cfg = st.get("config") or {}
        on_error = (cfg.get("on_error") or "skip").lower()
        t = REGISTRY.get(st.get("id"))
        if t is None or t.phase != phase:
            continue
        if not _safe_available(t):
            if on_error == "fail":
                raise RuntimeError(f"필수 transform '{st.get('id')}' 미가용")
            logger.warning("transform %s 미가용 — 건너뜀", st.get("id"))
            continue
        try:
            data = t.apply(data, cfg, ctx)
        except Exception as e:  # noqa: BLE001
            if on_error == "fail":
                raise
            logger.warning("transform %s 적용 실패(건너뜀): %s", st.get("id"), e)
    return data
