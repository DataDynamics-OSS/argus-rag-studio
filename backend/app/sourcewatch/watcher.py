# SPDX-License-Identifier: Apache-2.0
"""소스 워처 — API 프로세스 내 백그라운드 루프(드롭존 무인화).

설계: design/source-watch.md §2. tick 마다 실행 시점이 된 워치를 SKIP LOCKED 로
클레임해 intake-scan 코어(run_scan)를 실행한다. NAS 마운트가 API 호스트에서만 접근
가능하다는 전제라 워처도 API 안에서 돈다(무거운 파싱은 어차피 잡 큐 → 워커).
`storage_sources.watch_enabled=false` 면 시작하지 않는다 — 외부 스케줄러(NiFi 등)가
intake-scan API 를 대신 호출하는 운영의 탈출구.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import async_session
from app.routing.scan import prune_seen, run_scan
from app.sourcewatch import service
from app.sources import service as sources_service

logger = logging.getLogger(__name__)

SCAN_LIMIT = 500  # intake-scan 과 동일 상한 — truncated 시 즉시 드레인으로 배수

_PRUNE_EVERY_TICKS = 240  # tick 15s 기준 약 1시간마다 seen 프루닝


class SourceWatcher:
    """주기 tick 으로 due 워치를 클레임·실행하는 루프(disconnect_checker 와 동형)."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False
        self._ticks = 0

    async def start(self) -> None:
        if not settings.watch_enabled:
            logger.info("소스 워처 비활성(storage_sources.watch_enabled=false) — 외부 스케줄러 모드")
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="source-watcher")
        logger.info("소스 워처 시작 (tick=%ds)", settings.watch_tick_seconds)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("소스 워처 중지")

    async def _run(self) -> None:
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001 — 루프는 죽지 않는다
                logger.exception("소스 워처 tick 오류")
            try:
                await asyncio.sleep(settings.watch_tick_seconds)
            except asyncio.CancelledError:
                break

    async def tick(self) -> int:
        """due 워치 클레임 → 순차 실행(워치당 동시 1개 보장은 클레임+next_run 선반영이 담당)."""
        async with async_session() as session:
            claimed = await service.claim_due(session, limit=3)
        for w in claimed:
            await self._execute(w)

        self._ticks += 1
        if self._ticks % _PRUNE_EVERY_TICKS == 0:
            try:
                async with async_session() as session:
                    removed = await prune_seen(session, settings.seen_prune_days)
                if removed:
                    logger.info("seen 캐시 프루닝: %d행 (>%d일)", removed, settings.seen_prune_days)
            except Exception:  # noqa: BLE001
                logger.exception("seen 프루닝 실패")
        return len(claimed)

    async def _execute(self, w: dict) -> None:
        """워치 1개 실행 — scan 자체 실패는 워치 실패(백오프), 파일 단위 실패는 counts 로만."""
        started = datetime.now(timezone.utc)
        try:
            async with async_session() as session:
                source = await sources_service.get_source_by_pk(session, w["source_id"])
                if source is None or not source.enabled:
                    raise RuntimeError("소스가 없거나 비활성 상태입니다.")
                report = await run_scan(
                    session, source,
                    prefix=w["prefix"], recursive=w["recursive"], dry_run=False,
                    limit=SCAN_LIMIT, username=f"watch:{w['name']}",
                )
            async with async_session() as session:
                await service.record_result(
                    session, w["id"], started_at=started,
                    scanned=report.scanned, skipped=report.skipped,
                    counts=report.counts, truncated=report.truncated,
                    runs_keep=settings.watch_runs_keep,
                )
            logger.info(
                "워치 실행: %s scanned=%d skipped=%d counts=%s%s",
                w["name"], report.scanned, report.skipped, report.counts,
                " (truncated — 즉시 드레인)" if report.truncated else "",
            )
        except Exception as e:  # noqa: BLE001 — 실행 실패는 백오프로 기록
            logger.warning("워치 실행 실패: %s err=%s", w["name"], e)
            try:
                async with async_session() as session:
                    await service.record_result(
                        session, w["id"], started_at=started, error=str(e),
                        runs_keep=settings.watch_runs_keep,
                    )
            except Exception:  # noqa: BLE001
                logger.exception("워치 실패 기록 실패: %s", w["name"])


source_watcher = SourceWatcher()
