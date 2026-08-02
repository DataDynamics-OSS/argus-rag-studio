# SPDX-License-Identifier: Apache-2.0
"""PII 정규식 규칙 ORM 모델.

``RagPiiRule``: 본문에서 개인정보를 찾아 마스킹하는 정규식 규칙. 인제스천 보강의 ``pii_regex``
transform(post_parse)이 enabled 규칙을 불러 적용한다. 규칙은 전역(컬렉션 공유) 자산이다.
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func

from app.core.database import Base


class RagPiiRule(Base):
    __tablename__ = "rag_pii_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(String(36), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    category = Column(String(40), nullable=False, default="custom")  # rrn | email | phone | card | custom ...
    pattern = Column(Text, nullable=False)                           # 파이썬 re 정규식
    flags = Column(String(20), nullable=False, default="")           # i(IGNORECASE) m(MULTILINE) s(DOTALL) 조합
    mask = Column(String(200), nullable=False, default="[REDACTED]") # 치환 문자열
    enabled = Column(Boolean, nullable=False, default=True)
    description = Column(Text)
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RagPiiFunction(Base):
    """사용자 정의 PII 함수 — 관리자가 작성한 파이썬 코드(샌드박스 실행).

    계약: ``def redact(text: str) -> str`` 정의. 인제스천 ``pii_function`` transform(post_parse)이
    enabled 함수를 별도 프로세스 샌드박스로 실행한다. import·위험 빌트인은 AST 검증으로 차단된다.
    """

    __tablename__ = "rag_pii_functions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    function_id = Column(String(36), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    code = Column(Text, nullable=False)                       # redact(text)->str 정의 코드
    timeout_ms = Column(Integer, nullable=False, default=2000)
    enabled = Column(Boolean, nullable=False, default=True)
    description = Column(Text)
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
