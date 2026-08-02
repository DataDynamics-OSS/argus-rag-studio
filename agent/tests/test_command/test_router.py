"""Tests for command execution API."""

import pytest


@pytest.mark.asyncio
async def test_execute_command(client):
    """Test basic command execution."""
    response = await client.post(
        "/api/v1/command/execute",
        json={"command": "echo hello"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["exit_code"] == 0
    assert "hello" in data["stdout"]


@pytest.mark.asyncio
async def test_blocked_command(client):
    """Test that dangerous commands are blocked."""
    response = await client.post(
        "/api/v1/command/execute",
        json={"command": "rm -rf /"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["exit_code"] == -1
    assert "blocked" in data["stderr"].lower()
