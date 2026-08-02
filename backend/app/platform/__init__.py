# SPDX-License-Identifier: Apache-2.0
"""기반 환경(Platform Profile) 패키지.

`platform.base` 설정에 따라 임베딩/LLM/벡터스토어/스토리지의 기본값과 동작을 한 곳에서
공급하는 어댑터. 호출부에 `if databricks` 분기를 흩뿌리지 않고 프로파일 1개로 격리한다.
"""

from app.platform.factory import get_platform_profile, reset_platform_profile
from app.platform.profile import (
    DatabricksProfile,
    PlatformProfile,
    StandardProfile,
)

__all__ = [
    "PlatformProfile",
    "StandardProfile",
    "DatabricksProfile",
    "get_platform_profile",
    "reset_platform_profile",
]
