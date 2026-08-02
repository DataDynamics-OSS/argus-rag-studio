# SPDX-License-Identifier: Apache-2.0
"""어노테이션 이미지 전용 오브젝트 스토리지(MinIO) 헬퍼.

원본 문서 버킷과 분리된 ``settings.os_annotation_bucket`` 을 사용한다. 이미지는
가상 폴더(prefix) 아래 ``{folder}/{filename}`` 키로 저장되며, 폴더 탐색기 UI 가
``list_folders`` 로 폴더 트리를, DB(``AnnotationImage.folder``)로 폴더별 이미지를 조회한다.

S3 에는 실제 폴더가 없어 빈 폴더는 ``prefix/`` 빈 마커 객체로 표현한다(파일 브라우저와 동일).
boto3 동기 클라이언트는 ``app.storage.client`` 의 싱글턴을 재사용한다.
"""

import asyncio
import logging

from botocore.exceptions import ClientError

from app.core.config import settings
from app.storage.client import _get_client

logger = logging.getLogger(__name__)


def bucket() -> str:
    return settings.os_annotation_bucket


def norm_folder(folder: str | None) -> str:
    """폴더 경로 정규화 — 앞뒤 슬래시 제거, 빈 값은 루트("")."""
    return (folder or "").strip().strip("/")


def build_key(folder: str | None, filename: str) -> str:
    """``{folder}/{filename}`` 오브젝트 키. 파일명의 슬래시는 치환."""
    safe = filename.replace("/", "_").strip() or "image"
    f = norm_folder(folder)
    return f"{f}/{safe}" if f else safe


def build_source_uri(key: str) -> str:
    return f"s3://{bucket()}/{key}"


# content-type → 썸네일 확장자
_THUMB_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def build_thumb_key(folder: str | None, filename: str, content_type: str | None) -> str:
    """썸네일 키 — 원본 파일명(stem) 뒤에 ``_thumbnail`` 을 붙인다.

    예) ``a/b/photo.png`` + image/jpeg → ``a/b/photo_thumbnail.jpg``.
    """
    import os

    stem = os.path.splitext(filename)[0] or "image"
    ext = _THUMB_EXT.get((content_type or "").lower(), "jpg")
    return build_key(folder, f"{stem}_thumbnail.{ext}")


def build_json_key(folder: str | None, filename: str) -> str:
    """라벨 JSON 사이드카 키 — 원본 파일명(stem) 뒤에 ``.json`` 을 붙인다.

    이미지와 **같은 폴더·같은 이름**(확장자만 .json)으로 두어, 라벨링 완료 시
    이미지 옆에 라벨 파일이 나란히 놓이게 한다. 예) ``a/b/photo.png`` → ``a/b/photo.json``.
    """
    import os

    stem = os.path.splitext(filename)[0] or "annotation"
    return build_key(folder, f"{stem}.json")


async def ensure_bucket() -> None:
    """어노테이션 버킷이 없으면 생성(멱등)."""
    def _ensure():
        client = _get_client()
        b = bucket()
        try:
            client.head_bucket(Bucket=b)
        except ClientError:
            client.create_bucket(Bucket=b)
            logger.info("어노테이션 이미지 버킷 생성: %s", b)

    await asyncio.to_thread(_ensure)


async def put_image(key: str, data: bytes, content_type: str | None = None) -> str:
    """이미지 바이트를 어노테이션 버킷에 저장하고 source_uri 를 반환."""
    def _put():
        extra = {"ContentType": content_type} if content_type else {}
        _get_client().put_object(Bucket=bucket(), Key=key, Body=data, **extra)

    await asyncio.to_thread(_put)
    uri = build_source_uri(key)
    logger.info("어노테이션 이미지 업로드: %s (%d bytes)", uri, len(data))
    return uri


async def put_json(key: str, body: str) -> str:
    """라벨 JSON(텍스트)을 어노테이션 버킷에 저장하고 source_uri 를 반환."""
    def _put():
        _get_client().put_object(
            Bucket=bucket(), Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json; charset=utf-8",
        )

    await asyncio.to_thread(_put)
    uri = build_source_uri(key)
    logger.info("어노테이션 라벨 JSON 저장: %s (%d bytes)", uri, len(body))
    return uri


