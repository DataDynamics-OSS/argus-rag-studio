# SPDX-License-Identifier: Apache-2.0
"""소스 워치 서비스 — CRUD·클레임(SKIP LOCKED)·실행 기록·백오프.

설계: design/source-watch.md §2·§3. 클레임 시점에 next_run_at 을 먼저 밀어두므로
실행 중 프로세스가 죽어도 다음 주기에 자연 재시도된다(scan 이 멱등이라 안전).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.sourcewatch.models import RagSourceWatch, RagSourceWatchRun

logger = logging.getLogger(__name__)

BACKOFF_CAP_SECONDS = 3600


def backoff_seconds(interval_seconds: int, consecutive_failures: int) -> int:
    """scan 실패 시 재시도 지연 — interval × 2^failures (상한 1시간). 자동 비활성화는 안 한다."""
    if consecutive_failures <= 0:
        return interval_seconds
    return min(interval_seconds * (2 ** consecutive_failures), BACKOFF_CAP_SECONDS)


# ── CRUD ─────────────────────────────────────────────────────────────────────

async def list_watches(session: AsyncSession) -> list[RagSourceWatch]:
    return list((await session.execute(
        select(RagSourceWatch).order_by(RagSourceWatch.created_at)
    )).scalars())


async def get_watch(session: AsyncSession, watch_id: str) -> RagSourceWatch | None:
    return (await session.execute(
        select(RagSourceWatch).where(RagSourceWatch.watch_id == watch_id)
    )).scalar_one_or_none()


async def watches_for_source(session: AsyncSession, source_pk: int) -> list[RagSourceWatch]:
    return list((await session.execute(
        select(RagSourceWatch).where(RagSourceWatch.source_id == source_pk)
    )).scalars())


async def create_watch(session: AsyncSession, data: dict, username: str) -> RagSourceWatch:
    w = RagSourceWatch(
        watch_id=str(uuid.uuid4()), source_id=data["source_id"],
        name=data["name"], prefix=data.get("prefix") or "",
        recursive=bool(data.get("recursive", True)),
        interval_seconds=int(data["interval_seconds"]),
        enabled=bool(data.get("enabled", True)),
        next_run_at=datetime.now(timezone.utc),  # 등록 즉시 첫 실행
        created_by=username,
    )
    session.add(w)
    await session.commit()
    await session.refresh(w)
    return w


async def update_watch(session: AsyncSession, w: RagSourceWatch, data: dict) -> RagSourceWatch:
    for field in ("name", "prefix", "recursive", "interval_seconds", "enabled"):
        if data.get(field) is not None:
            setattr(w, field, data[field])
    await session.commit()
    await session.refresh(w)
    return w


async def delete_watch(session: AsyncSession, w: RagSourceWatch) -> None:
    await session.delete(w)
    await session.commit()


async def run_now(session: AsyncSession, w: RagSourceWatch) -> None:
    """다음 tick 에 즉시 집히도록 next_run_at 을 당긴다(루프가 실행 주체)."""
    w.next_run_at = datetime.now(timezone.utc)
    await session.commit()


# ── 클레임(다중 레플리카 안전) ─────────────────────────────────────────────────

async def claim_due(session: AsyncSession, limit: int = 3) -> list[dict]:
    """실행 시점이 된 워치를 SKIP LOCKED 로 클레임하고 next_run_at 을 먼저 민다.

    반환은 detach 안전한 dict 스냅샷 — 실행은 호출자(워처 루프)가 새 세션으로 한다.
    """
    now = datetime.now(timezone.utc)
    rows = list((await session.execute(
        select(RagSourceWatch)
        .where(RagSourceWatch.enabled.is_(True), RagSourceWatch.next_run_at <= now)
        .order_by(RagSourceWatch.next_run_at)
        .with_for_update(skip_locked=True)
        .limit(limit)
    )).scalars())
    claimed: list[dict] = []
    for w in rows:
        # 기본 스케줄로 먼저 밀어 커밋 — 레플리카 중복 방지 + 크래시 안전(다음 주기 재시도).
        w.next_run_at = now + timedelta(seconds=w.interval_seconds)
        claimed.append({
            "id": w.id, "watch_id": w.watch_id, "source_id": w.source_id,
            "name": w.name, "prefix": w.prefix, "recursive": w.recursive,
            "interval_seconds": w.interval_seconds,
            "consecutive_failures": w.consecutive_failures,
        })
    if rows:
        await session.commit()
    return claimed


# ── 실행 결과 기록 ────────────────────────────────────────────────────────────

async def record_result(
    session: AsyncSession,
    watch_pk: int,
    *,
    started_at: datetime,
    scanned: int = 0,
    skipped: int = 0,
    counts: dict | None = None,
    truncated: bool = False,
    error: str | None = None,
    runs_keep: int = 100,
) -> None:
    """run 이력 삽입(+초과분 삭제) + 워치 상태/백오프 갱신. truncated 는 즉시 드레인."""
    now = datetime.now(timezone.utc)
    w = (await session.execute(
        select(RagSourceWatch).where(RagSourceWatch.id == watch_pk)
    )).scalar_one_or_none()
    if w is None:  # 실행 중 삭제됨 — 기록할 곳 없음
        return

    session.add(RagSourceWatchRun(
        watch_id=watch_pk, started_at=started_at, finished_at=now,
        scanned=scanned, skipped=skipped,
        counts_json=json.dumps(counts or {}, ensure_ascii=False),
        truncated=truncated, error=error,
    ))

    w.last_run_at = now
    if error:
        w.consecutive_failures = (w.consecutive_failures or 0) + 1
        w.last_status = "error"
        w.last_error = error[:2000]
        # 백오프 — 조용히 꺼지는 게 최악이므로 자동 비활성화 없이 지연만 늘린다.
        w.next_run_at = now + timedelta(
            seconds=backoff_seconds(w.interval_seconds, w.consecutive_failures)
        )
    else:
        w.consecutive_failures = 0
        w.last_status = "ok"
        w.last_error = None
        w.last_counts_json = json.dumps(
            {**(counts or {}), "skipped": skipped}, ensure_ascii=False
        )
        if truncated:
            # 대량 적재 배수(drain) — 주기 대기 없이 즉시 이어서 실행.
            w.next_run_at = now

    # 이력 보존 상한 — 워치당 최근 N개만(집계 요약이므로 가볍게 유지).
    keep_ids = select(RagSourceWatchRun.id).where(
        RagSourceWatchRun.watch_id == watch_pk
    ).order_by(RagSourceWatchRun.started_at.desc()).limit(runs_keep)
    await session.execute(
        delete(RagSourceWatchRun).where(
            RagSourceWatchRun.watch_id == watch_pk,
            RagSourceWatchRun.id.not_in(keep_ids),
        )
    )
    await session.commit()


async def list_runs(session: AsyncSession, watch_pk: int, limit: int = 100) -> list[RagSourceWatchRun]:
    return list((await session.execute(
        select(RagSourceWatchRun).where(RagSourceWatchRun.watch_id == watch_pk)
        .order_by(RagSourceWatchRun.started_at.desc()).limit(limit)
    )).scalars())
