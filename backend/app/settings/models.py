# SPDX-License-Identifier: Apache-2.0
"""플랫폼 설정 저장 모델 (key-value).

config 파일이 기본값을 제공하고, 운영자가 UI(설정 화면)에서 바꾼 값은 이 테이블에
override 로 저장된다. 기동 시 ``load_into_runtime`` 이 override 를 전역 ``settings`` 객체에
덮어써, 인제스천 워커/임베딩 서비스가 변경값을 그대로 사용한다.
"""

from sqlalchemy import Column, DateTime, String, Text, func

from app.core.database import Base


class AppSetting(Base):
    """key-value 설정 override 행."""

    __tablename__ = "argus_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
