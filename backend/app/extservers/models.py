# SPDX-License-Identifier: Apache-2.0
"""외부 확장 서버 레플리카 레지스트리 ORM."""

from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class RagExtServer(Base):
    """확장 서버 레플리카 1개(=프로세스 1개). ``id`` 는 인스턴스 기동 시 생성한 uuid."""

    __tablename__ = "argus_ext_servers"

    id = Column(String(64), primary_key=True)       # 인스턴스 uuid
    kind = Column(String(20), nullable=False)       # embedding | reranker | detection
    hostname = Column(String(255))
    url = Column(String(500))                        # 이 레플리카의 직접 주소(표시용)
    version = Column(String(40))
    stats = Column(JSONB)                            # /stats 스냅샷(시스템·GPU·요청·모델)
    last_heartbeat_at = Column(DateTime(timezone=True), server_default=func.now())
