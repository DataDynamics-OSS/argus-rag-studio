# SPDX-License-Identifier: Apache-2.0
"""소스 워치 — seen 스킵 규칙·백오프(순수 로직) 단위 테스트. 설계 design/source-watch.md §3."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.routing.scan import should_skip_seen
from app.sourcewatch.service import backoff_seconds

MT = datetime(2026, 7, 12, 10, 0, 0, tzinfo=timezone.utc)


def _seen(status: str, *, size: int = 100, mtime=MT, policy_version: int | None = 3):
    return SimpleNamespace(size=size, mtime=mtime, status=status, policy_version=policy_version)


# ── seen 스킵 규칙 ────────────────────────────────────────────────────────────

def test_skip_new_file_never():
    assert should_skip_seen(None, 100, MT, 3) is False


def test_skip_routed_duplicate_when_fingerprint_same():
    assert should_skip_seen(_seen("routed"), 100, MT, 99) is True      # 정책 무관
    assert should_skip_seen(_seen("duplicate"), 100, MT, 99) is True


def test_reprocess_when_fingerprint_changed():
    assert should_skip_seen(_seen("routed"), 101, MT, 3) is False              # size 변경
    assert should_skip_seen(_seen("routed"), 100, MT + timedelta(seconds=1), 3) is False  # mtime 변경
    assert should_skip_seen(_seen("routed", mtime=None), 100, None, 3) is False  # 지문 불충분


def test_no_route_failed_respects_policy_version():
    # 같은 정책이면 결과가 같다 — skip. 정책이 바뀌면 새 규칙으로 구제될 수 있다 — 재평가.
    assert should_skip_seen(_seen("no_route", policy_version=3), 100, MT, 3) is True
    assert should_skip_seen(_seen("no_route", policy_version=3), 100, MT, 4) is False
    assert should_skip_seen(_seen("failed", policy_version=3), 100, MT, 3) is True
    assert should_skip_seen(_seen("failed", policy_version=None), 100, MT, 3) is False


def test_skip_handles_naive_mtime():
    # NAS(os.stat) 가 naive mtime 을 줄 수 있다 — UTC 로 간주해 비교.
    naive = MT.replace(tzinfo=None)
    assert should_skip_seen(_seen("routed", mtime=naive), 100, MT, 3) is True


# ── 백오프 ───────────────────────────────────────────────────────────────────

def test_backoff_doubles_and_caps():
    assert backoff_seconds(300, 0) == 300
    assert backoff_seconds(300, 1) == 600
    assert backoff_seconds(300, 2) == 1200
    assert backoff_seconds(300, 10) == 3600  # 상한 1시간
