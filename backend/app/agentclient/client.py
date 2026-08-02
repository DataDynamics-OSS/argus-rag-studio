# SPDX-License-Identifier: Apache-2.0
"""Argus Insight Agent REST 클라이언트.

컨트롤러(RAG Studio)가 원격 Agent(:4501)의 servicemgr API 를 호출한다.
멱등 호출(GET/DELETE/생성-by-name)은 일시적 오류에 한해 재시도하며, 모든 실패는
``AgentError`` 로 정규화한다(라우터가 502 로 변환).
"""

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


class AgentError(Exception):
    """Agent 호출 실패. status_code 는 Agent 가 돌려준 HTTP 코드(없으면 None)."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AgentClient:
    """단일 Agent 에 대한 얇은 비동기 클라이언트."""

    def __init__(
        self,
        ip: str,
        port: int = 4501,
        token: str | None = None,
        timeout: float = 30.0,
        retries: int = 2,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = f"http://{ip}:{port}/api/v1"
        self._headers = {"X-Agent-Token": token} if token else {}
        self._timeout = timeout
        self._retries = retries
        self._transport = transport  # 테스트에서 MockTransport 주입

    async def _request(self, method: str, path: str, **kw):
        url = f"{self._base}{path}"
        last_exc: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout, transport=self._transport
                ) as client:
                    resp = await client.request(method, url, headers=self._headers, **kw)
                # 5xx 는 재시도, 4xx 는 즉시 실패(클라이언트 오류).
                if resp.status_code >= 500:
                    last_exc = AgentError(
                        f"agent {method} {path} -> {resp.status_code}: {resp.text}",
                        resp.status_code,
                    )
                    raise last_exc
                if resp.status_code >= 400:
                    detail = _extract_detail(resp)
                    raise AgentError(
                        f"agent {method} {path} -> {resp.status_code}: {detail}",
                        resp.status_code,
                    )
                return resp.json() if resp.content else None
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last_exc = AgentError(f"agent {method} {path} 연결 실패: {e}")
            except AgentError as e:
                if e.status_code and e.status_code < 500:
                    raise  # 4xx 는 재시도하지 않음
                last_exc = e

            if attempt < self._retries:
                await asyncio.sleep(0)  # 양보(테스트 친화). 실제 backoff 는 추후.
        assert last_exc is not None
        raise last_exc

    # --- servicemgr 매핑 ---

    async def list_services(self) -> list[dict]:
        return await self._request("GET", "/service") or []

    async def get_service(self, name: str) -> dict:
        return await self._request("GET", f"/service/{name}")

    async def create_service(self, spec: dict) -> dict:
        return await self._request("POST", "/service", json=spec)

    async def start_service(self, name: str) -> dict:
        return await self._request("POST", f"/service/{name}/start")

    async def stop_service(self, name: str) -> dict:
        return await self._request("POST", f"/service/{name}/stop")

    async def restart_service(self, name: str) -> dict:
        return await self._request("POST", f"/service/{name}/restart")

    async def set_enabled(self, name: str, enabled: bool) -> dict:
        return await self._request("PUT", f"/service/{name}/enabled", json={"enabled": enabled})

    async def remove_service(self, name: str) -> dict:
        return await self._request("DELETE", f"/service/{name}")


def _extract_detail(resp: httpx.Response) -> str:
    """FastAPI 오류 본문에서 detail 을 뽑아낸다(없으면 원문)."""
    try:
        body = resp.json()
        if isinstance(body, dict) and "detail" in body:
            return str(body["detail"])
    except Exception:
        pass
    return resp.text
