# SPDX-License-Identifier: Apache-2.0
"""DatabricksVectorStore(Mosaic AI Vector Search) 어댑터 테스트.

실제 Databricks workspace 없이, ``databricks.vector_search.client`` 모듈을 가짜로 주입해
어댑터의 인덱스 이름 규약·업서트 페이로드·검색 응답 파싱·문서 단위 삭제(Postgres 조회→PK 삭제)를
검증한다. SDK 는 동기지만 어댑터가 asyncio.to_thread 로 감싸므로 호출 결과만 확인하면 충분하다.
"""

import sys
import types

import pytest

from app.vectorstore.base import CollectionSpec, VectorItem


# ── 가짜 Mosaic SDK ─────────────────────────────────────────────────────────
class FakeIndex:
    def __init__(self, exists: bool = True):
        self._exists = exists
        self.upserted: list[dict] = []
        self.deleted: list[str] = []
        self.search_kw: dict | None = None
        self.search_result = {"result": {"data_array": [["uuid-1", 0.9], ["uuid-2", 0.5]]}}

    def describe(self):
        if not self._exists:
            raise RuntimeError("index not found")
        return {"status": {"detailed_state": "ONLINE"}}

    def upsert(self, rows):
        self.upserted.extend(rows)

    def delete(self, primary_keys):
        self.deleted.extend(primary_keys)

    def similarity_search(self, **kw):
        self.search_kw = kw
        return self.search_result


class FakeClient:
    last: "FakeClient | None" = None

    def __init__(self, **kw):
        self.init_kw = kw
        self.created: list[dict] = []
        self.deleted_indexes: list[str] = []
        self.index = FakeIndex(exists=True)
        FakeClient.last = self

    def get_index(self, endpoint_name=None, index_name=None):
        return self.index

    def create_direct_access_index(self, **kw):
        self.created.append(kw)
        self.index = FakeIndex(exists=True)

    def delete_index(self, endpoint_name=None, index_name=None):
        self.deleted_indexes.append(index_name)


@pytest.fixture(autouse=True)
def _fake_sdk(monkeypatch):
    """``from databricks.vector_search.client import VectorSearchClient`` 가 FakeClient 를 주도록 주입."""
    pkg = types.ModuleType("databricks")
    sub = types.ModuleType("databricks.vector_search")
    client_mod = types.ModuleType("databricks.vector_search.client")
    client_mod.VectorSearchClient = FakeClient
    monkeypatch.setitem(sys.modules, "databricks", pkg)
    monkeypatch.setitem(sys.modules, "databricks.vector_search", sub)
    monkeypatch.setitem(sys.modules, "databricks.vector_search.client", client_mod)
    FakeClient.last = None
    yield


def _store():
    from app.vectorstore.databricks_store import DatabricksVectorStore

    return DatabricksVectorStore(
        host="https://dbc-x.cloud.databricks.com",
        token="dapi-xxx",
        endpoint="argus-vs",
        catalog="main",
        schema="argus",
        prefix="argus",
    )


# ── 가짜 Postgres 세션(문서 단위 삭제용) ─────────────────────────────────────
class _FakeScalars:
    def __init__(self, vals):
        self._v = vals

    def all(self):
        return self._v


class _FakeResult:
    def __init__(self, vals):
        self._v = vals

    def scalars(self):
        return _FakeScalars(self._v)


class _FakeSession:
    def __init__(self, vals):
        self._v = vals

    async def execute(self, _stmt):
        return _FakeResult(self._v)


# ── 검증 ─────────────────────────────────────────────────────────────────────
def test_requires_host_token_endpoint():
    from app.vectorstore.databricks_store import DatabricksVectorStore

    for kw in (
        dict(host="", token="t", endpoint="e"),
        dict(host="h", token="", endpoint="e"),
        dict(host="h", token="t", endpoint=""),
    ):
        with pytest.raises(ValueError):
            DatabricksVectorStore(catalog="main", schema="argus", prefix="argus", **kw)


