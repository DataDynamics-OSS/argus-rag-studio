"""Remote terminal API routes."""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.terminal.service import terminal_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/terminal", tags=["terminal"])


@router.websocket("/ws")
async def terminal_ws(websocket: WebSocket) -> None:
    """Open a remote terminal session via WebSocket.

    Protocol:
    - Text messages are written as input to the terminal.
    - Binary messages are treated as raw bytes input.
    - JSON messages with {"type": "resize", "rows": N, "cols": N} resize the terminal.
    - Server sends terminal output as text messages.
    """
    await websocket.accept()
    session_id = str(uuid.uuid4())

    # Ensure the stale-session reaper is running.
    terminal_manager.start_reaper()

    try:
        session = terminal_manager.create_session(session_id)
    except RuntimeError as e:
        await websocket.send_text(f"Error: {e}")
        await websocket.close()
        return

    logger.info("Terminal WebSocket connected: %s (session=%s)", websocket.client, session_id)

    async def read_loop() -> None:
        """Read from PTY and send to WebSocket."""
        while session.active:
            try:
                data = await terminal_manager.read_output(session_id)
                if not data:
                    break
                await websocket.send_bytes(data)
            except Exception:
                break

    read_task = asyncio.create_task(read_loop())

    try:
        while True:
            message = await websocket.receive()

            if "text" in message:
                text = message["text"]
                # Check for resize command
                try:
                    payload = json.loads(text)
                    if payload.get("type") == "resize":
                        terminal_manager.resize(
                            session_id,
                            rows=payload["rows"],
                            cols=payload["cols"],
                        )
                        continue
                except (json.JSONDecodeError, KeyError, OSError):
                    pass
                try:
                    terminal_manager.write_input(session_id, text.encode())
                except (KeyError, OSError):
                    break

            elif "bytes" in message:
                try:
                    terminal_manager.write_input(session_id, message["bytes"])
                except (KeyError, OSError):
                    break

    except WebSocketDisconnect:
        logger.info("Terminal WebSocket disconnected: %s", session_id)
    except Exception as e:
        logger.warning("Terminal WebSocket error: %s err=%s", session_id, e)
    finally:
        read_task.cancel()
        terminal_manager.close_session(session_id)
