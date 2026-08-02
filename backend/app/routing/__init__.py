# SPDX-License-Identifier: Apache-2.0
"""문서 라우팅 레지스트리 + 기본 정책.

빌트인 라우터 import 는 등록 트리거다(transforms 패턴과 동일). 기본 정책은 빈 stage(=항상 폴백)로,
관리자가 정책을 구성하기 전까지 인테이크 문서를 폴백 컬렉션으로 보낸다.
"""

from app.routing import builtins as _builtins  # noqa: F401 (등록 트리거)
from app.routing.base import (
    MODES,
    REGISTRY,
    Candidate,
    RouteContext,
    RouteInput,
    Router,
    list_routers,
    normalize_policy,
    register_router,
    run_policy,
    validate_policy,
)

# 기본 라우팅 정책 — stage 없음(매칭 없음 → 폴백). fallback_collection_id 는 관리자가 설정.
DEFAULT_POLICY: dict = {
    "mode": "first_match",
    "stages": [],
    "fallback_collection_id": None,
    "review_below": 0.5,
}

__all__ = [
    "MODES", "REGISTRY", "Candidate", "RouteContext", "RouteInput", "Router",
    "list_routers", "normalize_policy", "register_router", "run_policy",
    "validate_policy", "DEFAULT_POLICY",
]
