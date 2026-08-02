"""Tests for metrics scheduler."""

from datetime import datetime
from unittest.mock import patch

from app.metrics.scheduler import MetricsScheduler, _cron_matches, _field_matches


class TestFieldMatches:
    """Tests for _field_matches helper."""

    def test_wildcard_matches_any(self):
        assert _field_matches("*", 0) is True
        assert _field_matches("*", 59) is True

    def test_exact_match(self):
        assert _field_matches("5", 5) is True
        assert _field_matches("5", 6) is False

    def test_step_match(self):
        assert _field_matches("*/5", 0) is True
        assert _field_matches("*/5", 5) is True
        assert _field_matches("*/5", 10) is True
        assert _field_matches("*/5", 3) is False

    def test_comma_separated(self):
        assert _field_matches("1,3,5", 3) is True
        assert _field_matches("1,3,5", 4) is False
        assert _field_matches("0,30", 0) is True
        assert _field_matches("0,30", 30) is True
        assert _field_matches("0,30", 15) is False

    def test_invalid_step_returns_false(self):
        assert _field_matches("*/abc", 5) is False

    def test_invalid_value_in_comma_list(self):
        assert _field_matches("1,abc,5", 5) is True
        assert _field_matches("abc,def", 0) is False


class TestCronMatches:
    """Tests for _cron_matches function."""

    def test_every_minute(self):
        dt = datetime(2025, 3, 15, 10, 30)
        assert _cron_matches("* * * * *", dt) is True

    def test_specific_minute(self):
        dt = datetime(2025, 3, 15, 10, 30)
        assert _cron_matches("30 * * * *", dt) is True
        assert _cron_matches("15 * * * *", dt) is False

    def test_specific_hour_and_minute(self):
        dt = datetime(2025, 3, 15, 14, 0)
        assert _cron_matches("0 14 * * *", dt) is True
        assert _cron_matches("0 15 * * *", dt) is False

    def test_every_5_minutes(self):
        dt0 = datetime(2025, 3, 15, 10, 0)
        dt5 = datetime(2025, 3, 15, 10, 5)
        dt3 = datetime(2025, 3, 15, 10, 3)
        assert _cron_matches("*/5 * * * *", dt0) is True
        assert _cron_matches("*/5 * * * *", dt5) is True
        assert _cron_matches("*/5 * * * *", dt3) is False

    def test_specific_day_of_month(self):
        dt = datetime(2025, 3, 15, 10, 0)
        assert _cron_matches("0 10 15 * *", dt) is True
        assert _cron_matches("0 10 16 * *", dt) is False

    def test_specific_month(self):
        dt = datetime(2025, 3, 15, 10, 0)
        assert _cron_matches("0 10 15 3 *", dt) is True
        assert _cron_matches("0 10 15 4 *", dt) is False

    def test_weekday(self):
        # 2025-03-15 is Saturday = isoweekday() 6, %7 = 6
        dt = datetime(2025, 3, 15, 10, 0)
        assert _cron_matches("0 10 * * 6", dt) is True
        assert _cron_matches("0 10 * * 1", dt) is False

    def test_sunday_is_zero(self):
        # 2025-03-16 is Sunday = isoweekday() 7, %7 = 0
        dt = datetime(2025, 3, 16, 10, 0)
        assert _cron_matches("0 10 * * 0", dt) is True

    def test_invalid_cron_too_few_fields(self):
        dt = datetime(2025, 3, 15, 10, 0)
        assert _cron_matches("* * *", dt) is False

    def test_invalid_cron_too_many_fields(self):
        dt = datetime(2025, 3, 15, 10, 0)
        assert _cron_matches("* * * * * *", dt) is False

    def test_comma_in_cron(self):
        dt = datetime(2025, 3, 15, 10, 15)
        assert _cron_matches("0,15,30,45 * * * *", dt) is True
        assert _cron_matches("0,30 * * * *", dt) is False


class TestMetricsScheduler:
    """Tests for MetricsScheduler class."""

    @patch("app.metrics.scheduler.settings")
    async def test_start_disabled(self, mock_settings):
        mock_settings.prometheus_enable_push = False
        scheduler = MetricsScheduler()
        await scheduler.start()
        assert scheduler._task is None

    @patch("app.metrics.scheduler.push_metrics")
    @patch("app.metrics.scheduler.settings")
    async def test_start_creates_task(self, mock_settings, mock_push):
        mock_settings.prometheus_enable_push = True
        mock_settings.prometheus_push_cron = "* * * * *"
        mock_settings.prometheus_pushgateway_host = "localhost"
        mock_settings.prometheus_pushgateway_port = 9091

        scheduler = MetricsScheduler()
        await scheduler.start()
        assert scheduler._task is not None
        assert scheduler._running is True
        await scheduler.stop()

    @patch("app.metrics.scheduler.settings")
    async def test_stop_cancels_task(self, mock_settings):
        mock_settings.prometheus_enable_push = True
        mock_settings.prometheus_push_cron = "* * * * *"
        mock_settings.prometheus_pushgateway_host = "localhost"
        mock_settings.prometheus_pushgateway_port = 9091

        scheduler = MetricsScheduler()
        await scheduler.start()
        assert scheduler._task is not None
        await scheduler.stop()
        assert scheduler._task is None
        assert scheduler._running is False

    async def test_stop_without_start(self):
        scheduler = MetricsScheduler()
        await scheduler.stop()
        assert scheduler._task is None
