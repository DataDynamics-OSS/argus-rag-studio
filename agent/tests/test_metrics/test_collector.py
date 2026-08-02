"""Tests for metrics collector."""

from unittest.mock import MagicMock, patch

import psutil

from app.metrics.collector import (
    _get_fqdn,
    _get_socket_count,
    _get_too_many_open_files_count,
    collect_metrics,
)


class TestGetFqdn:
    """Tests for _get_fqdn helper."""

    @patch("app.metrics.collector.socket.getfqdn")
    def test_returns_fqdn(self, mock_fqdn):
        mock_fqdn.return_value = "host1.example.com"
        assert _get_fqdn() == "host1.example.com"


class TestGetSocketCount:
    """Tests for _get_socket_count helper."""

    @patch("app.metrics.collector.psutil.net_connections")
    def test_returns_count(self, mock_net):
        mock_net.return_value = [MagicMock(), MagicMock(), MagicMock()]
        assert _get_socket_count() == 3

    @patch("app.metrics.collector.psutil.net_connections")
    def test_access_denied_returns_zero(self, mock_net):
        mock_net.side_effect = psutil.AccessDenied(pid=1)
        assert _get_socket_count() == 0

    @patch("app.metrics.collector.psutil.net_connections")
    def test_os_error_returns_zero(self, mock_net):
        mock_net.side_effect = OSError("test")
        assert _get_socket_count() == 0


class TestGetTooManyOpenFilesCount:
    """Tests for _get_too_many_open_files_count helper."""

    @patch("app.metrics.collector.Path")
    @patch("app.metrics.collector.psutil.process_iter")
    def test_counts_processes_above_threshold(self, mock_iter, mock_path):
        proc = MagicMock()
        proc.pid = 100
        mock_iter.return_value = [proc]

        # Mock /proc/100/fd with 95 files
        fd_path_mock = MagicMock()
        fd_path_mock.iterdir.return_value = [MagicMock() for _ in range(95)]

        # Mock /proc/100/limits
        limits_content = (
            "Max open files            100                  100                  files\n"
        )
        limits_path_mock = MagicMock()
        limits_path_mock.read_text.return_value = limits_content

        def path_factory(path_str):
            if "/fd" in path_str:
                return fd_path_mock
            if "/limits" in path_str:
                return limits_path_mock
            return MagicMock()

        mock_path.side_effect = path_factory

        assert _get_too_many_open_files_count(threshold=90.0) == 1

    @patch("app.metrics.collector.Path")
    @patch("app.metrics.collector.psutil.process_iter")
    def test_skips_processes_below_threshold(self, mock_iter, mock_path):
        proc = MagicMock()
        proc.pid = 100
        mock_iter.return_value = [proc]

        fd_path_mock = MagicMock()
        fd_path_mock.iterdir.return_value = [MagicMock() for _ in range(10)]

        limits_content = (
            "Max open files            100                  100                  files\n"
        )
        limits_path_mock = MagicMock()
        limits_path_mock.read_text.return_value = limits_content

        def path_factory(path_str):
            if "/fd" in path_str:
                return fd_path_mock
            if "/limits" in path_str:
                return limits_path_mock
            return MagicMock()

        mock_path.side_effect = path_factory

        assert _get_too_many_open_files_count(threshold=90.0) == 0

    @patch("app.metrics.collector.psutil.process_iter")
    def test_handles_no_such_process(self, mock_iter):
        proc = MagicMock()
        proc.pid = 100
        type(proc).pid = property(lambda self: (_ for _ in ()).throw(psutil.NoSuchProcess(pid=100)))
        mock_iter.return_value = [proc]
        assert _get_too_many_open_files_count() == 0


