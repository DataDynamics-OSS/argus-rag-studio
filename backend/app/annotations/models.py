# SPDX-License-Identifier: Apache-2.0
"""어노테이션(Annotation) 모듈의 SQLAlchemy ORM 모델.

- ``AnnotationImage``: 업로드된 이미지 1장 = 어노테이션 작업 1건.
- ``AnnotationBox``: 이미지 안의 글자/단어 단위 bbox 1개.

내부 좌표는 ``(x1, y1, x2, y2)`` 축정렬(axis-aligned) 사각형으로 보관한다.
AI-Hub 규격(``x=[x1,x1,x2,x2]``, ``y=[y1,y2,y1,y2]``)으로의 변환은
``app.annotations.aihub`` 가 입출력 경계에서만 수행한다.

``status`` 라이프사이클: ``draft`` → ``in_progress`` → ``completed``.
"""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class AnnotationImage(Base):
    """어노테이션 대상 이미지 테이블.

    컬럼:
        - ``id``: auto-increment PK
        - ``image_id``: 외부 노출용 UUID 식별자 (UNIQUE) — 모든 API 가 이 값으로 주소지정
        - ``collection_id``: 선택적 컬렉션 연결(``rag_collections.id``, ON DELETE SET NULL)
        - ``filename`` / ``source_uri``: 원본 파일명 / MinIO 위치(s3://...)
        - ``content_type`` / ``content_hash`` / ``size_bytes``: MIME / 중복판별 해시 / 크기
        - ``width`` / ``height``: 원본 픽셀 크기(bbox 좌표계 기준)
        - ``status``: draft/in_progress/completed
        - ``meta_json``: AI-Hub 메타 블록(Annotation/Dataset/Images)을 담는 JSONB
        - ``created_by`` / ``created_at`` / ``updated_at``
    """

    __tablename__ = "annotation_images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    image_id = Column(String(36), nullable=False, unique=True)
    collection_id = Column(
        Integer, ForeignKey("rag_collections.id", ondelete="SET NULL")
    )
    filename = Column(String(500), nullable=False)
    # 가상 폴더 경로(루트="" / 중첩="a/b"). 탐색기 폴더 트리·폴더별 목록의 기준.
    folder = Column(String(1000), nullable=False, default="")
    source_uri = Column(String(2000))
    # 썸네일 객체 위치(s3://...). 없으면 원본을 표시.
    thumb_uri = Column(String(2000))
    content_type = Column(String(100))
    content_hash = Column(String(64))
    width = Column(Integer, nullable=False, default=0)
    height = Column(Integer, nullable=False, default=0)
    size_bytes = Column(BigInteger, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="draft")
    meta_json = Column(JSONB)
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AnnotationBox(Base):
    """bbox 테이블 — 글자/단어 1개에 대응.

    ``seq`` 는 이미지 내에서 유니크하며 AI-Hub ``bbox.id`` 로 직렬화된다(1-based).
    """

    __tablename__ = "annotation_boxes"
    __table_args__ = (
        UniqueConstraint("image_id", "seq", name="uq_annotation_boxes_image_seq"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    image_id = Column(
        Integer, ForeignKey("annotation_images.id", ondelete="CASCADE"), nullable=False
    )
    seq = Column(Integer, nullable=False)
    data = Column(Text, nullable=False, default="")
    x1 = Column(Integer, nullable=False)
    y1 = Column(Integer, nullable=False)
    x2 = Column(Integer, nullable=False)
    y2 = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
