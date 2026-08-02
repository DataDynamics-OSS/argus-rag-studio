# SPDX-License-Identifier: Apache-2.0
"""독립 워커 프로세스 — API(uvicorn)와 분리해 백그라운드 작업만 실행한다.

대량 인제스천(특히 docai/layout 파싱)은 CPU 바운드라, API 와 같은 프로세스에서 돌면 GIL
경합으로 API 응답이 느려진다. 이 진입점은 인제스천·평가·스윕 워커 루프만 돌려, 파싱/청킹
CPU 부하를 API 호스트와 격리한다. 임베딩은 이미 외부 GPU 서버로 오프로드되므로 여기서
드는 부하는 주로 parse+chunk(백엔드 CPU)다.

큐(``rag_ingestion_jobs``)는 DB 기반이고 ``SKIP LOCKED`` 로 잡을 claim 하므로, 이 프로세스를
**여러 개 동시에 띄워 수평 확장**할 수 있다(중복 처리 없음).

실행::

    ARGUS_RAG_STUDIO_SERVER_CONFIG_DIR=backend/packaging/config \
      python -m app.worker_main

API 인스턴스는 ``ARGUS_INGESTION_LOCAL_WORKER_ENABLED=false`` 로 띄워 로컬(인프로세스) 워커를 끈다.
"""

import asyncio
import logging
import signal

from app.core.config import settings
from app.core.database import async_session, close_database, init_database
from app.core.logging import setup_logging

logger = logging.getLogger("argus.worker")


def _register_models() -> None:
    """ORM 메타데이터 등록 — main.lifespan 과 동일(스키마는 SQL DDL 이 전담)."""
    import app.annotations.models  # noqa: F401
    import app.apikeys.models  # noqa: F401
    import app.chunks.models  # noqa: F401
    import app.collections.models  # noqa: F401
    import app.documents.models  # noqa: F401
    import app.evaluation.models  # noqa: F401
    import app.feedback.models  # noqa: F401
    import app.finetune.models  # noqa: F401
    import app.ingestion.models  # noqa: F401
    import app.observability.models  # noqa: F401
    import app.permissions.models  # noqa: F401
    import app.pipelines.models  # noqa: F401
    import app.settings.models  # noqa: F401
    import app.usermgr.models  # noqa: F401
    import app.workers.models  # noqa: F401


async def _amain() -> None:
    setup_logging()
    logger.info("Argus 워커 프로세스 기동 (config=%s)", settings.config_dir)

    await init_database()
    _register_models()

    # DB 설정 override 를 런타임 settings 에 적용(임베딩 server_url·rerank 등 — API 와 동일 효과)
    from app.settings.service import load_into_runtime
    async with async_session() as session:
        await load_into_runtime(session)

    # 워커는 원본 바이트를 오브젝트 스토리지에서 당겨오므로 버킷 존재를 보장한다.
    try:
        from app.annotations.storage import ensure_bucket as ensure_annotation_bucket
        from app.storage.client import ensure_bucket
        await ensure_bucket()
        await ensure_annotation_bucket()
    except Exception as e:  # noqa: BLE001 — MinIO 미가용 시 경고만(루프는 재시도)
        logger.warning("오브젝트 스토리지 버킷 확인 건너뜀 (MinIO 미가용 가능): %s", e)

    from app.evaluation.sweep_worker import sweep_worker_loop
    from app.evaluation.worker import evaluation_worker_loop
    from app.ingestion.worker import ingestion_worker_loop

    # 종료 신호(SIGTERM/SIGINT) 처리 — 컨테이너 정지/Ctrl-C 시 깔끔히 멈춘다.
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # 일부 플랫폼(예: Windows)
            pass

    tasks = [
        asyncio.create_task(ingestion_worker_loop(), name="ingestion-worker"),
        asyncio.create_task(evaluation_worker_loop(), name="evaluation-worker"),
        asyncio.create_task(sweep_worker_loop(), name="sweep-worker"),
    ]

    # 레지스트리에 등록 + 하트비트 시작(API 가 이 워커를 인지·모니터링할 수 있게)
    from app.workers import runtime as worker_runtime
    await worker_runtime.start("standalone")

    logger.info("워커 루프 %d개 실행 중 (interval=%.1fs) — 종료 신호 대기",
                len(tasks), settings.ingestion_worker_interval)

    await stop.wait()
    logger.info("종료 신호 수신 — 워커 정리 중")

    await worker_runtime.stop()
    for t in tasks:
        t.cancel()
    for t in tasks:
        try:
            await t
        except asyncio.CancelledError:
            pass

    from app.embedding.service import shutdown_provider
    from app.llm.service import shutdown_chat_provider
    await shutdown_provider()
    await shutdown_chat_provider()
    await close_database()
    logger.info("워커 종료 완료")


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