async def list_folders(parent: str | None = None) -> list[str]:
    """parent 폴더 바로 아래의 자식 폴더 경로 목록(루트 기준 전체 경로)을 반환한다.

    예) parent="a" → ["a/b", "a/c"]. delimiter='/' 로 한 단계만 탐색.
    """
    p = norm_folder(parent)
    s3_prefix = f"{p}/" if p else ""

    def _list():
        return _get_client().list_objects_v2(Bucket=bucket(), Prefix=s3_prefix, Delimiter="/")

    resp = await asyncio.to_thread(_list)
    out: list[str] = []
    for cp in resp.get("CommonPrefixes", []):
        out.append(cp["Prefix"].rstrip("/"))
    return sorted(out)


async def create_folder(path: str) -> None:
    """가상 폴더 생성 — ``{path}/`` 빈 마커 객체를 PUT."""
    key = norm_folder(path) + "/"

    def _do():
        _get_client().put_object(Bucket=bucket(), Key=key, Body=b"")

    await asyncio.to_thread(_do)


async def delete_prefix(path: str) -> list[str]:
    """폴더(prefix) 하위 모든 객체를 삭제하고, 삭제된 객체 키 목록을 반환한다."""
    prefix = norm_folder(path) + "/"
    b = bucket()

    def _do() -> list[str]:
        client = _get_client()
        deleted: list[str] = []
        token = None
        while True:
            kw = {"Bucket": b, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            resp = client.list_objects_v2(**kw)
            objs = [{"Key": o["Key"]} for o in resp.get("Contents", [])]
            deleted.extend(o["Key"] for o in objs)
            for i in range(0, len(objs), 1000):
                client.delete_objects(Bucket=b, Delete={"Objects": objs[i : i + 1000]})
            if resp.get("IsTruncated"):
                token = resp.get("NextContinuationToken")
            else:
                break
        return deleted

    return await asyncio.to_thread(_do)


async def list_direct_object_keys(prefix: str | None = None) -> list[str]:
    """prefix 바로 아래 직속 오브젝트(파일) 키만 반환한다(delimiter='/' — 하위 폴더는 제외).

    그리드 목록처럼 한 폴더의 파일만 필요할 때 사용한다(전체 서브트리 스캔 회피).
    """
    p = norm_folder(prefix)
    s3_prefix = f"{p}/" if p else ""
    b = bucket()

    def _list() -> list[str]:
        client = _get_client()
        keys: list[str] = []
        token = None
        while True:
            kw = {"Bucket": b, "Prefix": s3_prefix, "Delimiter": "/"}
            if token:
                kw["ContinuationToken"] = token
            resp = client.list_objects_v2(**kw)
            keys.extend(o["Key"] for o in resp.get("Contents", []))
            if resp.get("IsTruncated"):
                token = resp.get("NextContinuationToken")
            else:
                break
        return keys

    return await asyncio.to_thread(_list)


async def list_object_keys(prefix: str | None = None) -> list[str]:
    """prefix 하위 모든 오브젝트 키 목록(재귀, delimiter 없음)을 반환한다."""
    p = norm_folder(prefix)
    s3_prefix = f"{p}/" if p else ""
    b = bucket()

    def _list() -> list[str]:
        client = _get_client()
        keys: list[str] = []
        token = None
        while True:
            kw = {"Bucket": b, "Prefix": s3_prefix}
            if token:
                kw["ContinuationToken"] = token
            resp = client.list_objects_v2(**kw)
            keys.extend(o["Key"] for o in resp.get("Contents", []))
            if resp.get("IsTruncated"):
                token = resp.get("NextContinuationToken")
            else:
                break
        return keys

    return await asyncio.to_thread(_list)


async def delete_object(key: str) -> None:
    """단일 객체 삭제."""
    def _do():
        _get_client().delete_object(Bucket=bucket(), Key=key)

    await asyncio.to_thread(_do)
