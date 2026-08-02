# SPDX-License-Identifier: Apache-2.0
"""평가(Evaluation) 모듈의 SQLAlchemy ORM 모델.

- ``RagEvalDataset``: 골든 데이터셋. (질문, 기대답변, 기대출처) 항목의 컨테이너.
- ``RagEvalItem``: 데이터셋 항목 1건.
- ``RagEvalRun``: 데이터셋을 특정 컬렉션의 RAG 파이프라인에 대해 1회 평가한 단위.
  검색 지표(hit_rate/mrr)와 생성 지표(faithfulness/answer_relevance/correctness)의 집계를 보유.
- ``RagEvalResult``: Run 안의 항목별 결과(답변, 검색 적중, 항목별 지표).
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
    func,
)

from app.core.database import Base


class RagEvalDataset(Base):
    __tablename__ = "rag_eval_datasets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(String(36), nullable=False, unique=True)
    name = Column(String(200), nullable=False, unique=True)
    description = Column(Text)
    # 기본 평가 대상 컬렉션(Run 생성 시 재정의 가능). 컬렉션 삭제 시 NULL.
    collection_id = Column(Integer, ForeignKey("rag_collections.id", ondelete="SET NULL"))
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RagEvalItem(Base):
    __tablename__ = "rag_eval_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(36), nullable=False, unique=True)
    dataset_id = Column(
        Integer, ForeignKey("rag_eval_datasets.id", ondelete="CASCADE"), nullable=False
    )
    question = Column(Text, nullable=False)
    expected_answer = Column(Text)
    # 기대 출처 — 문서명 부분문자열의 줄바꿈 구분 목록. 검색 적중(hit) 판정에 사용.
    expected_sources = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RagEvalSweep(Base):
    """설정 스윕 — 한 데이터셋에 대해 여러 설정 조합(Run)을 만들어 베스트를 찾는 단위.

    search_space(JSON): {"index_axis": {...}, "query_axis": {...}} 형태의 탐색 공간.
    상태: queued → (indexing: P2 임시 컬렉션 인덱싱) → running(Run 실행) → succeeded/failed/canceled.
    """

    __tablename__ = "rag_eval_sweeps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sweep_id = Column(String(36), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    dataset_id = Column(
        Integer, ForeignKey("rag_eval_datasets.id", ondelete="CASCADE"), nullable=False
    )
    base_collection_id = Column(Integer, nullable=False)  # 인덱스 후보 생성/평가 기준 컬렉션
    search_space = Column(Text, nullable=False)           # JSON 탐색 공간
    primary_metric = Column(String(30), nullable=False, default="hit_rate")
    judge = Column(Boolean, nullable=False, default=False)
    # judge 게이팅(P3): 검색 점수 상위 N개 조합만 judge 를 재실행. NULL 이면 게이팅 없음(전체 judge).
    judge_top_n = Column(Integer)
    # 홀드아웃 비율(P3): 0~0.9. >0 이면 train 으로 베스트 선정·holdout 으로 일반화 검증(과적합 플래그).
    holdout_ratio = Column(Float, nullable=False, default=0.0)
    max_runs = Column(Integer, nullable=False, default=64)
    status = Column(String(20), nullable=False, default="queued")
    total_runs = Column(Integer, nullable=False, default=0)
    completed_runs = Column(Integer, nullable=False, default=0)
    candidate_collections = Column(Text)  # JSON: [{collection_id, index_config, ephemeral}]
    best_run_id = Column(Integer)         # 우승 Run(rag_eval_runs.id)
    error = Column(Text)
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))


class RagEvalRun(Base):
    __tablename__ = "rag_eval_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), nullable=False, unique=True)
    dataset_id = Column(
        Integer, ForeignKey("rag_eval_datasets.id", ondelete="CASCADE"), nullable=False
    )
    collection_id = Column(Integer, nullable=False)
    # 설정 스윕 소속(선택). 스윕 Run 은 sweep_id 로 묶이고 config_json 에 전체 설정을 스냅샷한다.
    sweep_id = Column(
        Integer, ForeignKey("rag_eval_sweeps.id", ondelete="CASCADE")
    )
    config_json = Column(Text)  # 이 Run 의 전체 설정(인덱스+쿼리) JSON 스냅샷(리더보드·재현용)
    pipeline_id = Column(Integer)  # 적용한 파이프라인(활성 버전 설정으로 검색·리랭크 실행). NULL=직접 설정
    status = Column(String(20), nullable=False, default="queued")  # queued/running/succeeded/failed
    mode = Column(String(20), nullable=False, default="hybrid")
    distance_metric = Column(String(20))  # 평가 대상 컬렉션의 벡터 거리 메트릭
    rerank = Column(Boolean, nullable=False, default=False)
    judge = Column(Boolean, nullable=False, default=False)  # LLM-as-judge 생성 지표 사용 여부
    top_k = Column(Integer, nullable=False, default=5)
    total_items = Column(Integer, nullable=False, default=0)
    completed_items = Column(Integer, nullable=False, default=0)
    # 집계 지표 (nullable — 해당 지표 산출 불가 시 NULL)
    hit_rate = Column(Float)
    mrr = Column(Float)
    faithfulness = Column(Float)
    answer_relevance = Column(Float)
    correctness = Column(Float)
    error = Column(Text)
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))


class RagEvalResult(Base):
    __tablename__ = "rag_eval_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(
        Integer, ForeignKey("rag_eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    item_id = Column(Integer, nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text)
    retrieved_docs = Column(Text)  # JSON: 검색된 문서명 목록
    hit = Column(Boolean)
    reciprocal_rank = Column(Float)
    faithfulness = Column(Float)
    answer_relevance = Column(Float)
    correctness = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
