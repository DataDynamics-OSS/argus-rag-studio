# SPDX-License-Identifier: Apache-2.0
"""인제스천 잡(Ingestion Job) ORM 모델.

문서 1건의 처리(파싱→청킹→임베딩→인덱싱)를 추적하는 단위. 업로드/등록 시 ``queued`` 로
생성되고, 비동기 워커가 집어 ``running`` → ``succeeded``/``failed`` 로 진행한다. ``stage`` 는
사용자에게 보여줄 현재 단계, ``progress`` 는 0~100 진행률, ``error`` 는 실패 사유다.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.core.database import Base


class RagIngestionJob(Base):
    """인제스천 잡 테이블."""

    __tablename__ = "rag_ingestion_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), nullable=False, unique=True)
    document_id = Column(
        Integer, ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False
    )
    collection_id = Column(Integer, nullable=False)
    # queued / running / succeeded / failed
    status = Column(String(20), nullable=False, default="queued")
    # parse / chunk / embed / index (현재 단계)
    stage = Column(String(20))
    progress = Column(Integer, nullable=False, default=0)
    chunk_count = Column(Integer, nullable=False, default=0)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
