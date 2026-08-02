# SPDX-License-Identifier: Apache-2.0
"""설정 스윕 오케스트레이션 워커.

스윕 상태 기계를 진행시킨다(폴링):
  queued    → plan_sweep: 후보 결정 → (P1) Run 생성·running / (P2) 임시 컬렉션 인덱싱·indexing
  indexing  → start_runs_after_indexing: 후보 인덱싱 끝나면 Run 생성·running
  running   → finalize_if_done: 모든 Run 끝나면 베스트 선정·정리·succeeded

개별 Run 실행은 기존 평가 워커(evaluation_worker_loop)가 담당한다(재사용).
"""

import asyncio
import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session
from app.evaluation import sweep_service as S
from app.evaluation.models import RagEvalSweep

logger = logging.getLogger(__name__)


async def _advance_one(session) -> bool:
    """진행 가능한 스윕 하나를 한 단계 전진시킨다. 처리했으면 True."""
    sweep = (await session.execute(
        select(RagEvalSweep)
        .where(RagEvalSweep.status.in_(("queued", "indexing", "running", "judging")))
        .order_by(RagEvalSweep.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )).scalars().first()
    if not sweep:
        return False

    try:
        if sweep.status == "queued":
            await S.plan_sweep(session, sweep)
        elif sweep.status == "indexing":
            await S.start_runs_after_indexing(session, sweep)
        elif sweep.status in ("running", "judging"):
            # running: 1차 완료 시 judge 게이팅(judging 전이) 또는 종료.
            # judging: 재실행 Run 완료 시 종료.
            await S.finalize_if_done(session, sweep)
    except Exception as e:
        await session.rollback()
        logger.warning("스윕 진행 오류 sweep=%s: %s", sweep.sweep_id, e, exc_info=True)
        fresh = await session.get(RagEvalSweep, sweep.id)
        if fresh:
            fresh.status = "failed"
            fresh.error = str(e)[:2000]
            await session.commit()
    return True


async def sweep_worker_loop() -> None:
    interval = settings.ingestion_worker_interval
    logger.info("스윕 워커 시작 (interval=%.1fs)", interval)
    while True:
        try:
            async with async_session() as session:
                worked = await _advance_one(session)
            # running 스윕은 Run 완료를 기다려야 하므로, 할 일이 없으면 쉰다.
            if not worked:
                await asyncio.sleep(interval)
            else:
                await asyncio.sleep(min(interval, 1.0))
        except asyncio.CancelledError:
            logger.info("스윕 워커 종료")
            raise
        except Exception as e:
            logger.warning("스윕 워커 루프 오류: %s", e, exc_info=True)
            await asyncio.sleep(interval)
