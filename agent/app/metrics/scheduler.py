"""Cron-based scheduler for periodic metrics push.

Parses a standard cron expression (minute hour day month weekday)
and runs push_metrics() on matching intervals.
"""

import asyncio
import logging
from datetime import datetime

from app.core.config import settings
from app.metrics.pusher import push_metrics

logger = logging.getLogger(__name__)


def _cron_matches(cron_expr: str, dt: datetime) -> bool:
    """Check if a datetime matches a cron expression.

    Supports standard 5-field cron: minute hour day month weekday
    Each field can be: * (any), number, comma-separated values, or */step.
    """
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        logger.warning("Invalid cron expression: %s", cron_expr)
        return False

    values = [dt.minute, dt.hour, dt.day, dt.month, dt.isoweekday() % 7]

    for field, value in zip(fields, values):
        if not _field_matches(field, value):
            return False
    return True


def _field_matches(field: str, value: int) -> bool:
    """Check if a single cron field matches a value."""
    if field == "*":
        return True

    # Handle */step
    if field.startswith("*/"):
        try:
            step = int(field[2:])
            return value % step == 0
        except ValueError:
            return False

    # Handle comma-separated values
    for part in field.split(","):
        try:
            if int(part) == value:
                return True
        except ValueError:
            continue

    return False


class MetricsScheduler:
    """Async scheduler that pushes metrics on a cron schedule."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the scheduler background task."""
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info(
            "Metrics scheduler started (cron=%s, gateway=%s:%s, push=%s)",
            settings.prometheus_push_cron,
            settings.prometheus_pushgateway_host,
            settings.prometheus_pushgateway_port,
            settings.prometheus_enable_push,
        )

    async def reschedule(self) -> None:
        """Stop the current scheduler task and restart with updated settings."""
        await self.stop()
        await self.start()
        logger.info(
            "Metrics scheduler rescheduled (cron=%s, gateway=%s:%s, push=%s)",
            settings.prometheus_push_cron,
            settings.prometheus_pushgateway_host,
            settings.prometheus_pushgateway_port,
            settings.prometheus_enable_push,
        )

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Metrics scheduler stopped")

    async def _run(self) -> None:
        """Main scheduler loop - checks cron every 30 seconds."""
        last_run_minute = -1

        while self._running:
            try:
                now = datetime.now()
                current_minute = now.minute + now.hour * 60

                # Only run once per matching minute
                if current_minute != last_run_minute and _cron_matches(
                    settings.prometheus_push_cron, now
                ):
                    last_run_minute = current_minute
                    # Run push in executor to avoid blocking event loop
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, push_metrics)

                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in metrics scheduler loop")
                await asyncio.sleep(30)


metrics_scheduler = MetricsScheduler()
