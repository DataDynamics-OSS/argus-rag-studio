# SPDX-License-Identifier: Apache-2.0
"""에이전트(:4501) 호출 헬퍼 — docker/systemd 전략 공용. REGISTERED 가드 + 능력(arch/gpu) 조회."""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from app.core.database import async_session
from app.deploy.models import DeployError
from app.servermgr import service as servermgr

AGENT_PORT = 4501


@dataclass
class AgentHost:
    ip: str
    arch: str | None
    gpu_count: int | None


async def resolve_host(hostname: str) -> AgentHost:
    """hostname → 에이전트 IP·arch·gpu_count. 미존재 404 / 미등록 409.

    관리 작업은 연결되어 관리 중(REGISTERED)인 에이전트에서만 허용한다.
    """
    async with async_session() as session:
        agent = await servermgr.get_agent_by_hostname(session, hostname)
    if not agent:
        raise DeployError(f"Agent not found: {hostname}", code=404)
    if agent.status != "REGISTERED":
        raise DeployError(
            f"등록(REGISTERED)된 에이전트에서만 가능한 작업입니다 (현재: {agent.status}).", code=409
        )
    return AgentHost(ip=agent.ip_address, arch=agent.arch, gpu_count=agent.gpu_count)


def agent_url(ip: str, path: str) -> str:
    return f"http://{ip}:{AGENT_PORT}{path}"


async def agent_request(method: str, ip: str, path: str, *, json=None, timeout: float = 60.0):
    """에이전트에 요청하고 JSON 반환. 4xx/5xx → DeployError, 통신 실패 → 502."""
    url = agent_url(ip, path)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, url, json=json)
    except httpx.RequestError as e:
        raise DeployError(f"Agent communication failed: {e}", code=502) from e
    if resp.status_code >= 400:
        raise DeployError(f"Agent error {resp.status_code}: {resp.text}", code=resp.status_code)
    if resp.headers.get("content-type", "").startswith("application/json"):
        return resp.json()
    return resp.text


async def agent_stream(ip: str, path: str, json_body):
    """에이전트 NDJSON 스트림(POST)을 줄단위로 파싱해 이벤트(dict)를 yield."""
    url = agent_url(ip, path)
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, json=json_body) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    raise DeployError(
                        f"Agent error {resp.status_code}: {body.decode(errors='replace')}",
                        code=resp.status_code,
                    )
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if line:
                        yield json.loads(line)
    except httpx.RequestError as e:
        raise DeployError(f"Agent communication failed: {e}", code=502) from e
