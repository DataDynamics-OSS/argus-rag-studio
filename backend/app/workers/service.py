# SPDX-License-Identifier: Apache-2.0
"""워커 레지스트리 서비스 — 목록 조회(생존 판정) + 유령 행 정리."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.workers.models import RagWorker
from app.workers.runtime import HEARTBEAT_INTERVAL
from app.workers.schemas import WorkerInfo

# 최근 이 시간 내 하트비트면 alive 로 본다(하트비트 주기의 3배, 최소 15초).
ALIVE_AFTER_SECONDS = max(15.0, HEARTBEAT_INTERVAL * 3)
# 이 시간 넘게 무소식인 행은 목록에서 제거(비정상 종료한 유령 워커 정리).
PRUNE_AFTER_SECONDS = 600.0


async def list_workers(session: AsyncSession) -> list[WorkerInfo]:
    now = datetime.now(timezone.utc)

    # 정리: 정상 종료(stopped)는 즉시 제거(예: dev --reload 재시작 잔재),
    #       크래시(스톱 못 부르고 하트비트만 끊김)는 PRUNE 경과 후 제거(그 전까진 alive=false 로 노출).
    await session.execute(
        delete(RagWorker).where(
            or_(
                RagWorker.status == "stopped",
                RagWorker.last_heartbeat_at < now - timedelta(seconds=PRUNE_AFTER_SECONDS),
            )
        )
    )
    await session.commit()

    rows = (await session.execute(
        select(RagWorker).order_by(RagWorker.started_at)
    )).scalars().all()

    out: list[WorkerInfo] = []
    for w in rows:
        hb = w.last_heartbeat_at
        if hb is not None and hb.tzinfo is None:
            hb = hb.replace(tzinfo=timezone.utc)
        age = (now - hb).total_seconds() if hb is not None else None
        alive = (
            w.status != "stopped"
            and age is not None
            and age <= ALIVE_AFTER_SECONDS
        )
        out.append(WorkerInfo(
            id=w.id, hostname=w.hostname, pid=w.pid, mode=w.mode, runtime=w.runtime,
            version=w.version,
            status=w.status, current_job_id=w.current_job_id,
            processed_total=w.processed_total, started_at=w.started_at,
            last_heartbeat_at=w.last_heartbeat_at,
            heartbeat_age_seconds=round(age, 1) if age is not None else None,
            alive=alive, metrics=w.metrics,
        ))
    return out
