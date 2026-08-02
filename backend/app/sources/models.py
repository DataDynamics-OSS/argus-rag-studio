# SPDX-License-Identifier: Apache-2.0
"""스토리지 소스 레지스트리 ORM.

``RagStorageSource`` — 참조 인테이크가 원본을 읽어오는 소스(S3·NAS) 1개. ``name`` 은 라우팅
규칙(path_rule 의 storage 필터)이 참조하는 논리 식별자라 unique 를 강제한다. 자격증명은
``secret_enc``(Fernet 암호화)에만 두고 API 응답에는 노출하지 않는다.
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func

from app.core.database import Base


class RagStorageSource(Base):
    __tablename__ = "rag_storage_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(String(36), nullable=False, unique=True)
    name = Column(String(200), nullable=False, unique=True)  # 라우팅 규칙이 참조하는 논리명
    kind = Column(String(20), nullable=False)                # s3 | nas
    description = Column(Text)
    config_json = Column(Text, nullable=False, default="{}")  # 비밀 아닌 설정(kind 별 스키마)
    secret_enc = Column(Text)                                 # 자격증명(Fernet) — 응답 미노출
    enabled = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
