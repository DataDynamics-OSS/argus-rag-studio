# SPDX-License-Identifier: Apache-2.0
"""기반 환경(Platform Profile) 어댑터 테스트.

StandardProfile = 현행 동작(쿼리/문서 원문 그대로), DatabricksProfile = 쿼리 instruction
비대칭. 팩토리가 settings(platform.base / embedding.query_instruction)에 따라 올바른
프로파일을 캐시·재생성하는지, 그리고 임베딩 서비스가 쿼리/문서를 다르게 전처리하는지 검증한다.
"""

import pytest

from app.core.config import settings
from app.platform import factory
from app.platform.profile import DatabricksProfile, StandardProfile


@pytest.fixture(autouse=True)
def _restore_platform(monkeypatch):
    """각 테스트 후 프로파일 캐시와 관련 설정을 원복(전역 오염 방지)."""
    base0 = settings.platform_base
    instr0 = settings.embedding_query_instruction
    yield
    settings.platform_base = base0
    settings.embedding_query_instruction = instr0
    factory.reset_platform_profile()


# ── 프로파일 단위 ───────────────────────────────────────────────────────────

def test_standard_profile_is_identity():
    p = StandardProfile()
    assert p.embedding_query_text("서울 날씨") == "서울 날씨"
    assert p.embedding_doc_text("서울 날씨") == "서울 날씨"
    assert p.embedding_endpoint_url("http://x:8080/v1", "bge-m3") == "http://x:8080/v1/embeddings"
    assert p.llm_endpoint_url("http://x:8080/v1") == "http://x:8080/v1/chat/completions"
    assert p.embedding_defaults() == {}


def test_databricks_profile_query_instruction_asymmetry():
    p = DatabricksProfile()
    q = p.embedding_query_text("서울 날씨")
    assert q.endswith("서울 날씨")
    assert q != "서울 날씨"  # 쿼리엔 지시문 부착
    assert q.startswith(DatabricksProfile.DEFAULT_QUERY_INSTRUCTION)
    # 문서는 원문 그대로(비대칭)
    assert p.embedding_doc_text("서울 날씨") == "서울 날씨"


def test_databricks_profile_custom_instruction_verbatim():
    p = DatabricksProfile(query_instruction="질의: ")
    assert p.embedding_query_text("hi") == "질의: hi"


def test_databricks_profile_empty_instruction_falls_back_to_default():
    p = DatabricksProfile(query_instruction="")
    assert p.embedding_query_text("hi").startswith(DatabricksProfile.DEFAULT_QUERY_INSTRUCTION)


def test_databricks_profile_embedding_defaults():
    d = DatabricksProfile().embedding_defaults()
    assert d["model"] == "Qwen/Qwen3-Embedding-0.6B"
    assert d["dim"] == 1024  # bge-m3 와 동일 차원 → 스키마 변경 불필요
    assert d["metric"] == "cosine"


# ── 팩토리 ──────────────────────────────────────────────────────────────────

def test_factory_default_is_standard():
    settings.platform_base = "standard"
    factory.reset_platform_profile()
    assert isinstance(factory.get_platform_profile(), StandardProfile)


def test_factory_switches_to_databricks():
    settings.platform_base = "databricks"
    factory.reset_platform_profile()
    assert isinstance(factory.get_platform_profile(), DatabricksProfile)


def test_factory_caches_instance():
    settings.platform_base = "standard"
    factory.reset_platform_profile()
    assert factory.get_platform_profile() is factory.get_platform_profile()


def test_factory_rebuilds_when_instruction_changes():
    settings.platform_base = "databricks"
    settings.embedding_query_instruction = ""
    factory.reset_platform_profile()
    p1 = factory.get_platform_profile()
    # 쿼리 instruction 설정만 바꿔도(reset 없이) 캐시 키가 달라져 재생성된다.
    settings.embedding_query_instruction = "질의: "
    p2 = factory.get_platform_profile()
    assert p1 is not p2
    assert p2.embedding_query_text("x") == "질의: x"


# ── 임베딩 서비스 통합(hash 프로바이더 — 외부 서버 불필요) ─────────────────────

@pytest.mark.asyncio
async def test_embed_texts_query_doc_diverge_on_databricks():
    """databricks 프로파일에선 같은 텍스트라도 쿼리/문서 전처리가 달라 벡터가 갈린다."""
    settings.platform_base = "databricks"
    settings.embedding_query_instruction = ""
    factory.reset_platform_profile()
    from app.embedding.service import embed_texts, shutdown_providers

    kw = dict(provider="hash", server_url=None, model="hash", dim=64)
    q = await embed_texts(["서울 날씨"], is_query=True, **kw)
    d = await embed_texts(["서울 날씨"], is_query=False, **kw)
    assert q[0] != d[0]
    await shutdown_providers()


@pytest.mark.asyncio
async def test_embed_texts_query_doc_identical_on_standard():
    """standard 프로파일에선 쿼리/문서 전처리가 동일해 벡터가 같다(현행 동작 유지)."""
    settings.platform_base = "standard"
    factory.reset_platform_profile()
    from app.embedding.service import embed_texts, shutdown_providers

    kw = dict(provider="hash", server_url=None, model="hash", dim=64)
    q = await embed_texts(["서울 날씨"], is_query=True, **kw)
    d = await embed_texts(["서울 날씨"], is_query=False, **kw)
    assert q[0] == d[0]
    await shutdown_providers()
