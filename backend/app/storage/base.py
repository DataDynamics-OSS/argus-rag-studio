# SPDX-License-Identifier: Apache-2.0
"""StorageBackend 인터페이스 — 원본 문서·아티팩트 오브젝트 저장소 추상화.

기본 백엔드는 S3 호환(MinIO/S3)이고, 기반 환경=databricks 에서는 Unity Catalog Volumes 를
쓸 수 있다. 호출부(documents/ingestion/s3browse)는 ``app.storage.client`` 의 모듈 함수를 통해
이 백엔드에 위임한다.

스코프 메모: RAG 코어 경로(문서 업로드·인제스천)는 put_object/get_object/build_object_key 만
쓴다. 나머지(list_directory/presigned/create_folder/rename 등)는 파일 브라우저(s3browse) 관리
기능으로, 백엔드별로 지원 범위가 다를 수 있다(UC Volumes 는 일부를 NotImplementedError 로 둔다).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    """오브젝트 저장소 백엔드. 모든 메서드는 비동기(블로킹 I/O 는 to_thread 로 감싼다)."""

    # ── URI 규약(백엔드별 스킴) ───────────────────────────────────────────────
    def build_uri(self, key: str) -> str:
        """오브젝트 키 → 영속 URI(rag_documents.source_uri 에 저장). 예: ``s3://bucket/key``."""

    def parse_uri(self, source_uri: str) -> tuple[str, str]:
        """URI → (container, key). container 는 S3 버킷 / UC 볼륨 루트."""

    # ── RAG 코어 경로(문서 업로드·인제스천) ──────────────────────────────────
    async def ensure_bucket(self) -> None:
        """기본 컨테이너(버킷/볼륨)가 없으면 생성(멱등)."""

    async def put_object(self, key: str, data: bytes, content_type: str | None = None) -> str:
        """바이트 저장 후 source_uri 반환."""

    async def get_object(self, source_uri: str) -> bytes:
        """source_uri 의 바이트를 읽어 반환."""

    async def object_exists(self, key: str) -> bool:
        """오브젝트 존재 여부."""

    async def delete_object(self, key: str) -> None:
        """오브젝트 1개 삭제."""

    async def copy_object(self, src_key: str, dst_key: str) -> None:
        """컨테이너 내 복사."""

    # ── 파일 브라우저(관리) — 백엔드별 지원 범위 상이 ─────────────────────────
    async def list_buckets(self) -> list[str]: ...

    async def list_directory(self, prefix: str = "", bucket: str | None = None) -> dict: ...

    async def presigned_download_url(self, path: str, bucket: str | None = None) -> str: ...

    async def read_object_by_path(
        self, path: str, bucket: str | None = None
    ) -> tuple[bytes, str | None]: ...

    async def create_folder(self, path: str, bucket: str | None = None) -> None: ...

    async def upload_object(
        self, directory: str, filename: str, data: bytes,
        content_type: str | None = None, bucket: str | None = None,
    ) -> None: ...

    async def delete_paths(self, paths: list[str], bucket: str | None = None) -> None: ...

    async def rename_path(
        self, source: str, destination: str, bucket: str | None = None
    ) -> None: ...
