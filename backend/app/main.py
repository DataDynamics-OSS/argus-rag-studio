# SPDX-License-Identifier: Apache-2.0
"""Argus RAG Studio 서버 - FastAPI 애플리케이션 진입점."""

import argparse
import asyncio
import logging
import sys
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app import __version__
from app.agent.disconnect_checker import disconnect_checker
from app.agent.router import router as agent_router
from app.annotations.router import router as annotations_router
from app.apikeys.router import router as apikeys_router
from app.auth.router import router as auth_router
from app.collections.router import router as collections_router
from app.core.config import settings
from app.core.database import close_database, init_database
from app.core.logging import setup_logging
from app.core.password_gate import PasswordChangeGateMiddleware
from app.core.security import SecurityHeadersMiddleware
from app.deploy.router import router as deploy_router
from app.documents.router import router as documents_router
from app.embedding.router import router as embedding_router
from app.evaluation.router import router as evaluation_router
from app.extservers.router import router as extservers_router
from app.feedback.router import router as feedback_router
from app.finetune.router import router as finetune_router
from app.generation.router import router as generation_router
from app.imagerecog.router import router as imagerecog_router
from app.ingestion.router import router as ingestion_router
from app.modelreg.router import router as modelreg_router
from app.observability.router import router as observability_router
from app.permissions.router import router as permissions_router
from app.pii.router import router as pii_router
from app.pipelines.router import router as pipelines_router
from app.routing.router import router as routing_router
from app.s3browse.router import router as s3browse_router
from app.servermgr.router import router as servermgr_router
from app.settings.router import router as settings_router
from app.sourcewatch.router import router as sourcewatch_router
from app.sources.router import router as sources_router
from app.usermgr.router import router as usermgr_router
from app.workers.router import router as workers_router

logger = logging.getLogger(__name__)
_start_time: float = 0.0

BANNER = r"""
   _                          ___  ___   ___   ___ _           _ _
  /_\  _ _ __ _ _  _ ___     | _ \/_\ / __| / __| |_ _  _ __| (_)___
 / _ \| '_/ _` | || (_-<     |   / _ \ (_ | \__ \  _| || / _` | / _ \
/_/ \_\_| \__, |\_,_/__/     |_|_\_/ \_\___| |___/\__|\_,_\__,_|_\___/
          |___/
"""


def _print_banner() -> None:
    logger.info(BANNER)
    logger.info("버전              : %s", settings.app_version)
    logger.info("설정 YAML         : %s", settings.config_yaml_path)
    logger.info("설정 Properties   : %s", settings.config_properties_path)
    logger.info("인증 모드         : %s", settings.auth_type)
    logger.info("데이터 디렉터리   : %s", settings.data_dir)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _start_time
    _start_time = time.monotonic()
    setup_logging()
    _print_banner()
    logger.info("RAG Studio 서버 %s 기동 중", __version__)
    await init_database()

    # ORM 메타데이터 등록 (스키마 자체는 SQL DDL 이 전담)
    import app.agent.models  # noqa: F401
    import app.annotations.models  # noqa: F401
    import app.apikeys.models  # noqa: F401
    import app.chunks.models  # noqa: F401
    import app.collections.models  # noqa: F401
    import app.deploy.cluster_models  # noqa: F401
    import app.documents.models  # noqa: F401
    import app.evaluation.models  # noqa: F401
    import app.extservers.models  # noqa: F401
    import app.feedback.models  # noqa: F401
    import app.finetune.models  # noqa: F401
    import app.ingestion.models  # noqa: F401
    import app.modelreg.models  # noqa: F401
    import app.sourcewatch.models  # noqa: F401
    import app.observability.models  # noqa: F401
    import app.permissions.models  # noqa: F401
    import app.pipelines.models  # noqa: F401
    import app.routing.models  # noqa: F401
    import app.settings.models  # noqa: F401
    import app.usermgr.models  # noqa: F401
    import app.workers.models  # noqa: F401

    logger.info("스키마는 SQL DDL 로 관리됨 (packaging/config/argus-rag-studio-*.sql)")

    # 기본 데이터 시드 + 설정 override 런타임 적용
    from app.core.database import async_session
    from app.permissions.router import seed_default_permissions
    from app.settings.service import load_into_runtime
    from app.usermgr.service import seed_admin_user, seed_roles

    async with async_session() as session:
        await seed_roles(session)
        await seed_admin_user(session)
        await seed_default_permissions(session)
        from app.modelreg.service import ensure_seeds as seed_model_registry
        await seed_model_registry(session)
        await load_into_runtime(session)

    # 오브젝트 스토리지 버킷 보장 — 백그라운드로 처리해 기동(로그인 가용)을 막지 않는다.
    # (MinIO 미가용 시에도 서버는 즉시 요청을 받고, 버킷 확인은 비동기로 재시도/경고)
    async def _ensure_bucket_bg():
        try:
            from app.annotations.storage import ensure_bucket as ensure_annotation_bucket
            from app.storage.client import ensure_bucket, ensure_models_bucket
            await ensure_bucket()
            await ensure_annotation_bucket()
            await ensure_models_bucket()  # 모델 저장소(Model Repository) — 보유 확인·서버 팩
        except Exception as e:
            logger.warning("오브젝트 스토리지 버킷 확인 건너뜀 (MinIO 미가용 가능): %s", e)

    asyncio.create_task(_ensure_bucket_bg())

    # 인제스천 + 평가 비동기 워커 기동
    worker_tasks = []
    if settings.ingestion_local_worker_enabled:
        from app.evaluation.sweep_worker import sweep_worker_loop
        from app.evaluation.worker import evaluation_worker_loop
        from app.ingestion.worker import ingestion_worker_loop
        worker_tasks.append(asyncio.create_task(ingestion_worker_loop()))
        worker_tasks.append(asyncio.create_task(evaluation_worker_loop()))
        worker_tasks.append(asyncio.create_task(sweep_worker_loop()))
        # 이 프로세스(API 동거 워커)를 레지스트리에 등록 + 하트비트 시작
        from app.workers import runtime as worker_runtime
        await worker_runtime.start("in_process")
    else:
        logger.info("로컬 워커 비활성화됨 (ingestion.local_worker_enabled=false) — 색인은 원격/분리 워커(app.worker_main)가 처리")

    # 에이전트 하트비트 끊김 감시 — 타임아웃 초과 시 argus_agents.status=DISCONNECTED
    await disconnect_checker.start()

    # 소스 워처(드롭존 무인화) — watch_enabled=false 면 내부에서 스킵(외부 스케줄러 모드).
    from app.sourcewatch.watcher import source_watcher
    await source_watcher.start()

    yield

    await source_watcher.stop()
    await disconnect_checker.stop()
    if settings.ingestion_local_worker_enabled:
        from app.workers import runtime as worker_runtime
        await worker_runtime.stop()
    for task in worker_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    from app.embedding.service import shutdown_provider
    from app.llm.service import shutdown_chat_provider
    await shutdown_provider()
    await shutdown_chat_provider()
    await close_database()
    logger.info("RAG Studio 서버 종료 중")


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)
# 강제 비밀번호 변경 게이트(로컬 모드) — 화이트리스트 외 API 차단
app.add_middleware(PasswordChangeGateMiddleware)


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    """DB 무결성 위반(FK 제약 등)을 500 대신 409 로 변환하는 안전망."""
    logger.warning("무결성 제약 위반 (%s %s): %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=409,
        content={"detail": "다른 항목과 연결되어 있어 처리할 수 없습니다. 연결된 하위 항목을 먼저 정리하세요."},
    )


