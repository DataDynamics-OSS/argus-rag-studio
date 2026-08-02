# SPDX-License-Identifier: Apache-2.0
"""오브젝트 스토리지 모듈 — 백엔드(S3 / UC Volumes) 위임 + boto3 클라이언트 싱글턴.

호출부(documents/ingestion/s3browse)는 이 모듈의 함수를 그대로 쓴다. 실제 구현은 설정
(object_storage.backend)에 따라 ``StorageBackend`` 로 위임된다(``app.storage.factory``).

boto3 클라이언트 싱글턴(``_get_client``)은 S3 백엔드와, raw boto3 를 직접 쓰는
annotations/imagerecog 모듈이 공유한다. 설정 변경 시 ``_client=None`` 으로 리셋한다.

스코프 메모: UC Volumes 백엔드는 RAG 코어 경로(put/get/exists/delete/copy)를 지원한다.
파일 브라우저 전용 일부 기능(presigned 등)은 UC Volumes 에서 NotImplementedError 다.
annotations/imagerecog 버킷은 이 단계에선 S3 전용이다(별도 raw boto3 사용).
"""

import logging

import boto3
from botocore.config import Config as BotoConfig

from app.core.config import settings
from app.storage.factory import get_storage_backend

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    """boto3 S3 클라이언트(lazy 싱글턴). MinIO 는 endpoint_url + path-style 로 접속.

    S3 백엔드 + annotations/imagerecog(raw boto3)가 공유한다."""
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=settings.os_endpoint,
            aws_access_key_id=settings.os_access_key,
            aws_secret_access_key=settings.os_secret_key,
            region_name=settings.os_region,
            use_ssl=settings.os_use_ssl,
            # MinIO 미가용 시 빠르게 실패하도록 짧은 타임아웃 + 재시도 1회.
            # (기본값은 연결 재시도로 ~11초 블로킹 → 기동/업로드가 오래 멈춤)
            config=BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                connect_timeout=3,
                read_timeout=5,
                retries={"max_attempts": 1},
            ),
        )
    return _client


def build_object_key(collection_uuid: str, document_uuid: str, filename: str) -> str:
    """오브젝트 키 규칙: ``collections/{collection_uuid}/{document_uuid}/{filename}``.

    백엔드 무관(순수 경로 규칙). 컬렉션 식별자는 외부 노출 UUID 를 쓴다.
    """
    safe_name = filename.replace("/", "_").strip() or "file"
    return f"collections/{collection_uuid}/{document_uuid}/{safe_name}"


def build_source_uri(key: str) -> str:
    return get_storage_backend().build_uri(key)


def parse_source_uri(source_uri: str) -> tuple[str, str]:
    return get_storage_backend().parse_uri(source_uri)


# ── 백엔드 위임(비동기) ───────────────────────────────────────────────────────


async def ensure_bucket() -> None:
    await get_storage_backend().ensure_bucket()


async def ensure_models_bucket() -> None:
    """모델 저장소(Model Repository) 버킷 보장 — 보유 확인·서버 팩 업로드가 사용.

    S3 계열 전용(직접 클라이언트) — 모델 팩은 문서 백엔드 추상화와 무관하게 S3 를 쓴다."""
    import asyncio

    from botocore.exceptions import ClientError

    from app.core.config import settings

    def _do() -> None:
        c = _get_client()
        try:
            c.head_bucket(Bucket=settings.os_models_bucket)
        except ClientError:
            c.create_bucket(Bucket=settings.os_models_bucket)

    await asyncio.to_thread(_do)


async def put_object(key: str, data: bytes, content_type: str | None = None) -> str:
    return await get_storage_backend().put_object(key, data, content_type)


async def copy_object(src_key: str, dst_key: str) -> None:
    await get_storage_backend().copy_object(src_key, dst_key)


async def delete_object(key: str) -> None:
    await get_storage_backend().delete_object(key)


async def object_exists(key: str) -> bool:
    return await get_storage_backend().object_exists(key)


async def get_object(source_uri: str) -> bytes:
    return await get_storage_backend().get_object(source_uri)


# ── 파일 브라우저(스토리지 관리) ──────────────────────────────────────────────


async def list_buckets() -> list[str]:
    return await get_storage_backend().list_buckets()


async def list_directory(prefix: str = "", bucket: str | None = None) -> dict:
    return await get_storage_backend().list_directory(prefix, bucket)


async def presigned_download_url(path: str, bucket: str | None = None) -> str:
    return await get_storage_backend().presigned_download_url(path, bucket)


async def read_object_by_path(path: str, bucket: str | None = None) -> tuple[bytes, str | None]:
    return await get_storage_backend().read_object_by_path(path, bucket)


async def create_folder(path: str, bucket: str | None = None) -> None:
    await get_storage_backend().create_folder(path, bucket)


async def upload_object(
    directory: str, filename: str, data: bytes, content_type: str | None = None,
    bucket: str | None = None,
) -> None:
    await get_storage_backend().upload_object(directory, filename, data, content_type, bucket)


async def delete_paths(paths: list[str], bucket: str | None = None) -> None:
    await get_storage_backend().delete_paths(paths, bucket)


async def rename_path(source: str, destination: str, bucket: str | None = None) -> None:
    await get_storage_backend().rename_path(source, destination, bucket)
