# SPDX-License-Identifier: Apache-2.0
"""서버 관리 API — 목록·등록·해제 + 에이전트(:4501) 프록시(inspect/top/processes/terminal)."""

import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session, get_session
from app.servermgr import service
from app.servermgr.schemas import (
    PaginatedServerResponse,
    RegisterRequest,
    RegisterResponse,
    UnregisterRequest,
    UnregisterResponse,
)

logger = logging.getLogger(__name__)

# Argus RAG Studio Agent 포트(고정).
AGENT_PORT = 4501

router = APIRouter(prefix="/servermgr", tags=["servermgr"])


@router.get("/servers", response_model=PaginatedServerResponse)
async def list_servers(
    status: str | None = Query(None, description="Filter by status (comma-separated for IN)"),
    search: str | None = Query(None, description="LIKE search on hostname, IP address"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    session: AsyncSession = Depends(get_session),
):
    """필터·페이지네이션으로 서버 목록 조회."""
    return await service.list_servers(
        session, status=status, search=search, page=page, page_size=page_size
    )


@router.post("/servers/register", response_model=RegisterResponse)
async def register_servers(body: RegisterRequest, session: AsyncSession = Depends(get_session)):
    """status 를 UNREGISTERED → REGISTERED 로 변경해 등록."""
    return await service.register_servers(session, hostnames=body.hostnames)


@router.post("/servers/unregister", response_model=UnregisterResponse)
async def unregister_servers(body: UnregisterRequest, session: AsyncSession = Depends(get_session)):
    """status 를 REGISTERED → UNREGISTERED 로 변경해 등록 해제."""
    return await service.unregister_servers(session, hostnames=body.hostnames)


async def _resolve_agent_ip(hostname: str) -> str:
    """hostname → 에이전트 IP. 미존재 시 404, REGISTERED 아니면 409.

    inspect/top/processes/terminal/서비스 등 관리 작업은 연결되어 관리 중(REGISTERED)인
    에이전트에서만 허용한다(UNREGISTERED/DISCONNECTED 차단). 조회 후 DB 세션은 즉시 반납.
    """
    async with async_session() as session:
        agent = await service.get_agent_by_hostname(session, hostname)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent not found: {hostname}")
    if agent.status != "REGISTERED":
        raise HTTPException(
            status_code=409,
            detail=f"등록(REGISTERED)된 에이전트에서만 가능한 작업입니다 (현재: {agent.status}).",
        )
    return agent.ip_address


@router.get("/servers/{hostname}/inspect")
async def server_inspect(hostname: str):
    """호스트 점검 요청을 에이전트로 프록시."""
    ip = await _resolve_agent_ip(hostname)
    agent_url = f"http://{ip}:{AGENT_PORT}/api/v1/host/inspect"
    logger.info("Inspect proxy: hostname=%s url=%s", hostname, agent_url)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(agent_url)
            return resp.json()
    except httpx.RequestError as e:
        logger.error("Inspect proxy error: hostname=%s err=%s", hostname, e)
        raise HTTPException(status_code=502, detail=f"Agent communication failed: {e}") from e


@router.get("/servers/{hostname}/top")
async def server_top(hostname: str, limit: int = Query(50, ge=1, le=500)):
    """top(htop 스타일) 요청을 에이전트로 프록시."""
    ip = await _resolve_agent_ip(hostname)
    agent_url = f"http://{ip}:{AGENT_PORT}/api/v1/sysmon/top?limit={limit}"
    logger.info("Top proxy: hostname=%s url=%s", hostname, agent_url)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(agent_url)
            return resp.json()
    except httpx.RequestError as e:
        logger.error("Top proxy error: hostname=%s err=%s", hostname, e)
        raise HTTPException(status_code=502, detail=f"Agent communication failed: {e}") from e


@router.get("/servers/{hostname}/processes")
async def server_processes(
    hostname: str,
    sort_by: str = Query("pid", description="Sort field"),
    limit: int = Query(0, ge=0, description="Max processes (0 = all)"),
):
    """프로세스 목록 요청을 에이전트로 프록시."""
    ip = await _resolve_agent_ip(hostname)
    agent_url = (
        f"http://{ip}:{AGENT_PORT}/api/v1/process/list?sort_by={sort_by}&limit={limit}"
    )
    logger.info("Processes proxy: hostname=%s url=%s", hostname, agent_url)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(agent_url)
            return resp.json()
    except httpx.RequestError as e:
        logger.error("Processes proxy error: hostname=%s err=%s", hostname, e)
        raise HTTPException(status_code=502, detail=f"Agent communication failed: {e}") from e


@router.post("/servers/{hostname}/processes/kill")
async def server_process_kill(hostname: str, body: dict):
    """프로세스 시그널(kill) 요청을 에이전트로 프록시."""
    ip = await _resolve_agent_ip(hostname)
    agent_url = f"http://{ip}:{AGENT_PORT}/api/v1/process/signal"
    logger.info("Process kill proxy: hostname=%s pid=%s", hostname, body.get("pid"))
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(agent_url, json=body)
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.RequestError as e:
        logger.error("Process kill proxy error: hostname=%s err=%s", hostname, e)
        raise HTTPException(status_code=502, detail=f"Agent communication failed: {e}") from e


@router.websocket("/servers/{hostname}/terminal/ws")
async def server_terminal_ws(websocket: WebSocket, hostname: str) -> None:
    """UI ↔ 에이전트 터미널 WebSocket 세션을 양방향 중계한다.

    argus_agents 에서 IP 를 조회한 뒤 에이전트의 터미널 엔드포인트로 연결해 메시지를
    상호 전달한다. 조회용 DB 세션은 짧게 열고 닫아 장수명 중계 동안 풀 슬롯을 점유하지 않는다.
    """
    async with async_session() as session:
        agent = await service.get_agent_by_hostname(session, hostname)

    if not agent:
        await websocket.close(code=4004, reason=f"Agent not found: {hostname}")
        return
    if agent.status != "REGISTERED":
        # 관리 작업은 REGISTERED 에이전트에서만. (UNREGISTERED/DISCONNECTED 차단)
        await websocket.close(code=4409, reason=f"Agent not registered: {agent.status}")
        return

    await websocket.accept()
    agent_ws_url = f"ws://{agent.ip_address}:{AGENT_PORT}/api/v1/terminal/ws"
    logger.info("Terminal proxy opening: hostname=%s url=%s", hostname, agent_ws_url)

    agent_ws = None
    try:
        import websockets

        agent_ws = await websockets.connect(agent_ws_url, close_timeout=5)

        async def ui_to_agent() -> None:
            """UI WebSocket → 에이전트 WebSocket 전달."""
            try:
                while True:
                    message = await websocket.receive()
                    if "text" in message:
                        await agent_ws.send(message["text"])
                    elif "bytes" in message:
                        await agent_ws.send(message["bytes"])
            except WebSocketDisconnect:
                pass

        async def agent_to_ui() -> None:
            """에이전트 WebSocket → UI WebSocket 전달."""
            try:
                async for data in agent_ws:
                    if isinstance(data, bytes):
                        await websocket.send_bytes(data)
                    else:
                        await websocket.send_text(data)
            except websockets.ConnectionClosed:
                pass

        ui_task = asyncio.create_task(ui_to_agent())
        agent_task = asyncio.create_task(agent_to_ui())
        _, pending = await asyncio.wait(
            [ui_task, agent_task], return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
    except Exception as e:
        logger.error("Terminal proxy error: hostname=%s err=%s", hostname, e)
    finally:
        if agent_ws is not None:
            try:
                await agent_ws.close()
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass
        logger.info("Terminal proxy closed: hostname=%s", hostname)


# ---------------------------------------------------------------------------
# 실시간 메트릭 프록시 (상세 페이지 차트용) — 에이전트 monitor/sysmon 그대로 전달
# ---------------------------------------------------------------------------

# servermgr 경로 → 에이전트 경로 매핑 (모두 REGISTERED 가드 + GET 패스스루)
_METRIC_PROXIES = {
    "metrics": "/api/v1/monitor/system",
    "gpu": "/api/v1/sysmon/gpu",
    "cpu-cores": "/api/v1/sysmon/cpu/cores",
    "network": "/api/v1/sysmon/network",
    "disk": "/api/v1/sysmon/disk/partitions",
}


async def _proxy_metric(hostname: str, key: str):
    ip = await _resolve_agent_ip(hostname)
    url = f"http://{ip}:{AGENT_PORT}{_METRIC_PROXIES[key]}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Agent communication failed: {e}") from e


@router.get("/servers/{hostname}/metrics")
async def server_metrics(hostname: str):
    """CPU·메모리·디스크·네트워크 스냅샷(monitor/system) 프록시 — 요약/개요 차트용."""
    return await _proxy_metric(hostname, "metrics")


@router.get("/servers/{hostname}/gpu")
async def server_gpu(hostname: str):
    """GPU별 메트릭(sysmon/gpu) 프록시 — 디스크리트 풀/통합메모리 N/A 모두."""
    return await _proxy_metric(hostname, "gpu")


@router.get("/servers/{hostname}/cpu-cores")
async def server_cpu_cores(hostname: str):
    """코어별 CPU 사용률(sysmon/cpu/cores) 프록시."""
    return await _proxy_metric(hostname, "cpu-cores")


@router.get("/servers/{hostname}/network")
async def server_network(hostname: str):
    """네트워크 인터페이스 누적 카운터(sysmon/network) 프록시 — 클라가 rate 계산."""
    return await _proxy_metric(hostname, "network")


@router.get("/servers/{hostname}/disk")
async def server_disk(hostname: str):
    """디스크 파티션 현황(sysmon/disk/partitions) 프록시."""
    return await _proxy_metric(hostname, "disk")
