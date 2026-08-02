# SPDX-License-Identifier: Apache-2.0
"""관측(Observability) 모듈의 SQLAlchemy ORM 모델.

``RagQueryTrace``: 단일 질의(search/query/chat)의 전 과정 기록. 단계별 지연(retrieval/
rerank/generation), 검색 청크 수, 토큰 사용량, 상태/오류를 남겨 추적·분석·비용 집계에 쓴다.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
)

from app.core.database import Base


class RagQueryTrace(Base):
    __tablename__ = "rag_query_traces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(36), nullable=False, unique=True)
    kind = Column(String(10), nullable=False)  # search | query | chat
    collection_id = Column(Integer)
    query = Column(Text)
    mode = Column(String(20))
    distance_metric = Column(String(20))  # 벡터 검색 거리 메트릭(렉시컬이면 미사용)
    rerank = Column(Boolean, nullable=False, default=False)
    status = Column(String(10), nullable=False, default="ok")  # ok | error
    error = Column(Text)
    hit_count = Column(Integer, nullable=False, default=0)
    # 단계별 지연(ms)
    embedding_ms = Column(Float)  # 쿼리 임베딩(검색 세부)
    search_ms = Column(Float)     # 벡터(+렉시컬) 검색·융합(검색 세부)
    retrieval_ms = Column(Float)  # 검색 단계 총합(임베딩+검색)
    rerank_ms = Column(Float)
    generation_ms = Column(Float)
    total_ms = Column(Float)
    # 토큰 사용량(생성 LLM)
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    answer = Column(Text)  # 답변(앞부분 저장)
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
