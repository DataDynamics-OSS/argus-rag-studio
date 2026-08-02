# SPDX-License-Identifier: Apache-2.0
"""워커 런타임 — 프로세스 1개의 정체성/상태를 들고, DB 에 등록·하트비트한다.

인제스천 워커 루프가 잡을 집고 끝낼 때 ``job_started``/``job_finished`` 를 호출해 상태를
갱신하고, 백그라운드 하트비트 루프가 주기적으로 DB 행을 upsert 한다. API 와 동거(in-process)
하든 분리(standalone)하든 동일하게 동작하며, 여러 워커가 각자 행을 가진다.
"""

import asyncio
import logging
import os
import socket
import uuid
from datetime import datetime, timezone

from app import __version__
from app.core.database import async_session

logger = logging.getLogger("argus.workers.runtime")

HEARTBEAT_INTERVAL = 5.0  # 초 — 하트비트 주기(생존 판정은 이보다 넉넉히)


class _Runtime:
    def __init__(self) -> None:
        self.worker_id = uuid.uuid4().hex
        self.hostname = socket.gethostname()
        self.pid = os.getpid()
        self.version = __version__
        self.mode = "in_process"
        # 배포 방식 — 배포 오케스트레이터(빌더)가 env 로 주입(docker|systemd|k8s). 없으면 직접 실행.
        self.deploy_runtime = os.environ.get("ARGUS_WORKER_RUNTIME") or None
        self.status = "starting"
        self.current_job_id: str | None = None
        self.processed_total = 0
        self._task: asyncio.Task | None = None
        self._registered = False

    def job_started(self, job_id: str | None) -> None:
        self.status = "busy"
        self.current_job_id = job_id

    def job_finished(self) -> None:
        self.status = "idle"
        self.current_job_id = None
        self.processed_total += 1


runtime = _Runtime()

_proc = None  # psutil.Process 핸들(cpu_percent 는 직전 호출 이후 사용률을 재므로 재사용·프라이밍 필요)
_nvml_state: bool | None = None  # None=미시도, True=가능, False=불가(이후 GPU 수집 생략)


def _gpu_metrics() -> list[dict] | None:
    """워커 호스트의 GPU 메트릭(NVML). GPU/드라이버 없으면 None.

    필드별로 보호하므로 일부 미지원(예: GB10 통합메모리의 메모리 쿼리)이 전체를 막지 않고,
    메모리가 NVML 로 안 잡히면 torch(설치돼 있으면)로 보강한다.
    """
    global _nvml_state
    if _nvml_state is False:
        return None
    gpus: list[dict] = []
    try:
        import pynvml

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
            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(h)
                g["mem_used_bytes"], g["mem_total_bytes"] = mem.used, mem.total
            except Exception:  # noqa: BLE001 — GB10 통합메모리 등은 NotSupported → torch 로 보강
                pass
            try:
                g["temperature_c"] = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
            except Exception:  # noqa: BLE001
                pass
            gpus.append(g)
    except Exception as e:  # noqa: BLE001 — pynvml 미설치/드라이버 없음 → 이후 생략
        _nvml_state = False
        logger.debug("NVML GPU 메트릭 비활성: %s", e)
        return None

    # NVML 로 메모리를 못 채운 장치는 torch(CUDA)로 보강(GB10 등)
    if gpus and any(g.get("mem_total_bytes") is None for g in gpus):
        try:
            import torch

            if torch.cuda.is_available():
                for g in gpus:
                    if g.get("mem_total_bytes") is None:
                        free, total = torch.cuda.mem_get_info(g["index"])
                        g["mem_total_bytes"], g["mem_used_bytes"] = int(total), int(total - free)
        except Exception:  # noqa: BLE001 — torch 미설치/CPU 빌드
            pass
    return gpus or None


def _collect_metrics() -> dict | None:
    """이 워커 프로세스 + 호스트의 CPU/RAM 메트릭. psutil 없으면 None."""
    global _proc
    try:
        import psutil
    except Exception:  # noqa: BLE001 — psutil 미설치
        return None

    m: dict = {}
    try:
        if _proc is None:
            _proc = psutil.Process()
            _proc.cpu_percent(None)   # 프로세스 CPU 프라이밍(첫 호출은 0)
            psutil.cpu_percent(None)  # 호스트 CPU 프라이밍
        with _proc.oneshot():
            m["cpu_percent"] = round(_proc.cpu_percent(None), 1)   # 직전 하트비트 이후 프로세스 CPU%
            m["rss_bytes"] = _proc.memory_info().rss
            m["threads"] = _proc.num_threads()
        vm = psutil.virtual_memory()
        m["host_cpu_percent"] = round(psutil.cpu_percent(None), 1)
        m["host_mem_used_bytes"] = vm.used
        m["host_mem_total_bytes"] = vm.total
        m["host_mem_percent"] = vm.percent
        try:
            m["load1"] = round(os.getloadavg()[0], 2)
        except (OSError, AttributeError):
            pass
    except Exception as e:  # noqa: BLE001 — 메트릭 실패가 하트비트를 막지 않는다
        logger.debug("워커 메트릭 수집 실패: %s", e)

    gpu = _gpu_metrics()
    if gpu:
        m["gpu"] = gpu
    return m or None


async def _upsert(status: str | None = None) -> None:
    """현재 런타임 상태를 DB 에 upsert(없으면 insert, 있으면 update)."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.workers.models import RagWorker

    if status is not None:
        runtime.status = status
    now = datetime.now(timezone.utc)
    mutable = dict(
        hostname=runtime.hostname, pid=runtime.pid, mode=runtime.mode,
        runtime=runtime.deploy_runtime, version=runtime.version, status=runtime.status,
        current_job_id=runtime.current_job_id, processed_total=runtime.processed_total,
        metrics=_collect_metrics(), last_heartbeat_at=now,
    )
    stmt = pg_insert(RagWorker).values(id=runtime.worker_id, started_at=now, **mutable)
    stmt = stmt.on_conflict_do_update(index_elements=[RagWorker.id], set_=mutable)
    async with async_session() as session:
        await session.execute(stmt)
        await session.commit()


async def _heartbeat_loop() -> None:
    while True:
        try:
            await _upsert()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — 하트비트 실패가 워커를 죽이지 않는다
            logger.warning("워커 하트비트 실패: %s", e)
        await asyncio.sleep(HEARTBEAT_INTERVAL)


async def start(mode: str = "in_process") -> None:
    """워커를 등록하고 하트비트 루프를 띄운다. DB 미가용이어도 워커는 계속 동작한다."""
    runtime.mode = mode
    try:
        await _upsert(status="idle")
        runtime._registered = True
    except Exception as e:  # noqa: BLE001
        logger.warning("워커 등록 실패(계속 진행): %s", e)
    runtime._task = asyncio.create_task(_heartbeat_loop(), name="worker-heartbeat")
    logger.info("워커 등록: id=%s host=%s pid=%s mode=%s",
                runtime.worker_id, runtime.hostname, runtime.pid, mode)


async def stop() -> None:
    """하트비트 중단 + 상태를 stopped 로 표시(등록된 적 있을 때만)."""
    if runtime._task is not None:
        runtime._task.cancel()
        try:
            await runtime._task
        except asyncio.CancelledError:
            pass
        runtime._task = None
    if runtime._registered:
        try:
            await _upsert(status="stopped")
        except Exception:  # noqa: BLE001
            pass
