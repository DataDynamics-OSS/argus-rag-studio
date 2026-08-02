# SPDX-License-Identifier: Apache-2.0
"""이미지 추출 및 분석 모듈의 SQLAlchemy ORM 모델.

- ``RagImageRecognitionRun``: 업로드 1건(파일 1개) = 분류 실행 1건의 이력.

추출 이미지(원본·썸네일)와 이미지별 분석 결과는 분류 버킷
(``settings.os_classification_bucket``)의 ``runs/{run_id}/`` 아래에 저장하고,
이 테이블에는 메타(파일명·상태·개수·시각·버킷 위치)만 보관한다.
``batch_id`` 는 같이(동시에) 업로드한 파일 묶음을 식별한다.

스키마 생성·변경은 SQL DDL(``packaging/config/argus-rag-studio-*.sql``)이 전담한다.
"""

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class RagImageRecognitionRun(Base):
    """이미지 추출 및 분석 실행 이력 테이블."""

    __tablename__ = "rag_image_recognition_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), nullable=False, unique=True)
    batch_id = Column(String(36))
    filename = Column(String(500), nullable=False)
    source_kind = Column(String(50))
    status = Column(String(20), nullable=False, default="running")  # running|succeeded|failed
    extracted_count = Column(Integer, nullable=False, default=0)
    analyzed_count = Column(Integer, nullable=False, default=0)
    counts_by_type = Column(JSONB)
    size_bytes = Column(BigInteger, nullable=False, default=0)  # 실행 폴더(prefix) 전체 저장 크기(byte)
    source_url = Column(String(2000))  # URL 가져오기면 원본 페이지 URL(파일명은 HTML 타이틀)
    bucket = Column(String(255))
    prefix = Column(String(1000))
    error = Column(Text)
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))
