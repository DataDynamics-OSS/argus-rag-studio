"""Tests for processmgr service - process management."""

import signal
from unittest.mock import MagicMock, patch

import psutil
import pytest

from app.processmgr import service

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _mock_process(
    pid=1234,
    ppid=1,
    name="test-proc",
    username="root",
    status="running",
    cpu_percent=1.5,
    rss=1024 * 1024,
    vms=2048 * 1024,
    create_time=1000000.0,
    cmdline=None,
    num_threads=2,
):
    """Create a mock psutil.Process."""
    proc = MagicMock(spec=psutil.Process)
    proc.pid = pid
    proc.ppid.return_value = ppid
    proc.name.return_value = name
    proc.username.return_value = username
    proc.status.return_value = status
    proc.cpu_percent.return_value = cpu_percent
    mem = MagicMock()
    mem.rss = rss
    mem.vms = vms
    proc.memory_info.return_value = mem
    proc.create_time.return_value = create_time
    proc.cmdline.return_value = cmdline or [f"/usr/bin/{name}"]
    proc.num_threads.return_value = num_threads
    proc.oneshot.return_value.__enter__ = MagicMock(return_value=None)
    proc.oneshot.return_value.__exit__ = MagicMock(return_value=False)
    return proc


# ---------------------------------------------------------------------------
# 1. Process list
# ---------------------------------------------------------------------------


def test_list_processes():
    procs = [
        _mock_process(pid=1, name="init"),
        _mock_process(pid=100, name="sshd"),
        _mock_process(pid=200, name="nginx", username="www"),
    ]
    with patch("app.processmgr.service.psutil.process_iter", return_value=procs):
        result = service.list_processes()

    assert result.total == 3
    pids = [p.pid for p in result.processes]
    assert 1 in pids
    assert 200 in pids


def test_list_processes_filter_user():
    procs = [
        _mock_process(pid=1, username="root"),
        _mock_process(pid=2, username="alice"),
        _mock_process(pid=3, username="root"),
    ]
    with patch("app.processmgr.service.psutil.process_iter", return_value=procs):
        result = service.list_processes(username="alice")

    assert result.total == 1
    assert result.processes[0].pid == 2


def test_list_processes_sort_cpu():
    procs = [
        _mock_process(pid=1, cpu_percent=5.0),
        _mock_process(pid=2, cpu_percent=80.0),
        _mock_process(pid=3, cpu_percent=20.0),
    ]
    with patch("app.processmgr.service.psutil.process_iter", return_value=procs):
        result = service.list_processes(sort_by="cpu_percent")

    assert result.processes[0].pid == 2
    assert result.processes[1].pid == 3


def test_list_processes_limit():
    procs = [_mock_process(pid=i) for i in range(10)]
    with patch("app.processmgr.service.psutil.process_iter", return_value=procs):
        result = service.list_processes(limit=3)

    assert result.total == 3


# ---------------------------------------------------------------------------
# 2. Send signal
# ---------------------------------------------------------------------------


def test_send_signal_success():
    with patch("app.processmgr.service.os.kill") as mock_kill:
        result = service.send_signal(1234, "SIGTERM")

    assert result.success is True
    mock_kill.assert_called_once_with(1234, signal.SIGTERM)


def test_send_signal_kill():
    with patch("app.processmgr.service.os.kill") as mock_kill:
        result = service.send_signal(5678, "SIGKILL")

    assert result.success is True
    mock_kill.assert_called_once_with(5678, signal.SIGKILL)


def test_send_signal_not_found():
    with patch("app.processmgr.service.os.kill", side_effect=ProcessLookupError):
        result = service.send_signal(9999, "SIGTERM")

    assert result.success is False
    assert "not found" in result.message.lower()


def test_send_signal_unknown():
    result = service.send_signal(1234, "SIGFAKE")
    assert result.success is False
    assert "Unknown signal" in result.message


def test_send_signal_permission_denied():
    with patch("app.processmgr.service.os.kill", side_effect=PermissionError):
        result = service.send_signal(1, "SIGTERM")

    assert result.success is False
    assert "Permission" in result.message


# ---------------------------------------------------------------------------
# 3. Restart (SIGHUP)
# ---------------------------------------------------------------------------


