"""Tests for metrics pusher."""

from unittest.mock import MagicMock, patch

from app.metrics.pusher import JOB_NAME, push_metrics


class TestPushMetrics:
    """Tests for push_metrics function."""

    @patch("app.metrics.pusher.settings")
    def test_disabled_returns_false(self, mock_settings):
        mock_settings.prometheus_enable_push = False
        assert push_metrics() is False

    @patch("app.metrics.pusher.pushadd_to_gateway")
    @patch("app.metrics.pusher.collect_metrics")
    @patch("app.metrics.pusher._get_hostname", return_value="host1.example.com")
    @patch("app.metrics.pusher.settings")
    def test_success_returns_true(self, mock_settings, mock_fqdn, mock_collect, mock_push):
        mock_settings.prometheus_enable_push = True
        mock_settings.prometheus_pushgateway_host = "pushgw"
        mock_settings.prometheus_pushgateway_port = 9091
        mock_collect.return_value = MagicMock()

        assert push_metrics() is True

        mock_push.assert_called_once_with(
            "pushgw:9091",
            job=JOB_NAME,
            registry=mock_collect.return_value,
            grouping_key={"instance": "host1.example.com"},
        )

    @patch("app.metrics.pusher.pushadd_to_gateway")
    @patch("app.metrics.pusher.collect_metrics")
    @patch("app.metrics.pusher._get_hostname", return_value="host1.example.com")
    @patch("app.metrics.pusher.settings")
    def test_failure_returns_false(self, mock_settings, mock_fqdn, mock_collect, mock_push):
        mock_settings.prometheus_enable_push = True
        mock_settings.prometheus_pushgateway_host = "localhost"
        mock_settings.prometheus_pushgateway_port = 9091
        mock_collect.return_value = MagicMock()
        mock_push.side_effect = ConnectionError("refused")

        assert push_metrics() is False

    @patch("app.metrics.pusher.pushadd_to_gateway")
    @patch("app.metrics.pusher.collect_metrics")
    @patch("app.metrics.pusher._get_hostname", return_value="host1.example.com")
    @patch("app.metrics.pusher.settings")
    def test_uses_fqdn_as_instance(self, mock_settings, mock_fqdn, mock_collect, mock_push):
        mock_settings.prometheus_enable_push = True
        mock_settings.prometheus_pushgateway_host = "localhost"
        mock_settings.prometheus_pushgateway_port = 9091
        mock_collect.return_value = MagicMock()

        push_metrics()

        call_kwargs = mock_push.call_args
        grouping_key = call_kwargs.kwargs.get("grouping_key") or call_kwargs[1].get("grouping_key")
        assert grouping_key == {"instance": "host1.example.com"}

    @patch("app.metrics.pusher.pushadd_to_gateway")
    @patch("app.metrics.pusher.collect_metrics")
    @patch("app.metrics.pusher._get_hostname", return_value="host1.example.com")
    @patch("app.metrics.pusher.settings")
    def test_job_name(self, mock_settings, mock_fqdn, mock_collect, mock_push):
        mock_settings.prometheus_enable_push = True
        mock_settings.prometheus_pushgateway_host = "localhost"
        mock_settings.prometheus_pushgateway_port = 9091
        mock_collect.return_value = MagicMock()

        push_metrics()

        call_kwargs = mock_push.call_args
        job = call_kwargs.kwargs.get("job") or call_kwargs[1].get("job")
        assert job == "argus_rag_studio_metrics"
