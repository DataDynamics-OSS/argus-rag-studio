"""Tests for monitoring API."""

import pytest


@pytest.mark.asyncio
async def test_system_info(client):
    """Test system info endpoint."""
    response = await client.get("/api/v1/monitor/system")
    assert response.status_code == 200
    data = response.json()
    assert "hostname" in data
    assert "cpu" in data
    assert "memory" in data
    assert "disks" in data
