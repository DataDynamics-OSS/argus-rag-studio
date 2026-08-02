"""Tests for heartbeat system info - managed services inventory."""

from unittest.mock import AsyncMock, patch

from app.heartbeat import system_info
from app.servicemgr.schemas import ServiceStatus


async def test_get_managed_services_maps_statuses():
    statuses = [
        ServiceStatus(
            name="argus-rag-worker-1",
            exists=True,
            active_state="active",
            sub_state="running",
            enabled=True,
            pid=123,
            kind="worker",
            version="0.4.2",
        )
    ]
    with patch(
        "app.servicemgr.service.list_managed", new_callable=AsyncMock
    ) as lm:
        lm.return_value = statuses
        result = await system_info.get_managed_services()

    assert result == [
        {
            "name": "argus-rag-worker-1",
            "kind": "worker",
            "runtime": "systemd",
            "version": "0.4.2",
            "active_state": "active",
            "sub_state": "running",
            "enabled": True,
            "pid": 123,
        }
    ]


async def test_get_managed_services_swallows_errors():
    with patch(
        "app.servicemgr.service.list_managed", new_callable=AsyncMock
    ) as lm:
        lm.side_effect = RuntimeError("systemctl unavailable")
        result = await system_info.get_managed_services()
    assert result == []
