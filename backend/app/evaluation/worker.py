# SPDX-License-Identifier: Apache-2.0
"""평가 비동기 워커.

``queued`` 평가 Run 을 폴링해 한 건씩 실행한다(인제스천 워커와 동일 패턴).
"""

import asyncio
import logging

from app.core.config import settings
from app.core.database import async_session
from app.evaluation.models import RagEvalRun
from app.evaluation.service import claim_next_run, run_evaluation

logger = logging.getLogger(__name__)


async def evaluation_worker_loop() -> None:
    interval = settings.ingestion_worker_interval
    logger.info("평가 워커 시작 (interval=%.1fs)", interval)
    while True:
        try:
            async with async_session() as session:
                claimed = await claim_next_run(session)
                run_id = claimed.id if claimed else None
            if run_id is None:
                await asyncio.sleep(interval)
                continue
            async with async_session() as session:
                run = await session.get(RagEvalRun, run_id)
                if run is not None:
                    await run_evaluation(session, run)
        except asyncio.CancelledError:
            logger.info("평가 워커 종료")
            raise
        except Exception as e:
            logger.warning("평가 워커 루프 오류: %s", e, exc_info=True)
            await asyncio.sleep(interval)
