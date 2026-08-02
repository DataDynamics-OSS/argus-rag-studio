# SPDX-License-Identifier: Apache-2.0
"""데이터베이스 연결 및 세션 관리.

SQLAlchemy 비동기 엔진을 통해 PostgreSQL 과 MariaDB/MySQL 을 지원한다.
스키마 생성·변경은 SQL DDL(``packaging/config/argus-rag-studio-*.sql``)이 전담한다.
"""

import logging
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def _build_database_url() -> str:
    # 원격/분리 워커가 라우팅 가능한 DB 주소로 접속하도록 env 오버라이드를 우선한다.
    override = os.environ.get("ARGUS_DB_URL")
    if override:
        return override
    db_type = settings.db_type.lower()
    host = settings.db_host
    port = settings.db_port
    name = settings.db_name
    user = settings.db_username
    password = settings.db_password

    if db_type == "postgresql":
        return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"
    elif db_type in ("mariadb", "mysql"):
        return f"mysql+aiomysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4"
    else:
        raise ValueError(f"Unsupported database type: {db_type}. Use 'postgresql' or 'mariadb'.")


engine = create_async_engine(
    _build_database_url(),
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_pool_max_overflow,
    pool_recycle=settings.db_pool_recycle,
    echo=settings.db_echo,
)

async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session


async def init_database() -> None:
    db_url = _build_database_url()
    masked = db_url
    if settings.db_password:
        masked = db_url.replace(f":{settings.db_password}@", ":****@")
    logger.info("데이터베이스 연결: %s", masked)

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("데이터베이스 연결 확인 완료")


async def close_database() -> None:
    await engine.dispose()
    logger.info("데이터베이스 연결 풀 종료")
