# SPDX-License-Identifier: Apache-2.0
"""pytest 공용 설정.

app.core.config 가 임포트되기 전에 설정 디렉토리를 패키징 기본값으로 고정해
테스트가 결정적으로 동작하도록 한다(개발 머신/CI 어디서나 동일)."""

import os
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
os.environ.setdefault(
    "ARGUS_RAG_STUDIO_SERVER_CONFIG_DIR", str(_BACKEND / "packaging" / "config")
)
