# SPDX-License-Identifier: Apache-2.0
"""관측 모듈의 Pydantic 스키마."""

from datetime import datetime

from pydantic import BaseModel


class TraceResponse(BaseModel):
    id: int
    trace_id: str
    kind: str
    collection_id: int | None = None
    query: str | None = None
    mode: str | None = None
    distance_metric: str | None = None
    rerank: bool
    status: str
    error: str | None = None
    hit_count: int
    retrieval_ms: float | None = None
    rerank_ms: float | None = None
    generation_ms: float | None = None
    total_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    answer: str | None = None
    created_by: str | None = None
    created_at: datetime


class LatencyStat(BaseModel):
    avg: float | None = None
    p50: float | None = None
    p95: float | None = None


class TopQuery(BaseModel):
    query: str
    count: int


class StatsResponse(BaseModel):
    total: int
    ok: int
    error: int
    success_rate: float | None = None
    total_ms: LatencyStat
    embedding_ms: LatencyStat
    search_ms: LatencyStat
    retrieval_ms: LatencyStat
    rerank_ms: LatencyStat
    generation_ms: LatencyStat
    prompt_tokens: int
    completion_tokens: int
    top_queries: list[TopQuery]