class DynamicCORSMiddleware:
    """요청 시점에 settings 에서 허용 origin 을 읽는 CORS 미들웨어."""

    def __init__(self, app):
        self.app = app
        self._inner = None
        self._origins_snapshot = None

    def _get_inner(self):
        current = tuple(settings.cors_origins)
        if current != self._origins_snapshot:
            self._inner = CORSMiddleware(
                app=self.app,
                allow_origins=list(current),
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )
            self._origins_snapshot = current
        return self._inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        await self._get_inner()(scope, receive, send)


app.add_middleware(DynamicCORSMiddleware)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(apikeys_router, prefix="/api/v1")
app.include_router(usermgr_router, prefix="/api/v1")
app.include_router(collections_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(ingestion_router, prefix="/api/v1")
app.include_router(embedding_router, prefix="/api/v1")
app.include_router(generation_router, prefix="/api/v1")
app.include_router(evaluation_router, prefix="/api/v1")
app.include_router(observability_router, prefix="/api/v1")
app.include_router(pipelines_router, prefix="/api/v1")
app.include_router(routing_router, prefix="/api/v1")
app.include_router(sources_router, prefix="/api/v1")
app.include_router(sourcewatch_router, prefix="/api/v1")
app.include_router(modelreg_router, prefix="/api/v1")
app.include_router(feedback_router, prefix="/api/v1")
app.include_router(finetune_router, prefix="/api/v1")
app.include_router(permissions_router, prefix="/api/v1")
app.include_router(pii_router, prefix="/api/v1")
app.include_router(settings_router, prefix="/api/v1")
app.include_router(s3browse_router, prefix="/api/v1")
app.include_router(annotations_router, prefix="/api/v1")
app.include_router(imagerecog_router, prefix="/api/v1")
app.include_router(workers_router, prefix="/api/v1")
app.include_router(extservers_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(servermgr_router, prefix="/api/v1")
app.include_router(deploy_router, prefix="/api/v1")


@app.get("/health")
async def health():
    """헬스 체크 엔드포인트."""
    uptime_seconds = int(time.monotonic() - _start_time)
    return {
        "status": "ok",
        "service": "argus-rag-studio-server",
        "uptime": uptime_seconds,
        "version": __version__,
    }


def run() -> None:
    parser = argparse.ArgumentParser(
        prog="argus-rag-studio-server",
        description="RAG Studio Server - Retrieval-Augmented Generation platform for Argus.",
    )
    parser.add_argument("--config-yaml", metavar="PATH", help="Path to YAML config file")
    parser.add_argument("--config-properties", metavar="PATH", help="Path to properties file")
    args = parser.parse_args()

    if args.config_yaml or args.config_properties:
        from app.core.config import init_settings
        init_settings(yaml_path=args.config_yaml, properties_path=args.config_properties)
    else:
        yaml_exists = settings.config_yaml_path.is_file()
        props_exists = settings.config_properties_path.is_file()
        if not yaml_exists and not props_exists:
            parser.print_help()
            print()
            print(
                f"Error: No configuration files found at default location:\n"
                f"  - {settings.config_yaml_path}\n"
                f"  - {settings.config_properties_path}\n"
            )
            sys.exit(1)

    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    run()
