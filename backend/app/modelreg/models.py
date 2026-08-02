# SPDX-License-Identifier: Apache-2.0
"""모델 레지스트리 ORM — "우리 시스템이 사용할 모델"의 선언(에어갭 반출 승인 목록).

설계: design/model-registry.md. ``(kind, name)`` 이 Model Repository(argus-models 버킷)의
키 규약 ``{kind}/{name}/{revision}/`` 과 결합되므로 unique 를 강제한다. ``repo`` 가 HF 와의
연결 고리 — 팩 명령·온라인 폴백·hf-cache 디렉터리명이 모두 이 값에서 나온다.
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint, func

from app.core.database import Base


class RagModelRegistry(Base):
    __tablename__ = "rag_model_registry"
    __table_args__ = (UniqueConstraint("kind", "name", name="uq_model_registry_kind_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_id = Column(String(36), nullable=False, unique=True)
    kind = Column(String(20), nullable=False)     # embedding | reranker | vlm | detection
    name = Column(String(200), nullable=False)    # 논리명 — Repo 키·served-model-name
    repo = Column(String(300), nullable=False)    # HF repo id (org/name)
    revision = Column(String(100), nullable=False, default="main")
    source = Column(String(20), nullable=False, default="hf")        # hf | paddle(수동)
    target = Column(String(20), nullable=False, default="hf-cache")  # hf-cache | flat
    params_json = Column(Text, nullable=False, default="{}")  # kind 별 부가(max_len, approx_gb…)
    note = Column(Text)
    enabled = Column(Boolean, nullable=False, default=True)   # 비활성화 = 배포 선택에서 제외
    builtin = Column(Boolean, nullable=False, default=False)  # 시드 여부(삭제 대신 비활성화)
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
