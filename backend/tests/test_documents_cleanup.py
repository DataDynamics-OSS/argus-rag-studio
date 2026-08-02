# SPDX-License-Identifier: Apache-2.0
"""문서 삭제 시 내부 스냅샷 정리의 소유권 가드 테스트.

삭제 정리는 내부 버킷의 표준 키(collections/{cuuid}/{duuid}/…)에 **자기 uuid 가 있는**
오브젝트만 대상이다 — 외부 파이프라인(/ingestion/register)이 가리키는 원본은 우리가
소유하지 않으므로 지우면 안 된다(그 판별이 이 함수).
"""

from app.core.config import settings
from app.documents.service import internal_snapshot_key

DUUID = "27112ac7-714c-4c7b-b590-659cc1ea18e3"
CUUID = "954de6f5-5401-4e45-bff9-265ff114104c"


def test_internal_standard_key_is_owned():
    uri = f"s3://{settings.os_bucket}/collections/{CUUID}/{DUUID}/계약서.pdf"
    assert internal_snapshot_key(uri, DUUID) == f"collections/{CUUID}/{DUUID}/계약서.pdf"


def test_other_bucket_not_owned():
    uri = f"s3://other-bucket/collections/{CUUID}/{DUUID}/a.pdf"
    assert internal_snapshot_key(uri, DUUID) is None


def test_non_standard_key_not_owned():
    # 외부 파이프라인이 올린 원본(비표준 키) — register 문서의 source_uri.
    assert internal_snapshot_key(f"s3://{settings.os_bucket}/nifi/inbox/a.pdf", DUUID) is None


def test_other_document_uuid_not_owned():
    uri = f"s3://{settings.os_bucket}/collections/{CUUID}/다른-문서-uuid/a.pdf"
    assert internal_snapshot_key(uri, DUUID) is None


def test_missing_or_garbage_uri():
    assert internal_snapshot_key(None, DUUID) is None
    assert internal_snapshot_key("", DUUID) is None
