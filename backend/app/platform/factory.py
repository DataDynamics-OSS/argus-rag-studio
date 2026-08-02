# SPDX-License-Identifier: Apache-2.0
"""PlatformProfile 팩토리 — 설정(platform.base)에 따라 프로파일 선택(캐시).

설정 변경(설정 화면 저장) 시 ``reset_platform_profile()`` 로 캐시를 무효화해 다음 호출에서
재생성한다(vectorstore/factory 와 동일 패턴). 캐시 키에 프로파일 동작에 영향을 주는 설정
값(쿼리 instruction)을 포함해, 해당 값이 바뀌면 명시 reset 없이도 자동 재생성된다.
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.platform.profile import DatabricksProfile, PlatformProfile, StandardProfile

logger = logging.getLogger(__name__)

_profile: PlatformProfile | None = None
_profile_key: tuple | None = None


def _current_key() -> tuple:
    return (
        (settings.platform_base or "standard").lower(),
        settings.embedding_query_instruction or "",
    )


def reset_platform_profile() -> None:
    """캐시 무효화 — 설정 변경 후 호출하면 다음 get_platform_profile() 이 새 설정으로 생성."""
    global _profile, _profile_key
    _profile = None
    _profile_key = None


def get_platform_profile() -> PlatformProfile:
    """현재 설정의 PlatformProfile 인스턴스를 반환한다(base/instruction 바뀌면 자동 재생성)."""
    global _profile, _profile_key
    key = _current_key()
    if _profile is not None and _profile_key == key:
        return _profile

    base = key[0]
    if base == "databricks":
        profile: PlatformProfile = DatabricksProfile(
            query_instruction=settings.embedding_query_instruction or None
        )
    else:
        profile = StandardProfile()
    logger.info("기반 환경 프로파일 생성: %s", profile.name)
    _profile = profile
    _profile_key = key
    return profile