def test_restart_process():
    with patch("app.processmgr.service.os.kill") as mock_kill:
        result = service.restart_process(1234)

    assert result.success is True
    mock_kill.assert_called_once_with(1234, signal.SIGHUP)


# ---------------------------------------------------------------------------
# 4. Zombie processes
# ---------------------------------------------------------------------------


def test_list_zombies():
    zombie = MagicMock(spec=psutil.Process)
    zombie.pid = 999
    zombie.ppid.return_value = 1
    zombie.name.return_value = "zombie-proc"
    zombie.username.return_value = "root"
    zombie.status.return_value = psutil.STATUS_ZOMBIE
    zombie.cmdline.return_value = []

    normal = MagicMock(spec=psutil.Process)
    normal.pid = 100
    normal.status.return_value = "running"

    with patch("app.processmgr.service.psutil.process_iter", return_value=[zombie, normal]):
        result = service.list_zombies()

    assert result.total == 1
    assert result.processes[0].pid == 999
    assert result.processes[0].status == "zombie"


def test_list_zombies_empty():
    proc = MagicMock(spec=psutil.Process)
    proc.pid = 1
    proc.status.return_value = "running"

    with patch("app.processmgr.service.psutil.process_iter", return_value=[proc]):
        result = service.list_zombies()

    assert result.total == 0


# ---------------------------------------------------------------------------
# 5. Kill user processes
# ---------------------------------------------------------------------------


def test_kill_user_processes():
    proc1 = MagicMock(spec=psutil.Process)
    proc1.pid = 100
    proc1.username.return_value = "alice"

    proc2 = MagicMock(spec=psutil.Process)
    proc2.pid = 200
    proc2.username.return_value = "bob"

    proc3 = MagicMock(spec=psutil.Process)
    proc3.pid = 300
    proc3.username.return_value = "alice"

    with (
        patch("app.processmgr.service.psutil.process_iter", return_value=[proc1, proc2, proc3]),
        patch("app.processmgr.service.os.kill") as mock_kill,
    ):
        result = service.kill_user_processes("alice")

    assert result.success is True
    assert mock_kill.call_count == 2
    assert "2 processes" in result.message


def test_kill_user_processes_no_match():
    proc = MagicMock(spec=psutil.Process)
    proc.pid = 100
    proc.username.return_value = "bob"

    with (
        patch("app.processmgr.service.psutil.process_iter", return_value=[proc]),
        patch("app.processmgr.service.os.kill"),
    ):
        result = service.kill_user_processes("nobody")

    assert result.success is False
    assert "No processes" in result.message


def test_kill_user_processes_unknown_signal():
    result = service.kill_user_processes("alice", "SIGFAKE")
    assert result.success is False
    assert "Unknown signal" in result.message


# ---------------------------------------------------------------------------
# 6. Process detail
# ---------------------------------------------------------------------------


def test_get_process_detail():
    proc = _mock_process(pid=1234, cpu_percent=5.0)
    full_mem = MagicMock()
    full_mem.pss = 512 * 1024
    full_mem.uss = 256 * 1024
    proc.memory_full_info.return_value = full_mem

    with (
        patch("app.processmgr.service.psutil.Process", return_value=proc),
        patch("app.processmgr.service._get_open_file_count", return_value=50),
        patch("app.processmgr.service._get_max_open_files", return_value=1024),
        patch("app.processmgr.service._get_oom_score", return_value=100),
        patch(
            "app.processmgr.service._get_limits",
            return_value=service.ProcessLimits(
                max_open_files_soft="1024",
                max_open_files_hard="4096",
            ),
        ),
    ):
        result = service.get_process_detail(1234)

    assert result.pid == 1234
    assert result.current_open_files == 50
    assert result.max_open_files == 1024
    assert result.open_files_warning is False
    assert result.oom_score == 100
    assert result.open_files_usage_percent == pytest.approx(4.88, abs=0.1)


