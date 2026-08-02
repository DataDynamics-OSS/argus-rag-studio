# SPDX-License-Identifier: Apache-2.0
"""S3StorageBackend — S3 호환(MinIO/S3) 오브젝트 저장소 백엔드.

기존 ``app.storage.client`` 의 boto3 로직을 그대로 옮긴 것이다(동작 동일). boto3 클라이언트
싱글턴은 여전히 ``client._get_client()`` 를 공유한다 — 설정 변경 시 ``client._client=None`` 리셋과
annotations/imagerecog 의 직접 사용(raw boto3)이 같은 연결을 재사용하도록 보장한다.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from botocore.exceptions import ClientError

from app.core.config import settings
from app.storage.client import _get_client

logger = logging.getLogger(__name__)


def _delete_prefix(client, bucket: str, prefix: str) -> None:
    """prefix 하위 모든 객체를 삭제(폴더 삭제). 1000개씩 batch."""
    token = None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        resp = client.list_objects_v2(**kw)
        objs = [{"Key": o["Key"]} for o in resp.get("Contents", [])]
        for i in range(0, len(objs), 1000):
            client.delete_objects(Bucket=bucket, Delete={"Objects": objs[i : i + 1000]})
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break


class S3StorageBackend:
    # ── URI 규약 ──────────────────────────────────────────────────────────────
    def build_uri(self, key: str) -> str:
        return f"s3://{settings.os_bucket}/{key}"

    def parse_uri(self, source_uri: str) -> tuple[str, str]:
        parsed = urlparse(source_uri)
        if parsed.scheme == "s3":
            return parsed.netloc, parsed.path.lstrip("/")
        return settings.os_bucket, source_uri.lstrip("/")

    # ── RAG 코어 경로 ─────────────────────────────────────────────────────────
    async def ensure_bucket(self) -> None:
        def _ensure():
            client = _get_client()
            bucket = settings.os_bucket
            try:
                client.head_bucket(Bucket=bucket)
            except ClientError:
                client.create_bucket(Bucket=bucket)
                logger.info("오브젝트 스토리지 버킷 생성: %s", bucket)

        await asyncio.to_thread(_ensure)

    async def put_object(self, key: str, data: bytes, content_type: str | None = None) -> str:
        def _put():
            client = _get_client()
            extra = {"ContentType": content_type} if content_type else {}
            client.put_object(Bucket=settings.os_bucket, Key=key, Body=data, **extra)

        await asyncio.to_thread(_put)
        uri = self.build_uri(key)
        logger.info("오브젝트 업로드: %s (%d bytes)", uri, len(data))
        return uri

    async def copy_object(self, src_key: str, dst_key: str) -> None:
        def _copy():
            client = _get_client()
            client.copy_object(
                Bucket=settings.os_bucket,
                Key=dst_key,
                CopySource={"Bucket": settings.os_bucket, "Key": src_key},
            )

        await asyncio.to_thread(_copy)

    async def delete_object(self, key: str) -> None:
        await asyncio.to_thread(
            lambda: _get_client().delete_object(Bucket=settings.os_bucket, Key=key)
        )

    async def object_exists(self, key: str) -> bool:
        def _head() -> bool:
            try:
                _get_client().head_object(Bucket=settings.os_bucket, Key=key)
                return True
            except ClientError:
                return False

        return await asyncio.to_thread(_head)

    async def get_object(self, source_uri: str) -> bytes:
        bucket, key = self.parse_uri(source_uri)

        def _get():
            client = _get_client()
            resp = client.get_object(Bucket=bucket, Key=key)
            return resp["Body"].read()

        return await asyncio.to_thread(_get)

    # ── 파일 브라우저(관리) ────────────────────────────────────────────────────
    async def list_buckets(self) -> list[str]:
        def _list():
            resp = _get_client().list_buckets()
            return sorted(b["Name"] for b in resp.get("Buckets", []))

        return await asyncio.to_thread(_list)

    async def list_directory(self, prefix: str = "", bucket: str | None = None) -> dict:
        bucket = bucket or settings.os_bucket
        clean = prefix.strip("/")
        s3_prefix = f"{clean}/" if clean else ""

        def _list():
            return _get_client().list_objects_v2(Bucket=bucket, Prefix=s3_prefix, Delimiter="/")

        resp = await asyncio.to_thread(_list)

        folders = []
        for cp in resp.get("CommonPrefixes", []):
            fp = cp["Prefix"]
            name = fp.rstrip("/").rsplit("/", 1)[-1]
            folders.append({
                "key": "/" + fp.rstrip("/") + "/", "name": name,
                "owner": "", "group": "", "permissions": "",
            })

        files = []
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            if key == s3_prefix:
                continue
            name = key.rsplit("/", 1)[-1]
            if not name:
                continue
            files.append({
                "key": "/" + key, "name": name, "size": obj.get("Size", 0),
                "last_modified": obj["LastModified"].isoformat() if obj.get("LastModified") else "",
                "owner": "", "group": "", "permissions": "",
            })

        current_path = "/" + clean if clean else "/"
        logger.info("S3 목록 조회: bucket=%s prefix=%s folders=%d files=%d",
                    bucket, s3_prefix, len(folders), len(files))
        return {"folders": folders, "files": files, "current_path": current_path}

    async def presigned_download_url(self, path: str, bucket: str | None = None) -> str:
        bucket = bucket or settings.os_bucket
        key = path.lstrip("/")

        def _gen():
            return _get_client().generate_presigned_url(
                "get_object", Params={"Bucket": bucket, "Key": key},
                ExpiresIn=settings.os_presign_expiry,
            )

        return await asyncio.to_thread(_gen)

    async def read_object_by_path(
        self, path: str, bucket: str | None = None
    ) -> tuple[bytes, str | None]:
        bucket = bucket or settings.os_bucket
        key = path.lstrip("/")

        def _get():
            resp = _get_client().get_object(Bucket=bucket, Key=key)
            return resp["Body"].read(), resp.get("ContentType")

        return await asyncio.to_thread(_get)

    async def create_folder(self, path: str, bucket: str | None = None) -> None:
        bucket = bucket or settings.os_bucket
        key = path.strip("/") + "/"

        def _do():
            _get_client().put_object(Bucket=bucket, Key=key, Body=b"")

        await asyncio.to_thread(_do)

    async def upload_object(
        self, directory: str, filename: str, data: bytes,
        content_type: str | None = None, bucket: str | None = None,
    ) -> None:
        bucket = bucket or settings.os_bucket
        base = directory.strip("/")
        safe = filename.replace("/", "_").strip() or "file"
        key = (base + "/" if base else "") + safe

        def _do():
            extra = {"ContentType": content_type} if content_type else {}
            _get_client().put_object(Bucket=bucket, Key=key, Body=data, **extra)

        await asyncio.to_thread(_do)

    async def delete_paths(self, paths: list[str], bucket: str | None = None) -> None:
        bucket = bucket or settings.os_bucket

        def _do():
            client = _get_client()
            for p in paths:
                if p.endswith("/"):
                    _delete_prefix(client, bucket, p.lstrip("/"))
                else:
                    client.delete_object(Bucket=bucket, Key=p.lstrip("/"))

        await asyncio.to_thread(_do)

    async def rename_path(
        self, source: str, destination: str, bucket: str | None = None
    ) -> None:
        bucket = bucket or settings.os_bucket
        src = source.strip("/")
        dst = destination.strip("/")

        def _do():
            client = _get_client()
            # src 가 단일 객체인지 확인 → 아니면 폴더(프리픽스)로 취급
            is_file = True
            try:
                client.head_object(Bucket=bucket, Key=src)
            except ClientError:
                is_file = False

            if is_file:
                client.copy_object(Bucket=bucket, CopySource={"Bucket": bucket, "Key": src}, Key=dst)
                client.delete_object(Bucket=bucket, Key=src)
                return

            src_prefix, dst_prefix = src + "/", dst + "/"
            token = None
            while True:
                kw = {"Bucket": bucket, "Prefix": src_prefix}
                if token:
                    kw["ContinuationToken"] = token
                resp = client.list_objects_v2(**kw)
                for o in resp.get("Contents", []):
                    suffix = o["Key"][len(src_prefix):]
                    client.copy_object(
                        Bucket=bucket, CopySource={"Bucket": bucket, "Key": o["Key"]},
                        Key=dst_prefix + suffix,
                    )
                    client.delete_object(Bucket=bucket, Key=o["Key"])
                if resp.get("IsTruncated"):
                    token = resp.get("NextContinuationToken")
                else:
                    break

        await asyncio.to_thread(_do)
