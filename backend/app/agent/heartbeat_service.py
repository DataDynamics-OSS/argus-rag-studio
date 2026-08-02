# SPDX-License-Identifier: Apache-2.0
"""하트비트 처리 서비스.

에이전트 하트비트 수신을 처리한다: 신규 에이전트는 UNREGISTERED 로 INSERT,
기존 에이전트는 최신 메트릭으로 UPDATE, 그리고 하트비트 타임스탬프를 갱신한다.
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import ArgusAgent, ArgusAgentHeartbeat
from app.agent.schemas import HeartbeatRequest

logger = logging.getLogger(__name__)


async def process_heartbeat(session: AsyncSession, req: HeartbeatRequest) -> None:
    """하트비트를 처리한다.

    1. argus_agents: 신규면 INSERT(status=UNREGISTERED), 있으면 메트릭 UPDATE.
    2. argus_agents_heartbeat: last_heartbeat_at=now() UPSERT.
    """
    logger.debug("Heartbeat received: %s", json.dumps(req.model_dump(), ensure_ascii=False))

    now = datetime.now(timezone.utc)

    # --- argus_agents ---
    result = await session.execute(
        select(ArgusAgent).where(ArgusAgent.hostname == req.hostname)
    )
    agent = result.scalar_one_or_none()

    if agent is None:
        # 이 에이전트의 첫 하트비트: UNREGISTERED 로 INSERT
        agent = ArgusAgent(
            hostname=req.hostname,
            ip_address=req.ip_address,
            version=req.version,
            kernel_version=req.kernel_version,
            os_version=req.os_version,
            arch=req.arch,
            cpu_count=req.cpu_count,
            core_count=req.core_count,
            total_memory=req.total_memory,
            cpu_usage=req.cpu_usage,
            memory_usage=req.memory_usage,
            disk_swap_percent=req.disk_swap_percent,
            gpu_count=req.gpu_count,
            gpu_usage=req.gpu_usage,
            gpu_memory_usage=req.gpu_memory_usage,
            gpu_memory_total=req.gpu_memory_total,
            gpu_name=req.gpu_name,
            status="UNREGISTERED",
            created_at=now,
            updated_at=now,
        )
        session.add(agent)
        logger.info("New agent registered: hostname=%s, status=UNREGISTERED", req.hostname)
    else:
        # 기존 에이전트: 동적 필드만 UPDATE(현재 status 유지). 단 DISCONNECTED 는
        # 하트비트가 재개되면 REGISTERED 로 복원한다. DISCONNECTED 는 disconnect_checker 가
        # "REGISTERED 였던" 에이전트에만 부여하므로(아래 disconnect_checker 참고), 재연결 시
        # 등록 상태를 그대로 되살리는 것이 올바르다(잠깐 끊겼다고 등록이 풀리면 안 됨).
        if agent.status == "DISCONNECTED":
            logger.info(
                "Agent heartbeat resumed: hostname=%s, status DISCONNECTED -> REGISTERED",
                req.hostname,
            )
            agent.status = "REGISTERED"
        agent.ip_address = req.ip_address
        agent.version = req.version
        agent.kernel_version = req.kernel_version
        agent.os_version = req.os_version
        agent.arch = req.arch
        agent.cpu_count = req.cpu_count
        agent.core_count = req.core_count
        agent.total_memory = req.total_memory
        agent.cpu_usage = req.cpu_usage
        agent.memory_usage = req.memory_usage
        agent.disk_swap_percent = req.disk_swap_percent
        agent.gpu_count = req.gpu_count
        agent.gpu_usage = req.gpu_usage
        agent.gpu_memory_usage = req.gpu_memory_usage
        agent.gpu_memory_total = req.gpu_memory_total
        agent.gpu_name = req.gpu_name
        agent.updated_at = now

    # --- argus_agents_heartbeat ---
    hb_result = await session.execute(
        select(ArgusAgentHeartbeat).where(ArgusAgentHeartbeat.hostname == req.hostname)
    )
    heartbeat = hb_result.scalar_one_or_none()

    if heartbeat is None:
        heartbeat = ArgusAgentHeartbeat(hostname=req.hostname, last_heartbeat_at=now)
        session.add(heartbeat)
    else:
        heartbeat.last_heartbeat_at = now

    await session.commit()
