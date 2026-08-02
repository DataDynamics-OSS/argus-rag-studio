"""Command execution API routes."""

from fastapi import APIRouter

from app.command.schemas import CommandRequest, CommandResponse
from app.command.service import execute_command

router = APIRouter(prefix="/command", tags=["command"])


@router.post("/execute", response_model=CommandResponse)
async def run_command(request: CommandRequest) -> CommandResponse:
    """Execute a shell command on the server."""
    return await execute_command(
        command=request.command,
        timeout=request.timeout,
        cwd=request.cwd,
    )
