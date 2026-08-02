# SPDX-License-Identifier: Apache-2.0
"""UCVolumesStorageBackend — Databricks Unity Catalog Volumes 오브젝트 저장소 백엔드.

요구: ``pip install databricks-sdk`` + Databricks workspace(PAT 토큰) + 사전 생성된 Volume.
인증은 기반 환경(databricks_host/token)을 재사용한다. 파일은 Files API 로 접근하며 경로는
``/Volumes/{catalog}/{schema}/{volume}/{key}`` 형식이다.

스코프
------
RAG 코어 경로(put/get/exists/delete/copy)와 단순 파일 작업(read_by_path/upload/mkdir/delete)을
지원한다. presigned URL·rename 은 Volumes 에 대응 개념이 없어 NotImplementedError 다(파일 브라우저는
앱 프록시(read_object_by_path)로 다운로드를 대신할 수 있다). SDK 는 동기라 to_thread 로 감싼다.

전환 메모: 기존 문서의 source_uri 는 이전 백엔드 스킴(예: s3://)일 수 있다 — 스토리지 백엔드를
바꿔도 기존 객체는 이동하지 않으므로, 전환 후에는 재인제스천이 필요하다(벡터 스토어와 동일 원칙).
"""

from __future__ import annotations

import asyncio
import io
import logging

logger = logging.getLogger(__name__)

_URI_SCHEME = "dbfs:"  # source_uri = dbfs:/Volumes/{catalog}/{schema}/{volume}/{key}


