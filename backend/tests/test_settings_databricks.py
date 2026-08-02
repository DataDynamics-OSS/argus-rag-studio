# SPDX-License-Identifier: Apache-2.0
"""기반 환경 Databricks 연결 테스트(service.test_databricks).

httpx 를 가짜로 주입해 인증 성공/실패와 입력 검증 분기를 검증한다(실제 workspace 불필요)."""

import httpx
import pytest

from app.core.config import settings
from app.settings import service


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp
        self.requested_url = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        self.requested_url = url
        return self._resp


@pytest.fixture
def _restore():
    saved = (settings.databricks_host, settings.databricks_token)
    yield
    settings.databricks_host, settings.databricks_token = saved


@pytest.mark.asyncio
async def test_empty_host(_restore):
    settings.databricks_host = ""
    r = await service.test_databricks({"token": "t"})
    assert r["ok"] is False and "Host" in r["message"]


@pytest.mark.asyncio
async def test_empty_token(_restore):
    settings.databricks_token = ""
    r = await service.test_databricks({"host": "https://dbc.example.com"})
    assert r["ok"] is False and "토큰" in r["message"]


@pytest.mark.asyncio
async def test_success(monkeypatch, _restore):
    captured = {}

    def _factory(*a, **kw):
        c = _FakeClient(_FakeResp(200, {"userName": "alice@x.com"}))
        captured["client"] = c
        return c

    monkeypatch.setattr(httpx, "AsyncClient", _factory)
    r = await service.test_databricks({"host": "dbc.example.com", "token": "dapi-x"})
    assert r["ok"] is True
    assert "alice@x.com" in r["message"]
    # 스킴 없는 host 는 https 로 보정되고 SCIM Me 를 호출
    assert captured["client"].requested_url == "https://dbc.example.com/api/2.0/preview/scim/v2/Me"


@pytest.mark.asyncio
async def test_auth_failure(monkeypatch, _restore):
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _FakeClient(_FakeResp(403)))
    r = await service.test_databricks({"host": "https://dbc.example.com", "token": "bad"})
    assert r["ok"] is False and "인증 실패" in r["message"]
