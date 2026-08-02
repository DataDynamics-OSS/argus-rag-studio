# SPDX-License-Identifier: Apache-2.0
"""로깅 설정 — 파일 + stdout 핸들러(다중 워커 분리 조회용)."""

import logging
import sys
from logging.handlers import TimedRotatingFileHandler

from app.core import logging as alog


def test_setup_logging_adds_file_and_stdout_handlers(tmp_path, monkeypatch):
    monkeypatch.setattr(alog.settings, "log_dir", tmp_path)
    alog.setup_logging()

    handlers = logging.getLogger().handlers
    # 파일 핸들러(일일 롤링) 존재
    assert any(isinstance(h, TimedRotatingFileHandler) for h in handlers)
    # stdout StreamHandler 존재 (journald/docker logs 수집용) — 파일 핸들러와 구분
    assert any(
        isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
        and getattr(h, "stream", None) is sys.stdout
        for h in handlers
    )
