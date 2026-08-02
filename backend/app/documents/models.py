# SPDX-License-Identifier: Apache-2.0
"""문서(Document) 모듈의 SQLAlchemy ORM 모델.

Document 는 수집된 원본 단위(파일/페이지/레코드)다. 컬렉션에 속하며, 인제스천 파이프라인
(M2: 파싱→청킹→임베딩→인덱싱)의 입력이 된다. M1 에서는 문서 등록·메타데이터·상태(status)
관리까지만 다룬다. ``status`` 라이프사이클: ``registered`` → ``processing`` → ``indexed`` /
``failed``.
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


class RagDocument(Base):
    """문서 테이블.

    컬럼:
        - ``id``: auto-increment PK
        - ``document_id``: 외부 노출용 UUID 식별자 (UNIQUE)
        - ``collection_id``: ``rag_collections.id`` 참조(ON DELETE CASCADE)
        - ``name``: 문서 표시 이름
        - ``source_type``: 출처 유형(upload/s3/web/confluence/...) — M1 은 메타데이터
        - ``source_uri``: 원본 위치(업로드 경로/URL 등)
        - ``content_hash``: 원본 해시(중복/멱등 인제스천 식별자, M2)
        - ``size_bytes``: 원본 크기
        - ``status``: registered/processing/indexed/failed
        - ``chunk_count``: 인제스천 완료 후 생성된 청크 수(M2)
        - ``metadata_json``: 추가 메타데이터(JSON 문자열)
        - ``created_by`` / ``created_at`` / ``updated_at``
    """

    __tablename__ = "rag_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(String(36), nullable=False, unique=True)
    collection_id = Column(
        Integer, ForeignKey("rag_collections.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(500), nullable=False)
    source_type = Column(String(50), nullable=False, default="upload")
    source_uri = Column(String(2000))
    content_hash = Column(String(64))
    size_bytes = Column(BigInteger, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="registered")
    chunk_count = Column(Integer, nullable=False, default=0)
    metadata_json = Column(Text)
    indexed_at = Column(DateTime(timezone=True))
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
