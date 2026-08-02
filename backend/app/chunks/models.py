# SPDX-License-Identifier: Apache-2.0
"""청크(Chunk) ORM 모델.

청크는 문서를 검색 단위로 분할한 결과다. 임베딩 벡터(pgvector)와 렉시컬 인덱스(tsvector)를
함께 보유해, M3 에서 벡터 검색·BM25·하이브리드 검색의 대상이 된다.

차원 메모: ``embedding`` 컬럼은 DDL 에서 ``vector(1024)`` 로 고정되어 있다(bge-m3 기준).
컬렉션의 ``embedding_dim`` 과 일치해야 하며, 다차원 모델 혼용이 필요해지면 컬렉션별
파티션/테이블로 분리한다(architecture.md 참고).
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import TSVECTOR

from app.core.config import settings
from app.core.database import Base

# DDL 의 vector(1024) 와 일치. 설정 기본값을 단일 소스로 사용한다.
_EMBED_DIM = settings.embedding_default_dim


class RagChunk(Base):
    """청크 테이블 — 텍스트 + 임베딩 벡터 + tsvector."""

    __tablename__ = "rag_chunks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    chunk_id = Column(String(36), nullable=False, unique=True)
    document_id = Column(
        Integer, ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False
    )
    collection_id = Column(
        Integer, ForeignKey("rag_collections.id", ondelete="CASCADE"), nullable=False
    )
    seq = Column(Integer, nullable=False, default=0)
    text = Column(Text, nullable=False)
    embedding = Column(Vector(_EMBED_DIM))
    # 렉시컬(BM25/FTS) 검색용 tsvector. 인제스천 워커가 to_tsvector('simple', text) 로 채운다.
    tsv = Column(TSVECTOR)
    parent_chunk_id = Column(BigInteger, ForeignKey("rag_chunks.id", ondelete="SET NULL"))
    section_path = Column(String(1000))
    metadata_json = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
