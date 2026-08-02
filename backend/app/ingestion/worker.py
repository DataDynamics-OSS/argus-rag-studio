# SPDX-License-Identifier: Apache-2.0
"""인제스천 비동기 워커.

``queued`` 잡을 주기적으로 폴링해 한 건씩 처리한다. M1 의 스케줄러 패턴과 동일하게
``app/main.py`` lifespan 에서 ``asyncio.create_task`` 로 기동하고, 종료 시 취소한다.

단일 프로세스 개발 환경을 기본으로 하되, ``claim_next_job`` 이 ``FOR UPDATE SKIP LOCKED``
를 쓰므로 워커를 여러 개 띄워도 한 잡을 한 워커만 가져간다(수평 확장 여지).
"""

import asyncio
import logging

from app.core.config import settings
from app.core.database import async_session
from app.ingestion.models import RagIngestionJob
from app.ingestion.service import claim_next_job, run_pipeline
from app.workers.runtime import runtime as worker_runtime

logger = logging.getLogger(__name__)


async def ingestion_worker_loop() -> None:
    """무한 루프: 잡을 집어 처리하고, 없으면 잠시 대기한다."""
    interval = settings.ingestion_worker_interval
    logger.info("인제스천 워커 시작 (interval=%.1fs)", interval)
    while True:
        try:
            # 1) 잡을 원자적으로 집는다(짧은 트랜잭션)
            async with async_session() as session:
                claimed = await claim_next_job(session)
                job_id = claimed.id if claimed else None

            if job_id is None:
                await asyncio.sleep(interval)
                continue

            # 2) 별도 세션에서 처리한다(긴 작업이므로 lock 을 오래 잡지 않음).
            #    워커 상태를 busy 로 표시하고(모니터링), 끝나면 idle + 처리량 +1.
            worker_runtime.job_started(claimed.job_id if claimed else None)
            try:
                async with async_session() as session:
                    job = await session.get(RagIngestionJob, job_id)
                    if job is not None:
                        await run_pipeline(session, job)
            finally:
                worker_runtime.job_finished()
        except asyncio.CancelledError:
            logger.info("인제스천 워커 종료")
            raise
        except Exception as e:
            logger.warning("인제스천 워커 루프 오류: %s", e, exc_info=True)
            await asyncio.sleep(interval)
