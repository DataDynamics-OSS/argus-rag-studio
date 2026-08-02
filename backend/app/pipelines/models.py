# SPDX-License-Identifier: Apache-2.0
"""파이프라인(Pipeline) 모듈의 SQLAlchemy ORM 모델.

Pipeline 은 RAG 설정(검색·리랭크·생성 파라미터)을 묶은 **버전 가능한 1급 자산**이다.
설정을 수정할 때마다 불변(immutable) 버전이 append 되고, 파이프라인의 ``active_version``
포인터가 현재 적용 버전을 가리킨다(롤백 = 포인터를 과거 버전으로 이동).
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.core.database import Base


class RagPipeline(Base):
    __tablename__ = "rag_pipelines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pipeline_id = Column(String(36), nullable=False, unique=True)
    name = Column(String(200), nullable=False, unique=True)
    description = Column(Text)
    stage = Column(String(20), nullable=False, default="dev")  # dev | staging | prod (라벨)
    # 현재 적용 중인 버전 번호(rollback 으로 과거 버전 가리킴)
    active_version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RagPipelineVersion(Base):
    __tablename__ = "rag_pipeline_versions"
    __table_args__ = (UniqueConstraint("pipeline_id", "version", name="uq_pipeline_version"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    pipeline_id = Column(
        Integer, ForeignKey("rag_pipelines.id", ondelete="CASCADE"), nullable=False
    )
    version = Column(Integer, nullable=False)
    config_json = Column(Text, nullable=False)  # PipelineConfig JSON
    note = Column(Text)
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
