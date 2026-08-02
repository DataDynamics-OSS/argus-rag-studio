# SPDX-License-Identifier: Apache-2.0
"""컬렉션(지식베이스) 모듈의 SQLAlchemy ORM 모델.

Collection 은 RAG 의 1차 경계(boundary)다. 임베딩 모델·차원·거리 메트릭을 생성 시점에
고정하며, 같은 컬렉션 안의 모든 청크는 동일한 벡터 공간을 공유한다(M2 인제스천에서 사용).
M1 에서는 컬렉션 메타데이터 CRUD 와 문서 카운트 집계까지만 다룬다.
"""

from sqlalchemy import Column, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class RagCollection(Base):
    """컬렉션(지식베이스) 테이블.

    컬럼:
        - ``id``: auto-increment PK
        - ``collection_id``: 외부 노출용 UUID 식별자 (UNIQUE)
        - ``name``: 표시 이름 (UNIQUE)
        - ``description``: 설명(선택)
        - ``embedding_provider`` / ``embedding_model`` / ``embedding_dim`` / ``embedding_server_url`` /
          ``distance_metric``: 벡터 공간 정의(생성 후 불변, 컬렉션별 상이 가능)
        - ``rerank_provider``: 컬렉션 기본 리랭커(none|llm|cross_encoder, 쿼리 시점 — 파이프라인 우선)
        - ``chunk_strategy`` / ``chunk_size`` / ``chunk_overlap``: 청킹 전략(컬렉션별, 변경 시 재인덱싱)
        - ``status``: ``active`` / ``archived``
        - ``created_by`` / ``updated_by``: 행 단위 소유권(생성자 가드용)
        - ``created_at`` / ``updated_at``
    """

    __tablename__ = "rag_collections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    collection_id = Column(String(36), nullable=False, unique=True)
    name = Column(String(200), nullable=False, unique=True)
    description = Column(Text)
    # 임베딩(벡터 공간) 설정 — 생성 후 불변. server_url 이 NULL 이면 전역 설정 상속.
    embedding_provider = Column(String(30), nullable=False, default="openai_compatible")
    embedding_model = Column(String(200), nullable=False)
    embedding_dim = Column(Integer, nullable=False)
    embedding_server_url = Column(String(500))
    distance_metric = Column(String(20), nullable=False, default="cosine")
    # 리랭커(쿼리 시점) — none | llm | cross_encoder. 파이프라인 지정 시 파이프라인 설정이 우선.
    rerank_provider = Column(String(20), nullable=False, default="none")
    # cross_encoder 리랭커 모델(선택). 비면 리랭커 서버 기본 모델 사용.
    rerank_model = Column(String(200))
    # 파싱 전략 — text | layout | docai | vlm. parse 시점 설정(변경 시 재인덱싱 필요).
    parse_strategy = Column(String(20), nullable=False, default="text")
    # 청킹 전략 — 생성 후 불변(변경 시 재인덱싱 필요).
    chunk_strategy = Column(String(20), nullable=False, default="recursive")
    # 청크 크기/오버랩 단위 — char(기본) | token(tiktoken)
    chunk_unit = Column(String(10), nullable=False, default="char")
    chunk_size = Column(Integer, nullable=False, default=1000)
    chunk_overlap = Column(Integer, nullable=False, default=150)
    # 인제스천 보강 파이프라인 — {post_parse:[{id,config}], post_chunk:[...]}. NULL 이면 기본(DEFAULT_PIPELINE).
    # 변경 시 재인덱싱 필요(parse/chunk 와 동일). 단계 정의는 app/ingestion/transforms 레지스트리.
    ingestion_pipeline = Column(JSONB)
    status = Column(String(20), nullable=False, default="active")
    # 설정 스윕(P2)이 만든 임시 후보 컬렉션 표식 — 스윕 종료 시 자동 정리 대상.
    ephemeral_sweep_id = Column(Integer)
    created_by = Column(String(200))
    updated_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
