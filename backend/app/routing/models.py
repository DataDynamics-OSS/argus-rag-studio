# SPDX-License-Identifier: Apache-2.0
"""문서 라우팅 모듈의 SQLAlchemy ORM 모델.

``RagRoutingPolicy`` — 라우팅 정책(여러 라우터의 조합)을 묶은 **버전 가능한 1급 자산**.
``RagPipeline`` 과 동형으로, 수정할 때마다 불변 버전이 append 되고 ``active_version`` 이 현재
적용 버전을 가리킨다(롤백 = 포인터 이동). Phase 1 은 단일(singleton) 'default' 정책을 인테이크가 사용.

``RagRoutingDecision`` — 인테이크 시 실제 라우팅 결정 1건의 감사 로그(선택된 컬렉션·신뢰도·
라우터별 trace). 저신뢰(review=true) 결정을 검토 큐로 조회하는 토대(Phase 3 UI).
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.core.database import Base


class RagRoutingPolicy(Base):
    __tablename__ = "rag_routing_policies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    policy_id = Column(String(36), nullable=False, unique=True)
    name = Column(String(200), nullable=False, unique=True)
    description = Column(Text)
    active_version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RagRoutingPolicyVersion(Base):
    __tablename__ = "rag_routing_policy_versions"
    __table_args__ = (
        UniqueConstraint("policy_id", "version", name="uq_routing_policy_version"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    policy_id = Column(
        Integer, ForeignKey("rag_routing_policies.id", ondelete="CASCADE"), nullable=False
    )
    version = Column(Integer, nullable=False)
    config_json = Column(Text, nullable=False)  # RoutingPolicyConfig JSON
    note = Column(Text)
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RagRoutingDecision(Base):
    __tablename__ = "rag_routing_decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    decision_id = Column(String(36), nullable=False, unique=True)
    # 결정 대상 문서(인테이크로 생성된 문서). 문서 삭제 시 함께 정리.
    document_id = Column(
        Integer, ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False
    )
    # 최종 선택된 컬렉션(폴백 포함). 컬렉션 삭제 시 NULL.
    collection_id = Column(
        Integer, ForeignKey("rag_collections.id", ondelete="SET NULL")
    )
    confidence = Column(Float, nullable=False, default=0.0)
    mode = Column(String(20))                 # first_match | weighted_vote
    matched_router = Column(String(60))        # 채택된 라우터 id(없으면 NULL)
    fallback_used = Column(Boolean, nullable=False, default=False)
    review = Column(Boolean, nullable=False, default=False)  # 저신뢰/폴백 → 검토 대상
    policy_version = Column(Integer)           # 결정에 쓰인 정책 버전
    trace_json = Column(Text)                  # 라우터별 후보/점수 trace(JSON)
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # 검토 처리 기록(검토 큐 UI) — 확인/재배정 시 채워진다. corrected 는 재배정 시에만
    # (수동 수정 내역 = 향후 규칙 튜닝 피드백 루프의 원천 데이터).
    reviewed_at = Column(DateTime(timezone=True))
    reviewed_by = Column(String(200))
    corrected_collection_id = Column(
        Integer, ForeignKey("rag_collections.id", ondelete="SET NULL")
    )


class RagRoutingProfile(Base):
    """컬렉션 라우팅 디스크립터(Phase 2) — 내용 임베딩 라우터의 비교 기준.

    컬렉션마다 임베딩 공간(프로바이더/모델/차원)이 달라 컬렉션 자체 벡터는 서로 비교할 수
    없다. 그래서 **전역 임베딩 설정(라우팅 공간)** 으로 각 컬렉션의 대표 텍스트(최근 청크
    샘플, 없으면 설명)를 다시 임베딩해 centroid 를 사이드 테이블에 둔다 — 컬렉션의 불변
    벡터 공간은 건드리지 않는다. 공간이 바뀌면(설정 변경) 기존 행은 stale 로 간주되어
    라우팅에서 제외되고 재계산이 필요하다.
    """

    __tablename__ = "rag_routing_profiles"

    collection_id = Column(
        Integer, ForeignKey("rag_collections.id", ondelete="CASCADE"), primary_key=True
    )
    # 라우팅 공간 벡터(JSON float 배열, L2 정규화 저장) — pgvector 미사용(공간 전환 시
    # 차원이 바뀔 수 있고, 컬렉션 수가 작아 ANN 불필요).
    centroid_json = Column(Text, nullable=False)
    space_provider = Column(String(50), nullable=False)
    space_model = Column(String(200), nullable=False)
    space_dim = Column(Integer, nullable=False)
    source = Column(String(20), nullable=False, default="chunks")  # chunks | description
    sample_count = Column(Integer, nullable=False, default=0)
    built_at = Column(DateTime(timezone=True), server_default=func.now())
