# SPDX-License-Identifier: Apache-2.0
"""소스 워치 ORM — 워치 설정·실행 이력·증분 스캔(seen) 캐시.

설계: design/source-watch.md §3. seen 은 최적화 캐시(지워져도 정확성은 content_hash
중복 차단이 보장)라 소스 기준 키로 두어 프리픽스가 겹치는 워치끼리 이중 읽기를 막는다.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.core.database import Base


class RagSourceWatch(Base):
    """워치 1개 — 소스+폴더(prefix)+주기. 소스 하나에 폴더별 워치 여러 개 허용."""

    __tablename__ = "rag_source_watches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    watch_id = Column(String(36), nullable=False, unique=True)
    source_id = Column(
        Integer, ForeignKey("rag_storage_sources.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(200), nullable=False)
    prefix = Column(String(2000), nullable=False, default="")
    recursive = Column(Boolean, nullable=False, default=True)
    interval_seconds = Column(Integer, nullable=False, default=300)  # min 60(설정)
    enabled = Column(Boolean, nullable=False, default=True)
    next_run_at = Column(DateTime(timezone=True), server_default=func.now())
    last_run_at = Column(DateTime(timezone=True))
    last_status = Column(String(20))          # ok | error | NULL(미실행)
    last_error = Column(Text)
    last_counts_json = Column(Text)           # 마지막 실행 집계(UI 표시)
    consecutive_failures = Column(Integer, nullable=False, default=0)  # 백오프 계산용
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RagSourceWatchRun(Base):
    """워치 실행 이력(집계 요약) — 워치당 최근 N개만 유지(문서 단위 감사는 결정 로그가 담당)."""

    __tablename__ = "rag_source_watch_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    watch_id = Column(
        Integer, ForeignKey("rag_source_watches.id", ondelete="CASCADE"), nullable=False
    )
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))
    scanned = Column(Integer, nullable=False, default=0)
    skipped = Column(Integer, nullable=False, default=0)   # seen 지문 동일로 건너뜀
    counts_json = Column(Text)                             # {"routed":3,"duplicate":45,...}
    truncated = Column(Boolean, nullable=False, default=False)
    error = Column(Text)


class RagSourceSeenFile(Base):
    """증분 스캔 캐시 — list() 의 size/mtime 지문으로 읽기 전에 건너뛴다(비용의 핵심)."""

    __tablename__ = "rag_source_seen_files"
    __table_args__ = (UniqueConstraint("source_id", "path", name="uq_source_seen_path"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(
        Integer, ForeignKey("rag_storage_sources.id", ondelete="CASCADE"), nullable=False
    )
    path = Column(String(2000), nullable=False)
    size = Column(BigInteger, nullable=False, default=0)
    mtime = Column(DateTime(timezone=True))
    status = Column(String(20), nullable=False)   # routed | duplicate | no_route | failed
    policy_version = Column(Integer)              # no_route/failed 재평가 판단용
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now())
