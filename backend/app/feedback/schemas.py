# SPDX-License-Identifier: Apache-2.0
"""피드백 모듈의 Pydantic 스키마."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class FeedbackCreateRequest(BaseModel):
    rating: Literal["up", "down"]
    query: str = Field(..., min_length=1)
    answer: str | None = None
    collection_id: int | None = None
    trace_id: str | None = None
    comment: str | None = None
    corrected_answer: str | None = None
    expected_sources: list[str] = Field(default_factory=list)


class FeedbackResponse(BaseModel):
    id: int
    feedback_id: str
    trace_id: str | None = None
    collection_id: int | None = None
    query: str
    answer: str | None = None
    rating: str
    comment: str | None = None
    corrected_answer: str | None = None
    expected_sources: list[str]
    status: str
    promoted_item_id: int | None = None
    created_by: str | None = None
    created_at: datetime


class PromoteRequest(BaseModel):
    """피드백을 평가 골든셋 항목으로 승격한다."""

    dataset_id: int
    # 미지정 시 corrected_answer > answer 순으로 기대답변에 사용
    expected_answer: str | None = None
    expected_sources: list[str] | None = None


class FeedbackStats(BaseModel):
    total: int
    up: int
    down: int
    new: int
    promoted: int
