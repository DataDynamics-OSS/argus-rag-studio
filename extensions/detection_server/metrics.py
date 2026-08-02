# SPDX-License-Identifier: Apache-2.0
"""런타임 메트릭 — 시스템(CPU/RAM/디스크)·GPU·요청·모델 수집(원격 모니터링용).

두 형식으로 노출한다(main 이 엔드포인트 연결):
  - ``snapshot()``  : JSON (GET /stats)
  - ``prometheus()``: Prometheus 텍스트 (GET /metrics)

의존성은 선택적이다 — ``psutil`` 없으면 시스템 메트릭 일부 생략, GPU(pynvml) 없으면 GPU 생략.
어떤 경우에도 예외를 던지지 않는다(모니터링이 서비스를 막지 않음). 서버 패키지에 비의존이라
모든 확장 서버에 동일 파일을 둔다.
"""
from __future__ import annotations

import os
import shutil
import threading
import time
from typing import Callable

try:  # 가벼운 시스템 메트릭(선택)
    import psutil  # type: ignore
except Exception:  # noqa: BLE001
    psutil = None  # type: ignore

_START = time.time()
_lock = threading.Lock()
_CACHE_TTL = 1.5
_cache: dict = {"ts": 0.0, "data": None}

_info: dict = {"server": "extension", "version": "", "device": "cpu", "model": "", "cache_dir": ""}
_models_provider: Callable[[], dict] | None = None

# 요청 카운터(미들웨어가 갱신)
_req = {"total": 0, "errors": 0, "inflight": 0, "by_status": {}, "lat_sum": 0.0, "lat_count": 0}
# 도메인 카운터(핸들러/엔진이 갱신) — 예: embed_items_total / rerank_docs_total / detect_images_total
_domain: dict = {}

_nvml_state: bool | None = None  # None=미시도, True=가능, False=불가(이후 생략)
_torch_state: bool | None = None  # torch 메모리 폴백 가용 여부(GB10 등 NVML 메모리 미지원 보강)


def set_info(**kw) -> None:
    _info.update({k: v for k, v in kw.items() if v is not None})


def set_models_provider(fn: Callable[[], dict]) -> None:
    global _models_provider
    _models_provider = fn


def req_start() -> None:
    with _lock:
        _req["inflight"] += 1


def req_end(status: int, dur: float, error: bool = False) -> None:
    with _lock:
        _req["inflight"] = max(0, _req["inflight"] - 1)
        _req["total"] += 1
        _req["lat_sum"] += dur
        _req["lat_count"] += 1
        sc = str(status)
        _req["by_status"][sc] = _req["by_status"].get(sc, 0) + 1
        if error or status >= 500:
            _req["errors"] += 1


def incr(name: str, n: int = 1) -> None:
    with _lock:
        _domain[name] = _domain.get(name, 0) + n


def _req_snapshot() -> dict:
    with _lock:
        avg = (_req["lat_sum"] / _req["lat_count"]) if _req["lat_count"] else 0.0
        return {
            "total": _req["total"],
            "inflight": _req["inflight"],
            "errors": _req["errors"],
            "by_status": dict(_req["by_status"]),
            "avg_latency_ms": round(avg * 1000, 1),
            "domain": dict(_domain),
        }


def _torch_fill_memory(gpus: list[dict]) -> list[dict]:
    """torch 로 GPU 메모리를 보강한다. NVML 메모리가 미지원(예: GB10 통합메모리)이거나
    NVML 자체가 없을 때 ``mem_used/mem_total`` 을 채우고, 이 프로세스의 reserved/allocated 도 더한다.
    torch 미설치/CPU 환경에서는 조용히 건너뛴다(어떤 예외도 던지지 않음)."""
    global _torch_state
    if _torch_state is False:
        return gpus
    try:
        import torch  # type: ignore

        if not torch.cuda.is_available():
            _torch_state = False
            return gpus
        _torch_state = True
        if not gpus:  # NVML 이 비어 있으면 torch 로 디바이스 목록 구성
            gpus = [{"index": i} for i in range(torch.cuda.device_count())]
        for g in gpus:
            i = g.get("index", 0)
            if not g.get("name"):
                try:
                    g["name"] = torch.cuda.get_device_name(i)
                except Exception:  # noqa: BLE001
                    pass
            if g.get("mem_used_bytes") is None or g.get("mem_total_bytes") is None:
                try:
                    free, total = torch.cuda.mem_get_info(i)
                    g["mem_total_bytes"] = int(total)
                    g["mem_used_bytes"] = int(total - free)
                except Exception:  # noqa: BLE001
                    pass
            try:  # 이 서버 프로세스가 GPU 에 잡은 메모리(정보성)
                g["mem_reserved_bytes"] = int(torch.cuda.memory_reserved(i))
                g["mem_allocated_bytes"] = int(torch.cuda.memory_allocated(i))
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001 — torch 미설치 등
        _torch_state = False
    return gpus