class UCVolumesStorageBackend:
    def __init__(self, *, host: str, token: str, catalog: str, schema: str, volume: str):
        if not host:
            raise ValueError("Databricks Host(databricks.host)가 설정되지 않았습니다.")
        if not token:
            raise ValueError("Databricks PAT 토큰(databricks.token)이 설정되지 않았습니다.")
        if not (catalog and schema and volume):
            raise ValueError(
                "UC Volumes 위치(object_storage.databricks_catalog/schema/volume)가 설정되지 않았습니다."
            )
        from databricks.sdk import WorkspaceClient  # lazy

        self._w = WorkspaceClient(host=host, token=token)
        self._root = f"/Volumes/{catalog}/{schema}/{volume}"

    # ── URI 규약 ──────────────────────────────────────────────────────────────
    def _file_path(self, key: str) -> str:
        return f"{self._root}/{key.lstrip('/')}"

    def build_uri(self, key: str) -> str:
        return f"{_URI_SCHEME}{self._file_path(key)}"

    def parse_uri(self, source_uri: str) -> tuple[str, str]:
        path = self._uri_to_path(source_uri)
        # (container=볼륨 루트, key=루트 이하 상대경로)
        key = path[len(self._root) + 1:] if path.startswith(self._root + "/") else path.lstrip("/")
        return self._root, key

    def _uri_to_path(self, uri: str) -> str:
        """source_uri/path → Files API 절대경로(/Volumes/...)."""
        if uri.startswith(_URI_SCHEME):
            return uri[len(_URI_SCHEME):]
        if uri.startswith("/Volumes/"):
            return uri
        return self._file_path(uri)

    # ── RAG 코어 경로 ─────────────────────────────────────────────────────────
    async def ensure_bucket(self) -> None:
        # Volume 은 Unity Catalog 에서 사전 생성되어야 한다(API 로 자동 생성하지 않음). 존재만 확인.
        def _check():
            try:
                self._w.files.get_directory_metadata(self._root)
            except Exception as e:  # noqa: BLE001
                logger.warning("UC Volume 접근 확인 실패(%s): %s", self._root, e)

        await asyncio.to_thread(_check)

    async def put_object(self, key: str, data: bytes, content_type: str | None = None) -> str:
        path = self._file_path(key)
        await asyncio.to_thread(
            lambda: self._w.files.upload(path, io.BytesIO(data), overwrite=True)
        )
        uri = self.build_uri(key)
        logger.info("UC Volumes 업로드: %s (%d bytes)", uri, len(data))
        return uri

    async def get_object(self, source_uri: str) -> bytes:
        path = self._uri_to_path(source_uri)
        return await asyncio.to_thread(self._download_bytes, path)

    def _download_bytes(self, path: str) -> bytes:
        resp = self._w.files.download(path)
        return resp.contents.read()

    async def object_exists(self, key: str) -> bool:
        def _head() -> bool:
            try:
                self._w.files.get_metadata(self._file_path(key))
                return True
            except Exception:  # noqa: BLE001 — NotFound 등
                return False

        return await asyncio.to_thread(_head)

    async def delete_object(self, key: str) -> None:
        await asyncio.to_thread(lambda: self._w.files.delete(self._file_path(key)))

    async def copy_object(self, src_key: str, dst_key: str) -> None:
        # Files API 에 서버사이드 copy 가 없어 download→upload 로 처리.
        def _copy():
            data = self._download_bytes(self._file_path(src_key))
            self._w.files.upload(self._file_path(dst_key), io.BytesIO(data), overwrite=True)

        await asyncio.to_thread(_copy)

    # ── 파일 브라우저(관리) ────────────────────────────────────────────────────
    async def read_object_by_path(
        self, path: str, bucket: str | None = None
    ) -> tuple[bytes, str | None]:
        # content-type 은 Files API 가 제공하지 않아 None(호출부가 확장자로 추론).
        data = await asyncio.to_thread(self._download_bytes, self._uri_to_path(path))
        return data, None

    async def upload_object(
        self, directory: str, filename: str, data: bytes,
        content_type: str | None = None, bucket: str | None = None,
    ) -> None:
        base = directory.strip("/")
        safe = filename.replace("/", "_").strip() or "file"
        key = (base + "/" if base else "") + safe
        await asyncio.to_thread(
            lambda: self._w.files.upload(self._file_path(key), io.BytesIO(data), overwrite=True)
        )

    async def create_folder(self, path: str, bucket: str | None = None) -> None:
        await asyncio.to_thread(
            lambda: self._w.files.create_directory(self._file_path(path.strip("/")))
        )

    async def delete_paths(self, paths: list[str], bucket: str | None = None) -> None:
        def _do():
            for p in paths:
                fp = self._file_path(p.strip("/"))
                if p.endswith("/"):
                    self._w.files.delete_directory(fp)
                else:
                    self._w.files.delete(fp)

        await asyncio.to_thread(_do)

    async def list_directory(self, prefix: str = "", bucket: str | None = None) -> dict:
        directory = self._file_path(prefix.strip("/")) if prefix.strip("/") else self._root

        def _list():
            return list(self._w.files.list_directory_contents(directory))

        entries = await asyncio.to_thread(_list)
        folders, files = [], []
        for e in entries:
            name = (e.path or "").rstrip("/").rsplit("/", 1)[-1]
            rel = (e.path or "")[len(self._root):]
            if getattr(e, "is_directory", False):
                folders.append({"key": rel.rstrip("/") + "/", "name": name,
                                "owner": "", "group": "", "permissions": ""})
            else:
                lm = getattr(e, "last_modified", None)
                files.append({"key": rel, "name": name, "size": getattr(e, "file_size", 0) or 0,
                              "last_modified": str(lm) if lm else "",
                              "owner": "", "group": "", "permissions": ""})
        clean = prefix.strip("/")
        return {"folders": folders, "files": files, "current_path": "/" + clean if clean else "/"}

    async def list_buckets(self) -> list[str]:
        return [self._root]

    # ── UC Volumes 미지원(파일 브라우저 전용) ─────────────────────────────────
    async def presigned_download_url(self, path: str, bucket: str | None = None) -> str:
        raise NotImplementedError(
            "UC Volumes 는 공개 presigned URL 을 지원하지 않습니다. "
            "앱 프록시(read_object_by_path)로 다운로드를 처리하세요."
        )

    async def rename_path(
        self, source: str, destination: str, bucket: str | None = None
    ) -> None:
        raise NotImplementedError(
            "UC Volumes 백엔드는 이름변경(rename)을 아직 지원하지 않습니다(copy+delete 후속 작업)."
        )
