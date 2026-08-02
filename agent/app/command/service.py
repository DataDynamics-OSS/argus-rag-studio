"""Command execution service."""

import asyncio
import logging

from app.command.schemas import CommandResponse
from app.core.config import settings
from app.core.security import is_command_blocked

logger = logging.getLogger(__name__)


async def execute_command(
    command: str,
    timeout: int | None = None,
    cwd: str | None = None,
) -> CommandResponse:
    """Execute a shell command asynchronously."""
    if is_command_blocked(command):
        return CommandResponse(
            exit_code=-1,
            stdout="",
            stderr=f"Command blocked by security policy: {command}",
        )

    effective_timeout = timeout or settings.command_timeout
    logger.info("Executing command: %s (timeout=%ds)", command, effective_timeout)

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=effective_timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return CommandResponse(
                exit_code=-1,
                stdout="",
                stderr=f"Command timed out after {effective_timeout}s",
                timed_out=True,
            )

        return CommandResponse(
            exit_code=process.returncode or 0,
            stdout=stdout.decode(errors="replace")[: settings.command_max_output],
            stderr=stderr.decode(errors="replace")[: settings.command_max_output],
        )

    except Exception as e:
        logger.exception("Command execution failed: %s", command)
        return CommandResponse(exit_code=-1, stdout="", stderr=str(e))
