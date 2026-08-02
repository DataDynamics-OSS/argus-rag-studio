# SPDX-License-Identifier: Apache-2.0
"""워커 레지스트리 ORM 모델.

워커 프로세스(또는 API in-process 워커)가 기동 시 한 행을 등록하고 주기적으로
``last_heartbeat_at`` 을 갱신한다. API 는 이 표를 읽어 살아있는 워커·현재 잡·처리량을 보여준다.
"""

from sqlalchemy import Column, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class RagWorker(Base):
    """워커 1개(=프로세스 1개) 상태. ``id`` 는 프로세스 기동 시 생성한 uuid."""

    __tablename__ = "argus_workers"

    id = Column(String(64), primary_key=True)          # 프로세스당 uuid hex
    hostname = Column(String(255))
    pid = Column(Integer)
    mode = Column(String(20))                          # in_process(API 동거) | standalone(분리)
    runtime = Column(String(20))                       # 배포 방식: docker|systemd|k8s|NULL(직접 실행)
    version = Column(String(40))
    status = Column(String(20), nullable=False, default="idle", server_default="idle")  # starting|idle|busy|stopped
    current_job_id = Column(String(64))                # 처리 중인 잡의 job_id(uuid), idle 이면 NULL
    processed_total = Column(Integer, nullable=False, default=0, server_default="0")
    # 리소스 메트릭 — 프로세스/호스트 CPU·RAM 등(하트비트마다 갱신). 유연한 JSONB.
    metrics = Column(JSONB)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    last_heartbeat_at = Column(DateTime(timezone=True), server_default=func.now())
