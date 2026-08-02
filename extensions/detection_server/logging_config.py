# SPDX-License-Identifier: Apache-2.0
"""일 단위 롤링 파일 핸들러 로깅 설정 — catalog/RAG 백엔드와 동일 포맷.

콘솔(stdout) 핸들러를 추가해 도커 로그(`docker logs`)에서도 동일 포맷으로 보이게 한다.
"""

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from detection_server.config import config

LOG_FORMAT = (
    "%(levelname)s %(asctime)s.%(msecs)03d %(process)d %(programname)s"
    " %(filename)s:%(funcName)s:%(lineno)d - %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class _ProgramNameFilter(logging.Filter):
    def __init__(self, program_name: str) -> None:
        super().__init__()
        self.program_name = program_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.programname = self.program_name  # type: ignore[attr-defined]
        return True


class _DailyFileHandler(TimedRotatingFileHandler):
    def __init__(self, log_dir: Path, filename: str, backup_count: int) -> None:
        super().__init__(
            filename=str(log_dir / filename),
            when="midnight",
            interval=1,
            backupCount=backup_count,
            encoding="utf-8",
        )
        self.suffix = "%Y%m%d"
        self._log_dir = log_dir
        self._base_stem = Path(filename).stem
        self._base_ext = Path(filename).suffix or ".log"
        self.namer = self._namer

    def _namer(self, default_name: str) -> str:
        parts = default_name.rsplit(".", 1)
        if len(parts) == 2:
            return str(self._log_dir / f"{self._base_stem}_{parts[1]}{self._base_ext}")
        return default_name


def setup_logging() -> None:
    log_dir = config.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, config.log_level.upper(), logging.INFO)
    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)
    program_filter = _ProgramNameFilter(config.app_name)

    file_handler = _DailyFileHandler(log_dir, config.log_filename, config.log_rolling_backup_count)
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(program_filter)

    # 도커/포그라운드 가시성을 위한 콘솔 핸들러(동일 포맷)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(program_filter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
