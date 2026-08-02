# SPDX-License-Identifier: Apache-2.0
"""StorageBackend 팩토리 — 설정(object_storage.backend)에 따라 백엔드 선택(캐시).

설정 변경 시 ``reset_storage_backend()`` 로 캐시를 무효화한다(vectorstore/factory 와 동일 패턴).
``s3``(기본) | ``uc_volumes``(Databricks Unity Catalog Volumes). UC 인증은 기반 환경의
databricks_host/token 을 재사용한다.
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.storage.base import StorageBackend

logger = logging.getLogger(__name__)

_backend: StorageBackend | None = None
_backend_key: tuple | None = None


def _current_key() -> tuple:
    return (
        (settings.storage_backend or "s3").lower(),
        settings.databricks_host,
        settings.storage_databricks_catalog,
        settings.storage_databricks_schema,
        settings.storage_databricks_volume,
    )


def reset_storage_backend() -> None:
    """캐시 무효화 — 설정 변경 후 호출하면 다음 get_storage_backend() 가 새 설정으로 생성."""
    global _backend, _backend_key
    _backend = None
    _backend_key = None


def get_storage_backend() -> StorageBackend:
    """현재 설정의 StorageBackend 인스턴스를 반환한다(backend/위치 바뀌면 자동 재생성)."""
    global _backend, _backend_key
    key = _current_key()
    if _backend is not None and _backend_key == key:
        return _backend

    kind = key[0]
    if kind in ("uc_volumes", "uc", "databricks", "volumes"):
        from app.storage.uc_volumes_backend import UCVolumesStorageBackend
        _backend = UCVolumesStorageBackend(
            host=settings.databricks_host,
            token=settings.databricks_token,
            catalog=settings.storage_databricks_catalog,
            schema=settings.storage_databricks_schema,
            volume=settings.storage_databricks_volume,
        )
        kind = "uc_volumes"
    else:
        from app.storage.s3_backend import S3StorageBackend
        _backend = S3StorageBackend()
        kind = "s3"
    _backend_key = key
    logger.info("StorageBackend=%s", kind)
    return _backend