def test_get_process_detail_warning():
    proc = _mock_process(pid=1234)
    full_mem = MagicMock()
    full_mem.pss = 0
    full_mem.uss = 0
    proc.memory_full_info.return_value = full_mem

    with (
        patch("app.processmgr.service.psutil.Process", return_value=proc),
        patch("app.processmgr.service._get_open_file_count", return_value=950),
        patch("app.processmgr.service._get_max_open_files", return_value=1024),
        patch("app.processmgr.service._get_oom_score", return_value=0),
        patch(
            "app.processmgr.service._get_limits",
            return_value=service.ProcessLimits(),
        ),
    ):
        result = service.get_process_detail(1234)

    assert result.open_files_warning is True
    assert result.open_files_usage_percent >= 90.0


def test_get_process_detail_not_found():
    with patch(
        "app.processmgr.service.psutil.Process",
        side_effect=psutil.NoSuchProcess(9999),
    ):
        with pytest.raises(ProcessLookupError):
            service.get_process_detail(9999)


# ---------------------------------------------------------------------------
# 7. Too many open files
# ---------------------------------------------------------------------------


def test_list_too_many_open_files():
    proc1 = MagicMock(spec=psutil.Process)
    proc1.pid = 100
    proc1.name.return_value = "safe"
    proc1.username.return_value = "root"

    proc2 = MagicMock(spec=psutil.Process)
    proc2.pid = 200
    proc2.name.return_value = "risky"
    proc2.username.return_value = "root"

    def open_count(pid):
        return {100: 10, 200: 950}[pid]

    def max_open(pid):
        return {100: 1024, 200: 1024}[pid]

    with (
        patch("app.processmgr.service.psutil.process_iter", return_value=[proc1, proc2]),
        patch("app.processmgr.service._get_open_file_count", side_effect=open_count),
        patch("app.processmgr.service._get_max_open_files", side_effect=max_open),
    ):
        result = service.list_too_many_open_files(threshold=90.0)

    assert result.total == 1
    assert result.processes[0].pid == 200
    assert result.processes[0].usage_percent >= 90.0


def test_list_too_many_open_files_empty():
    proc = MagicMock(spec=psutil.Process)
    proc.pid = 100
    proc.name.return_value = "safe"
    proc.username.return_value = "root"

    with (
        patch("app.processmgr.service.psutil.process_iter", return_value=[proc]),
        patch("app.processmgr.service._get_open_file_count", return_value=10),
        patch("app.processmgr.service._get_max_open_files", return_value=1024),
    ):
        result = service.list_too_many_open_files()

    assert result.total == 0


# ---------------------------------------------------------------------------
# 8. CPU usage list
# ---------------------------------------------------------------------------


def test_list_process_cpu():
    procs = [
        _mock_process(pid=1, cpu_percent=1.0),
        _mock_process(pid=2, cpu_percent=50.0),
        _mock_process(pid=3, cpu_percent=25.0),
    ]
    with patch("app.processmgr.service.psutil.process_iter", return_value=procs):
        result = service.list_process_cpu(limit=2)

    assert result.total == 2
    assert result.processes[0].cpu_percent == 50.0
    assert result.processes[1].cpu_percent == 25.0


def test_list_process_cpu_all():
    procs = [_mock_process(pid=i, cpu_percent=float(i)) for i in range(5)]
    with patch("app.processmgr.service.psutil.process_iter", return_value=procs):
        result = service.list_process_cpu(limit=0)

    assert result.total == 5


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


def test_parse_limits():
    content = (
        "Limit                     Soft Limit           Hard Limit           Units     \n"
        "Max cpu time              unlimited            unlimited            seconds   \n"
        "Max open files            1024                 4096                 files     \n"
        "Max processes             63328                63328                processes \n"
        "Max stack size            8388608              unlimited            bytes     \n"
    )
    with patch("app.processmgr.service._read_proc_file", return_value=content):
        limits = service._get_limits(1234)

    assert limits.max_open_files_soft == "1024"
    assert limits.max_open_files_hard == "4096"
    assert limits.max_processes_soft == "63328"
    assert limits.max_stack_size_hard == "unlimited"


def test_get_oom_score():
    with patch("app.processmgr.service._read_proc_file", return_value="150\n"):
        score = service._get_oom_score(1234)
    assert score == 150


def test_get_oom_score_error():
    with patch("app.processmgr.service._read_proc_file", return_value=""):
        score = service._get_oom_score(1234)
    assert score == 0
