# SPDX-License-Identifier: Apache-2.0
"""하트비트가 멈춘 에이전트를 DISCONNECTED 로 표시하는 백그라운드 작업.

기본 60초마다 실행. 마지막 하트비트가 타임아웃(기본 3분)을 초과하면
argus_agents.status 를 DISCONNECTED 로 변경한다.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.agent.models import ArgusAgent, ArgusAgentHeartbeat
from app.core.config import settings
from app.core.database import async_session

logger = logging.getLogger(__name__)


class DisconnectChecker:
    """주기적으로 타임아웃된 에이전트를 찾아 DISCONNECTED 로 표시한다."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info(
            "Disconnect checker started (interval=%ds, timeout=%ds)",
            settings.agent_heartbeat_check_interval,
            settings.agent_heartbeat_disconnect_timeout,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Disconnect checker stopped")

    async def _run(self) -> None:
        while self._running:
            try:
                await self._check_disconnected()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in disconnect checker loop")
            try:
                await asyncio.sleep(settings.agent_heartbeat_check_interval)
            except asyncio.CancelledError:
                break

    async def _check_disconnected(self) -> None:
        timeout = timedelta(seconds=settings.agent_heartbeat_disconnect_timeout)
        threshold = datetime.now(timezone.utc) - timeout

        async with async_session() as session:
            result = await session.execute(
                select(ArgusAgentHeartbeat.hostname).where(
                    ArgusAgentHeartbeat.last_heartbeat_at < threshold
                )
            )
            stale_hostnames = [row[0] for row in result.all()]

            if not stale_hostnames:
                return

            # REGISTERED 였던 에이전트만 DISCONNECTED 로 표시한다. 그래야 DISCONNECTED 가
            # "관리 중이었는데 끊김"을 정확히 의미하고, 재연결 시 REGISTERED 로 복원할 수 있다.
            # (UNREGISTERED 에이전트가 사라지면 그냥 UNREGISTERED 로 남는다.)
            stmt = (
                update(ArgusAgent)
                .where(
                    ArgusAgent.hostname.in_(stale_hostnames),
                    ArgusAgent.status == "REGISTERED",
                )
                .values(status="DISCONNECTED", updated_at=datetime.now(timezone.utc))
            )
            result = await session.execute(stmt)
            await session.commit()

            if result.rowcount > 0:
                logger.warning(
                    "Marked %d agent(s) as DISCONNECTED (no heartbeat for %ds): %s",
                    result.rowcount,
                    settings.agent_heartbeat_disconnect_timeout,
                    stale_hostnames,
                )


disconnect_checker = DisconnectChecker()