def _gpu_snapshot() -> list[dict]:
    """GPU 메트릭. NVML 필드는 개별 보호(일부 미지원이 전체를 막지 않음), 메모리는 torch 로 보강.

    GB10(통합메모리)은 NVML ``nvmlDeviceGetMemoryInfo`` 가 NotSupported 라 util/temp/power 만
    NVML 로 얻고 메모리는 torch ``mem_get_info`` 로 채운다.
    """
    global _nvml_state
    gpus: list[dict] = []
    if _nvml_state is not False:
        try:
            import pynvml  # type: ignore

            if _nvml_state is None:
                pynvml.nvmlInit()
                _nvml_state = True
            for i in range(pynvml.nvmlDeviceGetCount()):
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                g: dict = {"index": i}
                try:
                    name = pynvml.nvmlDeviceGetName(h)
                    g["name"] = name.decode("utf-8", "ignore") if isinstance(name, bytes) else name
                except Exception:  # noqa: BLE001
                    pass
                try:
                    g["utilization_percent"] = pynvml.nvmlDeviceGetUtilizationRates(h).gpu
                except Exception:  # noqa: BLE001
                    pass
                try:  # GB10 통합메모리는 여기서 NotSupported → torch 로 보강
                    mem = pynvml.nvmlDeviceGetMemoryInfo(h)
                    g["mem_used_bytes"], g["mem_total_bytes"] = mem.used, mem.total
                except Exception:  # noqa: BLE001
                    pass
                try:
                    g["temperature_c"] = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    g["power_w"] = round(pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0, 1)
                except Exception:  # noqa: BLE001
                    pass
                gpus.append(g)
        except Exception:  # noqa: BLE001 — nvmlInit/Count 실패 → NVML 비활성, torch 폴백 시도
            _nvml_state = False
            gpus = []
    return _torch_fill_memory(gpus)


def _build_snapshot() -> dict:
    out = {
        "server": _info["server"], "version": _info["version"],
        "device": _info["device"], "model": _info["model"],
        "uptime_seconds": int(time.time() - _START),
    }
    sysd: dict = {}
    if psutil is not None:
        try:
            sysd["cpu_percent"] = psutil.cpu_percent(interval=None)
            vm = psutil.virtual_memory()
            sysd["mem_used_bytes"] = vm.used
            sysd["mem_total_bytes"] = vm.total
            sysd["mem_percent"] = vm.percent
            p = psutil.Process()
            with p.oneshot():
                sysd["process_rss_bytes"] = p.memory_info().rss
                sysd["process_cpu_percent"] = p.cpu_percent(interval=None)
                sysd["threads"] = p.num_threads()
                try:
                    sysd["open_fds"] = p.num_fds()
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass
    try:
        la = os.getloadavg()
        sysd["load1"], sysd["load5"], sysd["load15"] = (round(la[0], 2), round(la[1], 2), round(la[2], 2))
    except Exception:  # noqa: BLE001 — Windows 등
        pass
    out["system"] = sysd

    try:
        du = shutil.disk_usage(_info.get("cache_dir") or "/")
        out["disk"] = {"used_bytes": du.used, "total_bytes": du.total}
    except Exception:  # noqa: BLE001
        out["disk"] = {}

    out["gpu"] = _gpu_snapshot()
    try:
        out["models"] = _models_provider() if _models_provider else {}
    except Exception:  # noqa: BLE001
        out["models"] = {}
    out["requests"] = _req_snapshot()
    return out


def snapshot() -> dict:
    """시스템/GPU/모델/요청 스냅샷(1.5초 캐시 — 스크레이프 폭주 방지). 요청 카운터는 항상 최신."""
    now = time.time()
    with _lock:
        cached = _cache["data"]
        fresh = cached is not None and (now - _cache["ts"]) < _CACHE_TTL
    if fresh:
        d = dict(cached)
        d["requests"] = _req_snapshot()
        return d
    data = _build_snapshot()
    with _lock:
        _cache["ts"] = now
        _cache["data"] = data
    return data


def _line(out: list, name: str, val, labels: str = "") -> None:
    if val is None:
        return
    out.append(f"{name}{labels} {val}")


def prometheus() -> str:
    """Prometheus 텍스트 노출(의존성 없이 직접 생성)."""
    d = snapshot()
    out: list[str] = []
    _line(out, "argus_ext_up", 1)
    _line(out, "argus_ext_uptime_seconds", d.get("uptime_seconds"))
    s = d.get("system", {})
    _line(out, "argus_ext_cpu_percent", s.get("cpu_percent"))
    _line(out, "argus_ext_mem_used_bytes", s.get("mem_used_bytes"))
    _line(out, "argus_ext_mem_total_bytes", s.get("mem_total_bytes"))
    _line(out, "argus_ext_mem_percent", s.get("mem_percent"))
    _line(out, "argus_ext_process_rss_bytes", s.get("process_rss_bytes"))
    _line(out, "argus_ext_load1", s.get("load1"))
    dk = d.get("disk", {})
    _line(out, "argus_ext_disk_used_bytes", dk.get("used_bytes"))
    _line(out, "argus_ext_disk_total_bytes", dk.get("total_bytes"))
    for gpu in d.get("gpu", []):
        lbl = f'{{gpu="{gpu.get("index")}"}}'
        _line(out, "argus_ext_gpu_utilization_percent", gpu.get("utilization_percent"), lbl)
        _line(out, "argus_ext_gpu_mem_used_bytes", gpu.get("mem_used_bytes"), lbl)
        _line(out, "argus_ext_gpu_mem_total_bytes", gpu.get("mem_total_bytes"), lbl)
        _line(out, "argus_ext_gpu_temperature_celsius", gpu.get("temperature_c"), lbl)
        _line(out, "argus_ext_gpu_power_watts", gpu.get("power_w"), lbl)
    r = d.get("requests", {})
    _line(out, "argus_ext_requests_total", r.get("total"))
    _line(out, "argus_ext_inflight_requests", r.get("inflight"))
    _line(out, "argus_ext_errors_total", r.get("errors"))
    _line(out, "argus_ext_request_avg_latency_ms", r.get("avg_latency_ms"))
    for k, v in (r.get("domain") or {}).items():
        _line(out, f"argus_ext_{k}", v)
    _line(out, "argus_ext_models_loaded", (d.get("models") or {}).get("count"))
    out.append(
        f'argus_ext_build_info{{server="{d.get("server")}",version="{d.get("version")}",'
        f'device="{d.get("device")}",model="{d.get("model")}"}} 1'
    )
    return "\n".join(out) + "\n"
