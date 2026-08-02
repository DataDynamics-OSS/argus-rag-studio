# SPDX-License-Identifier: Apache-2.0
"""외부 확장 서버 레지스트리 서비스 — 하트비트 upsert + 목록(생존 판정) + 유령 정리."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.embedding.router import ExtServerStat
from app.extservers.models import RagExtServer
from app.extservers.schemas import ExtServerHeartbeat

# 최근 이 시간 내 하트비트면 alive(레플리카 하트비트 주기의 3배 안팎, 최소 20초).
ALIVE_AFTER_SECONDS = 20.0
# 이 시간 넘게 무소식인 레플리카는 목록에서 제거.
PRUNE_AFTER_SECONDS = 600.0


async def deregister(session: AsyncSession, instance_id: str) -> None:
    """레플리카가 정상 종료 시 자신을 즉시 제거(하트비트 끊김 prune 을 기다리지 않음)."""
    await session.execute(delete(RagExtServer).where(RagExtServer.id == instance_id))
    await session.commit()


async def record_heartbeat(session: AsyncSession, hb: ExtServerHeartbeat) -> None:
    now = datetime.now(timezone.utc)
    mutable = dict(
        kind=hb.kind, hostname=hb.hostname, url=hb.url, version=hb.version,
        stats=hb.stats, last_heartbeat_at=now,
    )
    stmt = pg_insert(RagExtServer).values(id=hb.instance_id, **mutable)
    stmt = stmt.on_conflict_do_update(index_elements=[RagExtServer.id], set_=mutable)
    await session.execute(stmt)
    await session.commit()


async def list_registered(session: AsyncSession) -> list[ExtServerStat]:
    """등록된 레플리카를 '외부 서버' 탭과 동일한 ExtServerStat 형태로 반환(카드 재사용)."""
    now = datetime.now(timezone.utc)
    await session.execute(
        delete(RagExtServer).where(
            RagExtServer.last_heartbeat_at < now - timedelta(seconds=PRUNE_AFTER_SECONDS)
        )
    )
    await session.commit()

    rows = (await session.execute(
        select(RagExtServer).order_by(RagExtServer.kind, RagExtServer.id)
    )).scalars().all()

    out: list[ExtServerStat] = []
    for r in rows:
        hb = r.last_heartbeat_at
        if hb is not None and hb.tzinfo is None:
            hb = hb.replace(tzinfo=timezone.utc)
        age = (now - hb).total_seconds() if hb is not None else None
        alive = age is not None and age <= ALIVE_AFTER_SECONDS
        out.append(ExtServerStat(
            kind=r.kind,
            url=r.url or r.id,
            ok=alive,
            stats=r.stats if alive else None,
            error=None if alive else (f"하트비트 끊김({round(age)}s 전)" if age is not None else "하트비트 없음"),
        ))
    return out
