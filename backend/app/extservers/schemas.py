# SPDX-License-Identifier: Apache-2.0
"""외부 확장 서버 레지스트리 스키마."""

from pydantic import BaseModel, Field


class ExtServerHeartbeat(BaseModel):
    """레플리카가 주기적으로 보내는 하트비트(자기 등록)."""

    instance_id: str = Field(..., max_length=64)   # 레플리카 프로세스당 고정 uuid
    kind: str = Field(..., max_length=20)           # embedding | reranker | detection
    hostname: str | None = Field(None, max_length=255)
    url: str | None = Field(None, max_length=500)   # 이 레플리카의 직접 주소(표시용)
    version: str | None = Field(None, max_length=40)
    stats: dict | None = None                       # /stats 스냅샷
