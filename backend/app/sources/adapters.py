# SPDX-License-Identifier: Apache-2.0
"""소스 어댑터 — 등록된 스토리지 소스(S3·NAS)에 대한 **읽기 전용** 접근.

내부 저장소의 ``StorageBackend``(put/copy/presigned…)와 달리 소스는 원본을 읽어오기만 하므로
``stat / read / list`` 3메서드로 좁게 정의한다. 새 kind 추가 = 어댑터 클래스 1개 +
``_ADAPTERS`` 등록(라우팅 Router 레지스트리와 동형).

경로 규약: 소스 내 상대 경로, 구분자 ``/``, 선행 ``/`` 없음. ``normalize_source_path`` 가
``..`` 세그먼트를 거부하고(NAS 는 추가로 realpath 가 마운트 루트 하위인지 검사 — 심링크 이탈
차단), 모든 진입점(API·인테이크)이 이 함수를 거친다.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

# list() 가 반환하는 최대 항목 수 — 폭주 방지(초과분은 truncated=True 로 알린다).
MAX_LIST_ENTRIES = 1000


class SourcePathError(ValueError):
    """경로 규약 위반(빈 경로·traversal·마운트 루트 이탈)."""


class SourceObjectNotFound(FileNotFoundError):
    """소스에 해당 경로의 객체/파일이 없음."""


def normalize_source_path(path: str, allow_empty: bool = False) -> str:
    """소스 내 경로 정규화 — ``\\``→``/``, 선행 ``/``·``.`` 세그먼트 제거, ``..`` 거부."""
    p = (path or "").replace("\\", "/").strip().lstrip("/")
    parts = [seg for seg in p.split("/") if seg not in ("", ".")]
    if any(seg == ".." for seg in parts):
        raise SourcePathError("상위 디렉터리 참조(..)는 허용되지 않습니다.")
    if not parts:
        if allow_empty:
            return ""
        raise SourcePathError("경로가 비어 있습니다.")
    return "/".join(parts)


@dataclass
class SourceStat:
    size: int
    mtime: datetime | None = None


@dataclass
class SourceEntry:
    path: str          # 소스 내 상대 경로(base_prefix 제외)
    name: str
    is_dir: bool
    size: int = 0
    mtime: datetime | None = None


@dataclass
class SourceListing:
    entries: list[SourceEntry]
    truncated: bool = False  # MAX_LIST_ENTRIES 로 잘렸는지


@runtime_checkable
class SourceAdapter(Protocol):
    """읽기 전용 소스 접근. 모든 메서드는 비동기(블로킹 I/O 는 to_thread)."""

    async def stat(self, path: str) -> SourceStat:
        """파일 크기/수정시각(read 전 크기 상한 검사용). 없으면 SourceObjectNotFound."""

    async def read(self, path: str) -> bytes:
        """원본 바이트를 읽어 반환. 없으면 SourceObjectNotFound."""

    async def list(self, prefix: str = "", recursive: bool = False) -> SourceListing:
        """prefix 하위 항목 열거(파일+디렉터리). recursive=True 면 파일만 평탄 열거."""


# ---------------------------------------------------------------------------
# S3 호환 소스 — 소스별 엔드포인트/자격증명(내부 저장소 boto3 싱글턴과 별개)
# ---------------------------------------------------------------------------

class S3SourceAdapter:
    """S3 호환(MinIO/S3) 소스. config: endpoint/bucket/base_prefix/region, secret: access/secret key."""

    def __init__(self, config: dict, secret: dict | None = None):
        self._endpoint = (config.get("endpoint") or "").strip() or None
        self._bucket = (config.get("bucket") or "").strip()
        self._base = normalize_source_path(config.get("base_prefix") or "", allow_empty=True)
        self._region = (config.get("region") or "").strip() or None
        secret = secret or {}
        self._access_key = secret.get("access_key")
        self._secret_key = secret.get("secret_key")
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                region_name=self._region,
                # 내부 저장소 클라이언트와 동일 — 미가용 소스에서 빠르게 실패.
                config=BotoConfig(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                    connect_timeout=3,
                    read_timeout=10,
                    retries={"max_attempts": 1},
                ),
            )
        return self._client

    def _key(self, path: str) -> str:
        return f"{self._base}/{path}" if self._base else path

    def _rel(self, key: str) -> str:
        return key[len(self._base) + 1:] if self._base and key.startswith(self._base + "/") else key

    async def stat(self, path: str) -> SourceStat:
        key = self._key(normalize_source_path(path))

        def _head() -> SourceStat:
            try:
                resp = self._get_client().head_object(Bucket=self._bucket, Key=key)
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                    raise SourceObjectNotFound(path) from e
                raise
            return SourceStat(size=int(resp.get("ContentLength", 0)), mtime=resp.get("LastModified"))

        return await asyncio.to_thread(_head)

    async def read(self, path: str) -> bytes:
        key = self._key(normalize_source_path(path))

        def _get() -> bytes:
            try:
                resp = self._get_client().get_object(Bucket=self._bucket, Key=key)
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                    raise SourceObjectNotFound(path) from e
                raise
            return resp["Body"].read()

        return await asyncio.to_thread(_get)

    async def list(self, prefix: str = "", recursive: bool = False) -> SourceListing:
        norm = normalize_source_path(prefix, allow_empty=True)
        key_prefix = self._key(norm)
        if key_prefix and not key_prefix.endswith("/"):
            key_prefix += "/"

        def _list() -> SourceListing:
            client = self._get_client()
            entries: list[SourceEntry] = []
            token = None
            truncated = False
            while True:
                kw: dict = {"Bucket": self._bucket, "Prefix": key_prefix,
                            "MaxKeys": min(1000, MAX_LIST_ENTRIES + 1)}
                if not recursive:
                    kw["Delimiter"] = "/"
                if token:
                    kw["ContinuationToken"] = token
                resp = client.list_objects_v2(**kw)
                for cp in resp.get("CommonPrefixes", []):
                    rel = self._rel(cp["Prefix"].rstrip("/"))
                    entries.append(SourceEntry(path=rel, name=rel.rsplit("/", 1)[-1], is_dir=True))
                for obj in resp.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith("/"):  # 폴더 마커 객체는 제외
                        continue
                    rel = self._rel(key)
                    entries.append(SourceEntry(
                        path=rel, name=rel.rsplit("/", 1)[-1], is_dir=False,
                        size=int(obj.get("Size", 0)), mtime=obj.get("LastModified"),
                    ))
                if len(entries) > MAX_LIST_ENTRIES:
                    del entries[MAX_LIST_ENTRIES:]
                    truncated = True
                    break
                if resp.get("IsTruncated"):
                    token = resp.get("NextContinuationToken")
                else:
                    break
            entries.sort(key=lambda e: (not e.is_dir, e.path))
            return SourceListing(entries=entries, truncated=truncated)

        return await asyncio.to_thread(_list)


# ---------------------------------------------------------------------------
# NAS(마운트) 소스 — 호스트에 NFS/SMB 마운트를 걸고 마운트 루트만 등록
# ---------------------------------------------------------------------------

class NasSourceAdapter:
    """NAS(로컬 마운트) 소스. config: mount_path/base_prefix. 자격증명은 마운트가 대신한다."""

    def __init__(self, config: dict, secret: dict | None = None):
        mount = (config.get("mount_path") or "").strip()
        if not mount or not os.path.isabs(mount):
            raise SourcePathError("mount_path 는 절대 경로여야 합니다.")
        base = normalize_source_path(config.get("base_prefix") or "", allow_empty=True)
        self._root = os.path.realpath(os.path.join(mount, base) if base else mount)

    def _resolve(self, path: str) -> str:
        """상대 경로 → 실제 경로. realpath 가 루트 하위가 아니면(심링크 이탈 포함) 거부."""
        full = os.path.realpath(os.path.join(self._root, path))
        if full != self._root and not full.startswith(self._root + os.sep):
            raise SourcePathError("마운트 루트를 벗어나는 경로입니다.")
        return full

    async def stat(self, path: str) -> SourceStat:
        full = self._resolve(normalize_source_path(path))

        def _stat() -> SourceStat:
            try:
                st = os.stat(full)
            except FileNotFoundError as e:
                raise SourceObjectNotFound(path) from e
            if not os.path.isfile(full):
                raise SourceObjectNotFound(path)
            return SourceStat(size=st.st_size, mtime=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc))

        return await asyncio.to_thread(_stat)

    async def read(self, path: str) -> bytes:
        full = self._resolve(normalize_source_path(path))

        def _read() -> bytes:
            try:
                with open(full, "rb") as f:
                    return f.read()
            except (FileNotFoundError, IsADirectoryError) as e:
                raise SourceObjectNotFound(path) from e

        return await asyncio.to_thread(_read)

    async def list(self, prefix: str = "", recursive: bool = False) -> SourceListing:
        norm = normalize_source_path(prefix, allow_empty=True)
        base = self._resolve(norm) if norm else self._root

        def _entry(rel: str, full: str, is_dir: bool) -> SourceEntry:
            st = os.stat(full)
            return SourceEntry(
                path=rel, name=rel.rsplit("/", 1)[-1], is_dir=is_dir,
                size=0 if is_dir else st.st_size,
                mtime=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
            )

        def _list() -> SourceListing:
            if not os.path.isdir(base):
                raise SourceObjectNotFound(prefix)
            entries: list[SourceEntry] = []
            truncated = False
            if recursive:
                for dirpath, _dirs, files in os.walk(base):
                    for fn in files:
                        full = os.path.join(dirpath, fn)
                        rel = os.path.relpath(full, self._root).replace(os.sep, "/")
                        entries.append(_entry(rel, full, is_dir=False))
                        if len(entries) >= MAX_LIST_ENTRIES:
                            truncated = True
                            break
                    if truncated:
                        break
            else:
                with os.scandir(base) as it:
                    for de in it:
                        rel = os.path.relpath(de.path, self._root).replace(os.sep, "/")
                        entries.append(_entry(rel, de.path, is_dir=de.is_dir()))
                        if len(entries) >= MAX_LIST_ENTRIES:
                            truncated = True
                            break
            entries.sort(key=lambda e: (not e.is_dir, e.path))
            return SourceListing(entries=entries, truncated=truncated)

        return await asyncio.to_thread(_list)


# ---------------------------------------------------------------------------
# 팩토리 — kind 별 어댑터(새 kind = 클래스 1개 + 여기 1줄)
# ---------------------------------------------------------------------------

_ADAPTERS: dict[str, type] = {
    "s3": S3SourceAdapter,
    "nas": NasSourceAdapter,
}

SOURCE_KINDS = tuple(_ADAPTERS.keys())


def get_source_adapter(kind: str, config: dict, secret: dict | None = None) -> SourceAdapter:
    cls = _ADAPTERS.get(kind)
    if cls is None:
        raise ValueError(f"지원하지 않는 소스 종류: {kind}")
    return cls(config, secret)