def test_index_name_is_three_level_uc():
    assert _store()._index_name(12) == "main.argus.argus_c12"


@pytest.mark.asyncio
async def test_ensure_creates_index_when_absent():
    store = _store()
    FakeClient.last.index = FakeIndex(exists=False)  # describe() 가 실패 → 생성 경로
    await store.ensure_collection(None, CollectionSpec(collection_id=7, dim=1024, metric="cosine"))
    created = FakeClient.last.created
    assert len(created) == 1
    assert created[0]["index_name"] == "main.argus.argus_c7"
    assert created[0]["primary_key"] == "chunk_id"
    assert created[0]["embedding_dimension"] == 1024


@pytest.mark.asyncio
async def test_ensure_skips_when_present():
    store = _store()  # 기본 FakeIndex(exists=True)
    await store.ensure_collection(None, CollectionSpec(collection_id=7, dim=1024))
    assert FakeClient.last.created == []  # 이미 존재 → 생성 안 함


@pytest.mark.asyncio
async def test_upsert_maps_payload_to_columns():
    store = _store()
    items = [
        VectorItem(chunk_id="uuid-a", vector=[0.1, 0.2], payload={"document_id": 3, "status": "indexed", "seq": 5}),
    ]
    await store.upsert(None, 1, items)
    rows = FakeClient.last.index.upserted
    assert rows == [
        {"chunk_id": "uuid-a", "embedding": [0.1, 0.2], "document_id": 3, "status": "indexed", "seq": 5}
    ]


@pytest.mark.asyncio
async def test_search_parses_hits():
    store = _store()
    hits = await store.search(None, CollectionSpec(collection_id=1, dim=2), [0.1, 0.2], k=2, filters={"document_id": 3})
    assert [(h.chunk_id, h.score) for h in hits] == [("uuid-1", 0.9), ("uuid-2", 0.5)]
    # 필터·결과 컬럼이 SDK 로 전달됐는지
    kw = FakeClient.last.index.search_kw
    assert kw["filters"] == {"document_id": 3}
    assert kw["columns"] == ["chunk_id"]
    assert kw["num_results"] == 2


@pytest.mark.asyncio
async def test_delete_by_document_uses_postgres_pks():
    store = _store()
    session = _FakeSession(["uuid-1", "uuid-2"])  # Postgres 가 돌려줄 chunk UUID
    await store.delete_by_document(session, 1, document_id=99)
    assert FakeClient.last.index.deleted == ["uuid-1", "uuid-2"]


@pytest.mark.asyncio
async def test_delete_by_document_noop_when_empty():
    store = _store()
    await store.delete_by_document(_FakeSession([]), 1, document_id=99)
    assert FakeClient.last.index.deleted == []


@pytest.mark.asyncio
async def test_drop_collection_deletes_index():
    store = _store()
    await store.drop_collection(None, 5)
    assert FakeClient.last.deleted_indexes == ["main.argus.argus_c5"]


def test_parse_hits_handles_empty():
    from app.vectorstore.databricks_store import _parse_hits

    assert _parse_hits({}) == []
    assert _parse_hits({"result": {"data_array": []}}) == []
    assert _parse_hits({"result": {}}) == []


def test_factory_builds_databricks_store():
    from app.core.config import settings
    from app.vectorstore.databricks_store import DatabricksVectorStore
    from app.vectorstore.factory import get_vector_store, reset_vector_store

    saved = (
        settings.vector_store_provider, settings.databricks_host,
        settings.databricks_token, settings.vector_store_databricks_endpoint,
    )
    try:
        settings.vector_store_provider = "databricks"
        settings.databricks_host = "https://dbc.cloud.databricks.com"
        settings.databricks_token = "dapi-x"
        settings.vector_store_databricks_endpoint = "argus-vs"
        reset_vector_store()
        assert isinstance(get_vector_store(), DatabricksVectorStore)
    finally:
        (
            settings.vector_store_provider, settings.databricks_host,
            settings.databricks_token, settings.vector_store_databricks_endpoint,
        ) = saved
        reset_vector_store()