class TestCollectMetrics:
    """Tests for collect_metrics function."""

    @patch("app.metrics.collector._get_too_many_open_files_count", return_value=2)
    @patch("app.metrics.collector._get_socket_count", return_value=42)
    @patch("app.metrics.collector.psutil")
    def test_returns_registry_with_metrics(self, mock_psutil, mock_sock, mock_tmof):
        # CPU
        mock_psutil.cpu_percent.return_value = 25.5
        mock_psutil.getloadavg.return_value = (1.0, 2.0, 3.0)
        mock_psutil.cpu_count.return_value = 4

        # Memory
        mock_psutil.virtual_memory.return_value = MagicMock(
            total=8_000_000_000,
            used=4_000_000_000,
            available=4_000_000_000,
            percent=50.0,
        )
        mock_psutil.swap_memory.return_value = MagicMock(total=2_000_000_000, used=500_000_000)

        # Processes
        mock_psutil.pids.return_value = [1, 2, 3]
        mock_proc = MagicMock()
        mock_proc.status.return_value = "running"
        mock_psutil.process_iter.return_value = [mock_proc]
        mock_psutil.STATUS_ZOMBIE = "zombie"

        # Disk
        mock_psutil.disk_partitions.return_value = []
        mock_psutil.disk_io_counters.return_value = {}

        # Network
        mock_psutil.net_io_counters.return_value = {}

        from prometheus_client import CollectorRegistry

        registry = collect_metrics()
        assert isinstance(registry, CollectorRegistry)

    @patch("app.metrics.collector._get_too_many_open_files_count", return_value=0)
    @patch("app.metrics.collector._get_socket_count", return_value=10)
    @patch("app.metrics.collector.psutil")
    def test_cpu_metrics_collected(self, mock_psutil, mock_sock, mock_tmof):
        mock_psutil.cpu_percent.return_value = 75.0
        mock_psutil.getloadavg.return_value = (2.5, 3.5, 4.5)
        mock_psutil.cpu_count.return_value = 8
        mock_psutil.virtual_memory.return_value = MagicMock(
            total=16_000_000_000,
            used=8_000_000_000,
            available=8_000_000_000,
            percent=50.0,
        )
        mock_psutil.swap_memory.return_value = MagicMock(total=0, used=0)
        mock_psutil.pids.return_value = []
        mock_psutil.process_iter.return_value = []
        mock_psutil.STATUS_ZOMBIE = "zombie"
        mock_psutil.disk_partitions.return_value = []
        mock_psutil.disk_io_counters.return_value = {}
        mock_psutil.net_io_counters.return_value = {}

        registry = collect_metrics()

        # Verify the registry has metrics by collecting sample data
        metrics = {}
        for metric in registry.collect():
            for sample in metric.samples:
                metrics[sample.name] = sample.value

        assert metrics["node_argus_cpu_usage_percent"] == 75.0
        assert metrics["node_argus_cpu_load1"] == 2.5
        assert metrics["node_argus_cpu_load5"] == 3.5
        assert metrics["node_argus_cpu_load15"] == 4.5
        assert metrics["node_argus_cpu_count"] == 8

    @patch("app.metrics.collector._get_too_many_open_files_count", return_value=0)
    @patch("app.metrics.collector._get_socket_count", return_value=10)
    @patch("app.metrics.collector.psutil")
    def test_memory_metrics_collected(self, mock_psutil, mock_sock, mock_tmof):
        mock_psutil.cpu_percent.return_value = 10.0
        mock_psutil.getloadavg.return_value = (0.5, 0.5, 0.5)
        mock_psutil.cpu_count.return_value = 2
        mock_psutil.virtual_memory.return_value = MagicMock(
            total=16_000_000_000,
            used=12_000_000_000,
            available=4_000_000_000,
            percent=75.0,
        )
        mock_psutil.swap_memory.return_value = MagicMock(total=4_000_000_000, used=1_000_000_000)
        mock_psutil.pids.return_value = []
        mock_psutil.process_iter.return_value = []
        mock_psutil.STATUS_ZOMBIE = "zombie"
        mock_psutil.disk_partitions.return_value = []
        mock_psutil.disk_io_counters.return_value = {}
        mock_psutil.net_io_counters.return_value = {}

        registry = collect_metrics()
        metrics = {}
        for metric in registry.collect():
            for sample in metric.samples:
                metrics[sample.name] = sample.value

        assert metrics["node_argus_memory_total_bytes"] == 16_000_000_000
        assert metrics["node_argus_memory_used_bytes"] == 12_000_000_000
        assert metrics["node_argus_memory_available_bytes"] == 4_000_000_000
        assert metrics["node_argus_memory_usage_percent"] == 75.0
        assert metrics["node_argus_swap_total_bytes"] == 4_000_000_000
        assert metrics["node_argus_swap_used_bytes"] == 1_000_000_000

    @patch("app.metrics.collector._get_too_many_open_files_count", return_value=3)
    @patch("app.metrics.collector._get_socket_count", return_value=55)
    @patch("app.metrics.collector.psutil")
    def test_process_and_socket_metrics(self, mock_psutil, mock_sock, mock_tmof):
        mock_psutil.cpu_percent.return_value = 10.0
        mock_psutil.getloadavg.return_value = (0.5, 0.5, 0.5)
        mock_psutil.cpu_count.return_value = 2
        mock_psutil.virtual_memory.return_value = MagicMock(
            total=8_000_000_000,
            used=4_000_000_000,
            available=4_000_000_000,
            percent=50.0,
        )
        mock_psutil.swap_memory.return_value = MagicMock(total=0, used=0)
        mock_psutil.pids.return_value = list(range(150))

        zombie_proc = MagicMock()
        zombie_proc.status.return_value = "zombie"
        running_proc = MagicMock()
        running_proc.status.return_value = "running"
        mock_psutil.process_iter.return_value = [zombie_proc, running_proc, zombie_proc]
        mock_psutil.STATUS_ZOMBIE = "zombie"

        mock_psutil.disk_partitions.return_value = []
        mock_psutil.disk_io_counters.return_value = {}
        mock_psutil.net_io_counters.return_value = {}

        registry = collect_metrics()
        metrics = {}
        for metric in registry.collect():
            for sample in metric.samples:
                metrics[sample.name] = sample.value

        assert metrics["node_argus_process_total"] == 150
        assert metrics["node_argus_process_zombie_count"] == 2
        assert metrics["node_argus_socket_count"] == 55
        assert metrics["node_argus_too_many_open_files_count"] == 3

    @patch("app.metrics.collector._get_too_many_open_files_count", return_value=0)
    @patch("app.metrics.collector._get_socket_count", return_value=0)
    @patch("app.metrics.collector.psutil")
    def test_disk_partition_metrics(self, mock_psutil, mock_sock, mock_tmof):
        mock_psutil.cpu_percent.return_value = 10.0
        mock_psutil.getloadavg.return_value = (0.5, 0.5, 0.5)
        mock_psutil.cpu_count.return_value = 2
        mock_psutil.virtual_memory.return_value = MagicMock(
            total=8_000_000_000,
            used=4_000_000_000,
            available=4_000_000_000,
            percent=50.0,
        )
        mock_psutil.swap_memory.return_value = MagicMock(total=0, used=0)
        mock_psutil.pids.return_value = []
        mock_psutil.process_iter.return_value = []
        mock_psutil.STATUS_ZOMBIE = "zombie"

        part = MagicMock(device="/dev/sda1", mountpoint="/", fstype="ext4")
        mock_psutil.disk_partitions.return_value = [part]
        mock_psutil.disk_usage.return_value = MagicMock(
            total=500_000_000_000,
            used=200_000_000_000,
            free=300_000_000_000,
            percent=40.0,
        )
        mock_psutil.disk_io_counters.return_value = {}
        mock_psutil.net_io_counters.return_value = {}

        registry = collect_metrics()
        found_total = False
        for metric in registry.collect():
            for sample in metric.samples:
                if sample.name == "node_argus_disk_total_bytes":
                    assert sample.labels.get("device") == "/dev/sda1"
                    assert sample.labels.get("mountpoint") == "/"
                    assert sample.labels.get("fstype") == "ext4"
                    assert sample.value == 500_000_000_000
                    found_total = True
        assert found_total, "node_argus_disk_total_bytes metric not found"

    @patch("app.metrics.collector._get_too_many_open_files_count", return_value=0)
    @patch("app.metrics.collector._get_socket_count", return_value=0)
    @patch("app.metrics.collector.psutil")
    def test_network_metrics(self, mock_psutil, mock_sock, mock_tmof):
        mock_psutil.cpu_percent.return_value = 10.0
        mock_psutil.getloadavg.return_value = (0.5, 0.5, 0.5)
        mock_psutil.cpu_count.return_value = 2
        mock_psutil.virtual_memory.return_value = MagicMock(
            total=8_000_000_000,
            used=4_000_000_000,
            available=4_000_000_000,
            percent=50.0,
        )
        mock_psutil.swap_memory.return_value = MagicMock(total=0, used=0)
        mock_psutil.pids.return_value = []
        mock_psutil.process_iter.return_value = []
        mock_psutil.STATUS_ZOMBIE = "zombie"
        mock_psutil.disk_partitions.return_value = []
        mock_psutil.disk_io_counters.return_value = {}

        eth0 = MagicMock(
            bytes_sent=1000,
            bytes_recv=2000,
            errin=5,
            errout=3,
            dropin=1,
            dropout=0,
        )
        mock_psutil.net_io_counters.return_value = {"eth0": eth0}

        registry = collect_metrics()
        metrics = {}
        for metric in registry.collect():
            for sample in metric.samples:
                key = sample.name
                if sample.labels:
                    label_str = ",".join(f"{k}={v}" for k, v in sample.labels.items())
                    key = f"{key}{{{label_str}}}"
                metrics[key] = sample.value

        assert metrics["node_argus_network_bytes_sent{interface=eth0}"] == 1000
        assert metrics["node_argus_network_bytes_recv{interface=eth0}"] == 2000
        assert metrics["node_argus_network_errors_in{interface=eth0}"] == 5
        assert metrics["node_argus_network_drop_in{interface=eth0}"] == 1

    @patch("app.metrics.collector._get_too_many_open_files_count", return_value=0)
    @patch("app.metrics.collector._get_socket_count", return_value=0)
    @patch("app.metrics.collector.psutil")
    def test_fresh_registry_each_call(self, mock_psutil, mock_sock, mock_tmof):
        """Each call should return a new registry to avoid duplicate errors."""
        mock_psutil.cpu_percent.return_value = 10.0
        mock_psutil.getloadavg.return_value = (0.5, 0.5, 0.5)
        mock_psutil.cpu_count.return_value = 2
        mock_psutil.virtual_memory.return_value = MagicMock(
            total=8_000_000_000,
            used=4_000_000_000,
            available=4_000_000_000,
            percent=50.0,
        )
        mock_psutil.swap_memory.return_value = MagicMock(total=0, used=0)
        mock_psutil.pids.return_value = []
        mock_psutil.process_iter.return_value = []
        mock_psutil.STATUS_ZOMBIE = "zombie"
        mock_psutil.disk_partitions.return_value = []
        mock_psutil.disk_io_counters.return_value = {}
        mock_psutil.net_io_counters.return_value = {}

        reg1 = collect_metrics()
        reg2 = collect_metrics()
        assert reg1 is not reg2
