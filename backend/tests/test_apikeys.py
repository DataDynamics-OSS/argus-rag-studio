# SPDX-License-Identifier: Apache-2.0
"""API 키(서비스 계정) 순수 로직 테스트.

DB 가 필요한 발급/검증 흐름이 아니라, 키 생성·해시·헤더 추출 등 결정적 단위만 검증한다.
"""

import hashlib

from app.apikeys import service
from app.core import auth


class _Req:
    """request.headers 만 흉내내는 최소 더블."""

    def __init__(self, headers: dict[str, str]):
        self.headers = headers


def test_generate_key_format_and_hash():
    raw, prefix, key_hash = service._generate_key()
    assert raw.startswith(service.KEY_PREFIX)
    assert prefix == raw[:16]
    assert key_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert len(key_hash) == 64


def test_generate_key_is_unique():
    keys = {service._generate_key()[0] for _ in range(100)}
    assert len(keys) == 100


def test_hash_key_is_deterministic():
    raw = "argus_sk_example"
    assert service._hash_key(raw) == service._hash_key(raw)
    assert service._hash_key(raw) != service._hash_key("argus_sk_other")


def test_extract_api_key_from_dedicated_header():
    assert auth._extract_api_key(_Req({"X-API-Key": "argus_sk_abc"})) == "argus_sk_abc"


def test_extract_api_key_from_bearer_with_prefix():
    assert (
        auth._extract_api_key(_Req({"Authorization": "Bearer argus_sk_xyz"}))
        == "argus_sk_xyz"
    )


def test_extract_api_key_ignores_jwt_bearer():
    # 접두사가 없는 일반 JWT 는 API 키로 오인하지 않는다.
    assert auth._extract_api_key(_Req({"Authorization": "Bearer eyJhbGciOiJ"})) is None


def test_extract_api_key_none_when_absent():
    assert auth._extract_api_key(_Req({})) is None


def test_extract_api_key_prefers_dedicated_header():
    req = _Req({"X-API-Key": "argus_sk_header", "Authorization": "Bearer argus_sk_bearer"})
    assert auth._extract_api_key(req) == "argus_sk_header"
