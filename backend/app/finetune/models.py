# SPDX-License-Identifier: Apache-2.0
"""파인튜닝 학습 데이터셋의 SQLAlchemy ORM 모델.

- ``FtDataset``: 학습 데이터셋. (질의, 정답, 오답) 예시의 컨테이너 + 매니페스트 메타.
- ``FtExample``: 데이터셋 예시 1건. split(train/valid/test) 으로 구분한다.

스키마 자체는 SQL DDL(packaging/config/argus-rag-studio-postgresql.sql)이 전담한다.
"""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)

from app.core.database import Base


class FtDataset(Base):
    __tablename__ = "ft_datasets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(String(36), nullable=False, unique=True)
    name = Column(String(200), nullable=False, unique=True)
    description = Column(Text)
    # 코퍼스/소스 컬렉션(빌더·하드네거티브 마이닝 기준). 삭제 시 NULL.
    base_collection_id = Column(Integer, ForeignKey("rag_collections.id", ondelete="SET NULL"))
    base_model = Column(String(200))
    task = Column(String(20), nullable=False, default="embedding")          # embedding | reranker
    prompt_format = Column(String(20), nullable=False, default="e5")        # e5 | none
    split_strategy = Column(String(20), nullable=False, default="by_document")
    status = Column(String(20), nullable=False, default="draft")            # draft | ready | exported
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FtExample(Base):
    __tablename__ = "ft_examples"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    example_id = Column(String(36), nullable=False, unique=True)
    dataset_id = Column(
        Integer, ForeignKey("ft_datasets.id", ondelete="CASCADE"), nullable=False
    )
    split = Column(String(10), nullable=False, default="train")             # train | valid | test
    query = Column(Text, nullable=False)
    positive = Column(Text, nullable=False)
    negatives = Column(Text)                                                # JSON: 문자열 배열
    positive_chunk_id = Column(BigInteger)                                  # 출처 청크(provenance)
    source = Column(String(20), nullable=False, default="manual")          # manual|goldenset|feedback|mined
    meta_json = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FtJob(Base):
    """학습 작업 — 외부 트레이너 실행 요청·상태 추적.

    Argus 는 잡을 기록·추적하고, 실제 학습은 외부 프로그램이 수행하며 상태를 콜백으로 갱신한다.
    라이프사이클: queued → running(stage: export|training|importing) → succeeded/failed/canceled.
    """

    __tablename__ = "ft_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), nullable=False, unique=True)
    dataset_id = Column(
        Integer, ForeignKey("ft_datasets.id", ondelete="CASCADE"), nullable=False
    )
    task = Column(String(20), nullable=False, default="embedding")          # embedding | reranker
    base_model = Column(String(200))
    config_json = Column(Text)                                              # 하이퍼파라미터 JSON
    status = Column(String(20), nullable=False, default="queued")           # queued|running|succeeded|failed|canceled
    stage = Column(String(20))                                              # export | training | importing
    progress = Column(Integer, nullable=False, default=0)
    metrics_json = Column(Text)                                             # valid 지표 JSON
    artifact_uri = Column(String(2000))
    error = Column(Text)
    # 잡 전용 콜백 토큰 — 외부 트레이너가 이 잡의 export(GET)·콜백(PATCH)만 인증하는 시크릿(M2M).
    callback_token = Column(String(64))
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))


class FtModel(Base):
    """학습 결과 모델 레지스트리 — 서빙·평가 연결 + 선택적 외부 발행.

    외부 트레이너 산출물(임베딩/리랭커)을 등록해 컬렉션에 연결하고, 홀드아웃 골든셋으로
    base 와 비교 평가한다. published_uri 는 OCI/MLflow 등 외부 배포 대상(선택).
    """

    __tablename__ = "ft_models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_id = Column(String(36), nullable=False, unique=True)
    name = Column(String(200), nullable=False, unique=True)
    task = Column(String(20), nullable=False, default="embedding")          # embedding | reranker
    base_model = Column(String(200))
    embedding_dim = Column(Integer)                                         # 임베딩만(리랭커는 NULL)
    format = Column(String(40))
    prompt_format = Column(String(20), nullable=False, default="e5")
    # 출처(provenance)
    dataset_id = Column(Integer, ForeignKey("ft_datasets.id", ondelete="SET NULL"))
    job_id = Column(Integer, ForeignKey("ft_jobs.id", ondelete="SET NULL"))
    artifact_uri = Column(String(2000))
    metrics_json = Column(Text)
    serving_url = Column(String(500))
    status = Column(String(20), nullable=False, default="registered")       # registered|serving|archived
    published_uri = Column(String(2000))                                    # OCI/MLflow 발행 위치(선택)
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FtGlossaryTerm(Base):
    """도메인 용어 사전 — 전문용어↔정의↔동의어. 합성 질의·하드네거티브 마이닝·쿼리 확장에 활용."""

    __tablename__ = "ft_glossary_terms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    term_id = Column(String(36), nullable=False, unique=True)
    term = Column(String(200), nullable=False)
    definition = Column(Text)
    synonyms = Column(Text)                                                 # JSON: 문자열 배열
    domain = Column(String(100))
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
