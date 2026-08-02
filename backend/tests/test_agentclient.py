# SPDX-License-Identifier: Apache-2.0
"""AgentClient 테스트 — httpx MockTransport 로 재시도/에러 정규화 검증."""

import httpx
import pytest

from app.agentclient import AgentClient, AgentError


def _client(handler, **kw):
    return AgentClient(
        ip="192.0.2.10",
        port=4501,
        transport=httpx.MockTransport(handler),
        **kw,
    )


# ---------------------------------------------------------------------------
# 정상 응답
# ---------------------------------------------------------------------------


async def test_create_service_returns_json():
    def handler(request):
        assert request.method == "POST"
        assert str(request.url).endswith("/api/v1/service")
        return httpx.Response(200, json={"name": "argus-rag-worker-1", "active_state": "active"})

    data = await _client(handler).create_service({"name": "argus-rag-worker-1"})
    assert data["name"] == "argus-rag-worker-1"


async def test_list_services_returns_list():
    def handler(request):
        return httpx.Response(200, json=[{"name": "argus-rag-worker-1"}])

    data = await _client(handler).list_services()
    assert data == [{"name": "argus-rag-worker-1"}]


async def test_remove_service_empty_body():
    def handler(request):
        return httpx.Response(204)

    assert await _client(handler).remove_service("argus-rag-worker-1") is None


async def test_token_header_sent():
    seen = {}

    def handler(request):
        seen["token"] = request.headers.get("X-Agent-Token")
        return httpx.Response(200, json=[])

    await _client(handler, token="secret").list_services()
    assert seen["token"] == "secret"


async def test_no_token_header_when_absent():
    seen = {}

    def handler(request):
        seen["has"] = "X-Agent-Token" in request.headers
        return httpx.Response(200, json=[])

    await _client(handler).list_services()
    assert seen["has"] is False


# ---------------------------------------------------------------------------
# 4xx — 즉시 실패(재시도 없음)
# ---------------------------------------------------------------------------


async def test_4xx_raises_without_retry():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404, json={"detail": "service not found"})

    with pytest.raises(AgentError) as ei:
        await _client(handler).get_service("argus-rag-worker-9")

    assert ei.value.status_code == 404
    assert "service not found" in ei.value.message
    assert calls["n"] == 1  # 재시도 없음


# ---------------------------------------------------------------------------
# 5xx / 연결 오류 — 재시도 후 실패
# ---------------------------------------------------------------------------


async def test_5xx_retries_then_raises():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503, text="unavailable")

    with pytest.raises(AgentError) as ei:
        await _client(handler, retries=2).list_services()

    assert ei.value.status_code == 503
    assert calls["n"] == 3  # 최초 1 + 재시도 2


async def test_transport_error_retries_then_raises():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(AgentError) as ei:
        await _client(handler, retries=1).list_services()

    assert "연결 실패" in ei.value.message
    assert calls["n"] == 2  # 최초 1 + 재시도 1


async def test_5xx_then_success_recovers():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=[{"name": "argus-rag-worker-1"}])

    data = await _client(handler, retries=2).list_services()
    assert data == [{"name": "argus-rag-worker-1"}]
    assert calls["n"] == 2
