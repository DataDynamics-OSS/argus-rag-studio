"""Tests for containermgr API routes."""

from unittest.mock import AsyncMock, patch

from app.containermgr import service

INSPECT_OK = "\t".join(
    [
        "abc123",
        "argus/embedding-server:latest",
        "running",
        "0",
        "2026-06-20T01:00:00Z",
        "embedding",
        "0.4.2",
    ]
)


def _payload(**kw) -> dict:
    base = {
        "name": "argus-rag-embedding-1",
        "image": "argus/embedding-server:latest",
        "kind": "embedding",
    }
    base.update(kw)
    return base


async def test_create_container(client):
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (0, INSPECT_OK, "")
        resp = await client.post("/api/v1/container", json=_payload(ports=["8080:8080"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "argus-rag-embedding-1"
    assert data["state"] == "running"


async def test_create_rejects_unmanaged_name(client):
    resp = await client.post("/api/v1/container", json=_payload(name="nginx"))
    assert resp.status_code == 403


async def test_status_not_found(client):
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (1, "", "No such object")
        resp = await client.get("/api/v1/container/argus-rag-embedding-9")
    assert resp.status_code == 404


async def test_status_guard_unmanaged(client):
    resp = await client.get("/api/v1/container/nginx")
    assert resp.status_code == 403


async def test_list_containers(client):
    async def fake(args):
        if args[0] == "ps":
            return (0, "argus-rag-embedding-1", "")
        return (0, INSPECT_OK, "")

    with patch.object(service, "_run", side_effect=fake):
        resp = await client.get("/api/v1/container")
    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "argus-rag-embedding-1"


async def test_restart_found(client):
    async def fake(args):
        if args[0] == "inspect":
            return (0, INSPECT_OK, "")
        return (0, "", "")

    with patch.object(service, "_run", side_effect=fake):
        resp = await client.post("/api/v1/container/argus-rag-embedding-1/restart")
    assert resp.status_code == 200


async def test_remove_found(client):
    async def fake(args):
        if args[0] == "inspect":
            return (0, INSPECT_OK, "")
        return (0, "", "")

    with patch.object(service, "_run", side_effect=fake):
        resp = await client.delete("/api/v1/container/argus-rag-embedding-1")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


async def test_remove_not_found(client):
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (1, "", "No such object")
        resp = await client.delete("/api/v1/container/argus-rag-embedding-9")
    assert resp.status_code == 404
