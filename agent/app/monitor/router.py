"""Server resource monitoring API routes."""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.monitor.schemas import SystemInfo
from app.monitor.service import get_system_info

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitor", tags=["monitor"])


@router.get("/system", response_model=SystemInfo)
async def system_info() -> SystemInfo:
    """Get current system resource information."""
    return get_system_info()


@router.websocket("/ws")
async def monitor_ws(websocket: WebSocket) -> None:
    """Stream system resource information via WebSocket."""
    await websocket.accept()
    logger.info("Monitor WebSocket connected: %s", websocket.client)

    try:
        while True:
            info = get_system_info()
            await websocket.send_text(info.model_dump_json())
            await asyncio.sleep(settings.monitor_interval)
    except WebSocketDisconnect:
        logger.info("Monitor WebSocket disconnected: %s", websocket.client)
