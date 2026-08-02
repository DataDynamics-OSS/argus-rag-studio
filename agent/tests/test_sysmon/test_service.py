"""Tests for sysmon service - basic validation of data structures."""

import pytest

from app.sysmon import service


def test_cpu_usage_returns_valid_structure():
    result = service.get_cpu_usage(interval=0.1)
    assert result.core_count >= 1
    assert 0.0 <= result.total_percent <= 100.0
    assert 0.0 <= result.user_percent <= 100.0
    assert 0.0 <= result.system_percent <= 100.0
    assert 0.0 <= result.idle_percent <= 100.0


def test_cpu_core_usage_matches_core_count():
    result = service.get_cpu_core_usage(interval=0.1)
    assert result.core_count >= 1
    assert len(result.cores) == result.core_count
    for core in result.cores:
        assert 0.0 <= core.total_percent <= 100.0


def test_network_usage_has_interfaces():
    result = service.get_network_usage()
    assert len(result.interfaces) >= 1  # at least lo
    assert result.total.bytes_sent >= 0
    assert result.total.bytes_recv >= 0

    lo = next((i for i in result.interfaces if i.interface == "lo"), None)
    if lo:
        assert lo.bytes_sent >= 0


@pytest.mark.asyncio
async def test_network_errors_structure():
    result = await service.get_network_errors()
    assert len(result.interfaces) >= 1
    assert result.total_errors >= 0
    for iface in result.interfaces:
        assert isinstance(iface.has_errors, bool)


def test_process_list_returns_processes():
    result = service.get_process_list(sort_by="cpu_percent", limit=10)
    assert result.total_count > 0
    assert len(result.processes) <= 10
    assert result.sort_by == "cpu_percent"
    for proc in result.processes:
        assert proc.pid > 0
        assert proc.memory.rss_bytes >= 0
        assert proc.memory.vms_bytes >= 0


def test_disk_partitions_returns_info():
    result = service.get_disk_partitions()
    assert result.total_count >= 1
    for part in result.partitions:
        assert part.device
        assert part.mount_point
        assert part.total_bytes > 0
        assert 0.0 <= part.usage_percent <= 100.0


def test_parent_disk_extraction():
    assert service._get_parent_disk("/dev/sda1") == "/dev/sda"
    assert service._get_parent_disk("/dev/nvme0n1p1") == "/dev/nvme0n1"
    assert service._get_parent_disk("/dev/vda2") == "/dev/vda"
