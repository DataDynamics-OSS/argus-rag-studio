# SPDX-License-Identifier: Apache-2.0
"""워커 모니터링 스키마."""

from datetime import datetime

from pydantic import BaseModel


class WorkerInfo(BaseModel):
    """워커 1개 상태 + 하트비트 기반 생존 판정."""

    id: str
    hostname: str | None = None
    pid: int | None = None
    mode: str | None = None                  # in_process | standalone
    runtime: str | None = None               # 배포 방식: docker|systemd|k8s|None(직접 실행)
    version: str | None = None
    status: str                              # starting|idle|busy|stopped
    current_job_id: str | None = None
    processed_total: int
    started_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    heartbeat_age_seconds: float | None = None   # 마지막 하트비트 경과(초)
    alive: bool                               # 최근 하트비트가 임계 내면 true
    metrics: dict | None = None               # 프로세스/호스트 CPU·RAM 등 리소스 메트릭
