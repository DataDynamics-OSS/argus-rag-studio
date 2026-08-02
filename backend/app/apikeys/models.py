# SPDX-License-Identifier: Apache-2.0
"""API 키(서비스 계정) ORM 모델.

외부 시스템이 ``search``/``query``/``chat`` 등을 프로그래밍 방식으로 호출할 때 쓰는
장기 자격 증명. 평문 키는 발급 시 1회만 노출하고, DB 에는 SHA-256 해시(``key_hash``)만
저장한다. 권한은 ``role_id`` (사용자와 동일한 역할 식별자, 예 ``argus-user``)로 부여한다.
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func

from app.core.database import Base


class ApiKey(Base):
    """API 키 테이블. 평문은 저장하지 않으며 ``key_hash`` 로만 검증한다."""

    __tablename__ = "argus_api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(String(255))
    # 표시용 앞부분 (예: "argus_sk_AbCd…") — 어떤 키인지 식별만 가능, 복원 불가
    key_prefix = Column(String(20), nullable=False)
    # sha256(평문 키) 16진 64자
    key_hash = Column(String(64), nullable=False, unique=True)
    # 권한 역할 식별자 — argus-admin | argus-superuser | argus-user
    role_id = Column(String(50), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    # NULL 이면 무기한
    expires_at = Column(DateTime(timezone=True))
    last_used_at = Column(DateTime(timezone=True))
    created_by = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
