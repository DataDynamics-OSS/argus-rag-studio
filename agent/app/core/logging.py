"""Logging configuration.

Provides daily rolling file logging with a structured log format:
  LEVEL yyyy-MM-dd HH:mm:ss.SSS PID program_name source_location - message

Rolled log files are named with a date suffix: agent_20260315.log
"""

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.core.config import settings

# Log format: LEVEL date PID program source - message
# Example: INFO 2025-03-15 14:30:45.123 12345 argus-rag-studio-agent app.main:lifespan:25 - Starting
LOG_FORMAT = (
    "%(levelname)s %(asctime)s.%(msecs)03d %(process)d %(programname)s"
    " %(filename)s:%(funcName)s:%(lineno)d - %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class _ProgramNameFilter(logging.Filter):
    """Inject program name into log records."""

    def __init__(self, program_name: str) -> None:
        super().__init__()
        self.program_name = program_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.programname = self.program_name  # type: ignore[attr-defined]
        return True


class _DailyFileHandler(TimedRotatingFileHandler):
    """Daily rotating file handler that produces agent_YYYYMMDD.log suffixes.

    Default TimedRotatingFileHandler appends a suffix like .2025-01-01 to the
    base filename. This subclass overrides namer to produce:
      agent_20260315.log  (instead of agent.log.2026-03-15)
    """

    def __init__(self, log_dir: Path, filename: str, backup_count: int) -> None:
        log_file = log_dir / filename
        super().__init__(
            filename=str(log_file),
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
        """Rename rolled file from agent.log.20260315 to agent_20260315.log."""
        # default_name is like /var/log/.../agent.log.20260315
        # Extract the date suffix
        parts = default_name.rsplit(".", 1)
        if len(parts) == 2:
            date_suffix = parts[1]
            return str(self._log_dir / f"{self._base_stem}_{date_suffix}{self._base_ext}")
        return default_name


def setup_logging() -> None:
    """Configure application logging.

    - File logging is the primary output (daily rolling)
    - Log directory is created if it does not exist
    - When config files are absent (dev mode), defaults to ./logs
    """
    log_dir = settings.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)
    program_filter = _ProgramNameFilter(settings.app_name)

    # File handler (daily rolling) - primary
    file_handler = _DailyFileHandler(
        log_dir=log_dir,
        filename=settings.log_filename,
        backup_count=settings.log_rolling_backup_count,
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(program_filter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    # Clear any existing handlers
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
