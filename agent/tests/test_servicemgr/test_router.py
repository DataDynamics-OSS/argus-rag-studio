"""Tests for servicemgr API routes."""

from unittest.mock import AsyncMock, patch

import pytest

from app.servicemgr import service

SHOW_OUTPUT = "\n".join(
    [
        "LoadState=loaded",
        "ActiveState=active",
        "SubState=running",
        "UnitFileState=enabled",
        "MainPID=12345",
        "ExecMainStatus=0",
    ]
)


@pytest.fixture
def systemd_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "SYSTEMD_DIR", tmp_path)
    return tmp_path


def _spec_payload(**kw) -> dict:
    base = {
        "name": "argus-rag-worker-1",
        "exec_start": "/opt/venv/bin/python -m app.worker_main",
        "kind": "worker",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


async def test_create_service(client, systemd_dir):
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (0, SHOW_OUTPUT, "")
        resp = await client.post("/api/v1/service", json=_spec_payload())

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "argus-rag-worker-1"
    assert data["active_state"] == "active"
    assert (systemd_dir / "argus-rag-worker-1.service").is_file()


async def test_create_rejects_unmanaged_name(client, systemd_dir):
    resp = await client.post("/api/v1/service", json=_spec_payload(name="nginx"))
    assert resp.status_code == 403


async def test_create_rejects_injection_in_exec_start(client, systemd_dir):
    resp = await client.post(
        "/api/v1/service",
        json=_spec_payload(exec_start="ok\nExecStartPre=/bin/evil"),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# status / list
# ---------------------------------------------------------------------------


async def test_status_not_found(client, systemd_dir):
    resp = await client.get("/api/v1/service/argus-rag-worker-9")
    assert resp.status_code == 404


async def test_status_found(client, systemd_dir):
    (systemd_dir / "argus-rag-worker-1.service").write_text("# X-Argus-Kind=worker\n")
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (0, SHOW_OUTPUT, "")
        resp = await client.get("/api/v1/service/argus-rag-worker-1")
    assert resp.status_code == 200
    assert resp.json()["pid"] == 12345


async def test_status_guard_unmanaged(client, systemd_dir):
    resp = await client.get("/api/v1/service/nginx")
    assert resp.status_code == 403


async def test_list_services(client, systemd_dir):
    (systemd_dir / "argus-rag-worker-1.service").write_text("# X-Argus-Kind=worker\n")
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (0, SHOW_OUTPUT, "")
        resp = await client.get("/api/v1/service")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "argus-rag-worker-1"


# ---------------------------------------------------------------------------
# lifecycle actions
# ---------------------------------------------------------------------------


async def test_start_not_found(client, systemd_dir):
    resp = await client.post("/api/v1/service/argus-rag-worker-9/start")
    assert resp.status_code == 404


async def test_restart_found(client, systemd_dir):
    (systemd_dir / "argus-rag-worker-1.service").write_text("x")
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.side_effect = [(0, "", ""), (0, SHOW_OUTPUT, "")]
        resp = await client.post("/api/v1/service/argus-rag-worker-1/restart")
    assert resp.status_code == 200
    assert resp.json()["active_state"] == "active"


async def test_set_enabled(client, systemd_dir):
    (systemd_dir / "argus-rag-worker-1.service").write_text("x")
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (0, "", "")
        resp = await client.put(
            "/api/v1/service/argus-rag-worker-1/enabled", json={"enabled": False}
        )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


async def test_remove_found(client, systemd_dir):
    unit = systemd_dir / "argus-rag-worker-1.service"
    unit.write_text("x")
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (0, "", "")
        resp = await client.delete("/api/v1/service/argus-rag-worker-1")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert not unit.exists()


async def test_remove_not_found(client, systemd_dir):
    resp = await client.delete("/api/v1/service/argus-rag-worker-9")
    assert resp.status_code == 404
