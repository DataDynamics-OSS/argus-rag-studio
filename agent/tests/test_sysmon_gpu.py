"""GPU 메트릭 수집 — 디스크리트(A100/H100 풀) vs 통합메모리(GB10 N/A) 내성."""

from unittest.mock import MagicMock, patch

from app.heartbeat import system_info
from app.heartbeat.system_info import get_gpu_info
from app.sysmon.service import get_gpu_usage


def _completed(stdout: str, rc: int = 0) -> MagicMock:
    m = MagicMock()
    m.returncode = rc
    m.stdout = stdout
    return m


# ---------------------------------------------------------------------------
# sysmon/gpu — per-GPU
# ---------------------------------------------------------------------------


def test_discrete_a100_full_metrics():
    # index,name,util,mem_total,mem_used,temp,power,power_limit
    out = (
        "0, NVIDIA A100-SXM4-80GB, 73, 81920, 42100, 61, 310.5, 400\n"
        "1, NVIDIA A100-SXM4-80GB, 5, 81920, 1024, 40, 62, 400\n"
    )
    with (
        patch("app.sysmon.service.shutil.which", return_value="/usr/bin/nvidia-smi"),
        patch("app.sysmon.service.subprocess.run", return_value=_completed(out)),
    ):
        r = get_gpu_usage()

    assert r.available is True
    assert r.count == 2
    g0 = r.gpus[0]
    assert g0.index == 0
    assert g0.name == "NVIDIA A100-SXM4-80GB"
    assert g0.util_percent == 73.0
    assert g0.mem_total_mb == 81920.0
    assert g0.mem_used_mb == 42100.0
    assert g0.temp_c == 61.0
    assert g0.power_w == 310.5
    assert g0.power_limit_w == 400.0


def test_gb10_unified_memory_na_tolerant():
    out = "0, NVIDIA GB10, 12, [N/A], [N/A], 48, 35.2, [N/A]\n"
    with (
        patch("app.sysmon.service.shutil.which", return_value="/usr/bin/nvidia-smi"),
        patch("app.sysmon.service.subprocess.run", return_value=_completed(out)),
    ):
        r = get_gpu_usage()

    assert r.available is True
    assert r.count == 1
    g = r.gpus[0]
    assert g.name == "NVIDIA GB10"
    assert g.util_percent == 12.0
    # 통합메모리: memory/power_limit 는 N/A → None (GPU 자체는 그대로 보고)
    assert g.mem_total_mb is None
    assert g.mem_used_mb is None
    assert g.temp_c == 48.0
    assert g.power_w == 35.2
    assert g.power_limit_w is None


def test_no_nvidia_smi():
    with patch("app.sysmon.service.shutil.which", return_value=None):
        r = get_gpu_usage()
    assert r.available is False
    assert r.count == 0
    assert r.gpus == []


# ---------------------------------------------------------------------------
# heartbeat 집계 — gpu_memory_total
# ---------------------------------------------------------------------------


def test_heartbeat_aggregate_discrete_total_vram():
    # util,mem_total,mem_used,name
    out = "73, 81920, 42100, NVIDIA A100\n5, 81920, 1024, NVIDIA A100\n"
    system_info._no_nvidia_smi = False
    with (
        patch("app.heartbeat.system_info.shutil.which", return_value="/usr/bin/nvidia-smi"),
        patch("app.heartbeat.system_info.subprocess.run", return_value=_completed(out)),
    ):
        info = get_gpu_info()

    assert info["gpu_count"] == 2
    assert info["gpu_name"] == "NVIDIA A100"
    assert info["gpu_memory_total"] == 163840  # 2 × 80GiB 합계
    assert info["gpu_usage"] == 39.0  # (73+5)/2


def test_heartbeat_aggregate_gb10_total_none():
    out = "12, [N/A], [N/A], NVIDIA GB10\n"
    system_info._no_nvidia_smi = False
    with (
        patch("app.heartbeat.system_info.shutil.which", return_value="/usr/bin/nvidia-smi"),
        patch("app.heartbeat.system_info.subprocess.run", return_value=_completed(out)),
    ):
        info = get_gpu_info()

    assert info["gpu_count"] == 1
    assert info["gpu_memory_total"] is None
    assert info["gpu_memory_usage"] is None
    assert info["gpu_usage"] == 12.0
