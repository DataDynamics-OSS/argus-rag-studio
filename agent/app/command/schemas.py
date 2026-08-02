"""Command execution request/response schemas."""

from pydantic import BaseModel, Field


class CommandRequest(BaseModel):
    """Request to execute a command."""

    command: str = Field(..., description="Shell command to execute")
    timeout: int | None = Field(None, description="Timeout in seconds (overrides default)")
    cwd: str | None = Field(None, description="Working directory for the command")


class CommandResponse(BaseModel):
    """Response from command execution."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
