# SPDX-License-Identifier: Apache-2.0
"""에이전트 관리 ORM 모델."""

from sqlalchemy import BigInteger, Column, DateTime, Float, Integer, String, func

from app.core.database import Base


class ArgusAgent(Base):
    """에이전트 마스터 — 호스트 신원 + 최신 리소스 사용량 + 등록 상태."""

    __tablename__ = "argus_agents"

    hostname = Column(String(255), primary_key=True)
    ip_address = Column(String(45), nullable=False)
    version = Column(String(50))
    kernel_version = Column(String(255))
    os_version = Column(String(255))
    arch = Column(String(16))
    cpu_count = Column(Integer)
    core_count = Column(Integer)
    total_memory = Column(BigInteger)
    cpu_usage = Column(Float)
    memory_usage = Column(Float)
    disk_swap_percent = Column(Float)
    gpu_count = Column(Integer)
    gpu_usage = Column(Float)
    gpu_memory_usage = Column(Float)
    gpu_memory_total = Column(BigInteger)
    gpu_name = Column(String(255))
    status = Column(String(20), nullable=False, default="UNREGISTERED")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ArgusAgentHeartbeat(Base):
    """에이전트별 마지막 하트비트 타임스탬프 추적."""

    __tablename__ = "argus_agents_heartbeat"

    hostname = Column(String(255), primary_key=True)
    last_heartbeat_at = Column(DateTime(timezone=True), server_default=func.now())
