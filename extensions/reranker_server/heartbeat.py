# SPDX-License-Identifier: Apache-2.0
"""확장 서버 하트비트 클라이언트 — 자신을 RAG 백엔드 레지스트리에 주기적으로 등록한다.

LB 뒤 레플리카는 백엔드의 `/stats` 풀 프로브로 1대만 보이므로, 각 레플리카가 자기 정체성 +
`/stats` 스냅샷을 백엔드(`POST /api/v1/ext-servers/heartbeat`)로 push 하면 풀 전체가 모니터링된다.

환경변수(미설정 시 비활성 — 추가 의존성 없음, stdlib urllib 사용):
  - ``ARGUS_HEARTBEAT_URL``      : 백엔드 수신 URL (예 http://rag-backend:4700/api/v1/ext-servers/heartbeat)
  - ``ARGUS_HEARTBEAT_TOKEN``    : 공유 토큰(백엔드 monitoring.heartbeat_token 과 일치, 선택)
  - ``ARGUS_INSTANCE_URL``       : 이 레플리카의 직접 주소(표시용, 예 http://192.0.2.48:8090)
  - ``ARGUS_HEARTBEAT_INTERVAL`` : 주기(초, 기본 10)

모든 확장 서버에 동일 파일을 둔다(서버 패키지 비의존). 서버 종류(kind)·버전·스냅샷 함수는 호출 측이 넘긴다.
"""

import asyncio
import json
import logging
import os
import socket
import urllib.request
import uuid
from typing import Callable

logger = logging.getLogger("ext_heartbeat")

_URL = os.environ.get("ARGUS_HEARTBEAT_URL", "").strip()
_TOKEN = os.environ.get("ARGUS_HEARTBEAT_TOKEN", "").strip()
_INSTANCE_URL = os.environ.get("ARGUS_INSTANCE_URL", "").strip()
try:
    _INTERVAL = float(os.environ.get("ARGUS_HEARTBEAT_INTERVAL", "10") or 10)
except ValueError:
    _INTERVAL = 10.0

_INSTANCE_ID = uuid.uuid4().hex  # 프로세스(레플리카)당 고정 식별자


def _post(payload: dict) -> None:
    """동기 POST(스레드에서 호출). 실패는 호출 측에서 무시."""
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if _TOKEN:
        headers["X-Heartbeat-Token"] = _TOKEN
    req = urllib.request.Request(_URL, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=5):
        pass


async def _loop(kind: str, version: str, snapshot_fn: Callable[[], dict]) -> None:
    while True:
        try:
            payload = {
                "instance_id": _INSTANCE_ID,
                "kind": kind,
                "hostname": socket.gethostname(),
                "url": _INSTANCE_URL or None,
                "version": version,
                "stats": snapshot_fn(),
            }
            await asyncio.to_thread(_post, payload)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — 하트비트 실패가 서버를 멈추지 않는다
            logger.warning("하트비트 전송 실패(%s): %s", _URL, e)
        await asyncio.sleep(_INTERVAL)


def start(kind: str, version: str, snapshot_fn: Callable[[], dict]) -> "asyncio.Task | None":
    """``ARGUS_HEARTBEAT_URL`` 이 설정돼 있으면 하트비트 루프를 띄운다(없으면 None=비활성)."""
    if not _URL:
        return None
    logger.info("하트비트 시작: kind=%s id=%s → %s (interval=%.0fs)",
                kind, _INSTANCE_ID, _URL, _INTERVAL)
    return asyncio.create_task(_loop(kind, version, snapshot_fn))


def _delete() -> None:
    """레지스트리에서 자신을 제거(동기 DELETE, 스레드에서 호출)."""
    base = _URL.rsplit("/heartbeat", 1)[0]
    url = f"{base}/{_INSTANCE_ID}"
    headers = {"X-Heartbeat-Token": _TOKEN} if _TOKEN else {}
    req = urllib.request.Request(url, method="DELETE", headers=headers)
    with urllib.request.urlopen(req, timeout=5):
        pass


async def stop(task: "asyncio.Task | None") -> None:
    """하트비트 루프 중단 + 레지스트리에서 즉시 디레지스터(정상 종료 시)."""
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if not _URL:
        return
    try:
        await asyncio.to_thread(_delete)
        logger.info("디레지스터 완료: id=%s", _INSTANCE_ID)
    except Exception as e:  # noqa: BLE001 — 디레지스터 실패해도 백엔드 prune 이 정리
        logger.warning("디레지스터 실패: %s", e)
