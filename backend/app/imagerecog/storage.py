# SPDX-License-Identifier: Apache-2.0
"""이미지 추출 및 분류 결과 전용 오브젝트 스토리지(MinIO) 헬퍼.

원본 문서/어노테이션 버킷과 분리된 ``settings.os_classification_bucket`` 을 사용한다.
한 번의 실행(파일 1건)은 ``{yyyy-mm-dd}/{run_id}/`` 프리픽스(날짜별 폴더 아래 UUID 폴더)에
저장되며, 그 파일에서 추출한 이미지는 모두 이 아래에 들어간다:

- ``{yyyy-mm-dd}/{run_id}/manifest.json``            — 실행 메타 + 이미지별 분석 결과
- ``{yyyy-mm-dd}/{run_id}/images/{index}_original.png`` — 원본 이미지(축소 없음)
- ``{yyyy-mm-dd}/{run_id}/images/{index}_thumb.png``    — 목록 표시용 썸네일

키 헬퍼는 위 프리픽스 문자열을 받아 만든다(프리픽스는 DB ``prefix`` 컬럼에도 보관).
boto3 동기 클라이언트는 ``app.storage.client`` 의 싱글턴을 재사용한다.
"""

import asyncio
import logging

from botocore.exceptions import ClientError

from app.core.config import settings
from app.storage.client import _get_client

logger = logging.getLogger(__name__)


def bucket() -> str:
    return settings.os_classification_bucket


def run_prefix(run_id: str, date_str: str) -> str:
    """``{yyyy-mm-dd}/{run_id}`` — 날짜별 폴더 아래 실행(파일) 1건의 UUID 폴더."""
    return f"{date_str}/{run_id}"


def manifest_key(prefix: str) -> str:
    return f"{prefix}/manifest.json"


def source_key(prefix: str, filename: str) -> str:
    """업로드한 원본 파일 키 — ``{prefix}/source/{filename}``(파일명 슬래시는 치환)."""
    safe = (filename or "upload").replace("/", "_").strip() or "upload"
    return f"{prefix}/source/{safe}"


def original_key(prefix: str, index: int) -> str:
    return f"{prefix}/images/{index}_original.png"


def thumb_key(prefix: str, index: int) -> str:
    return f"{prefix}/images/{index}_thumb.png"


async def ensure_bucket() -> None:
    """분류 버킷이 없으면 생성(멱등)."""
    def _ensure():
        client = _get_client()
        b = bucket()
        try:
            client.head_bucket(Bucket=b)
        except ClientError:
            client.create_bucket(Bucket=b)
            logger.info("이미지 추출 및 분류 버킷 생성: %s", b)

    await asyncio.to_thread(_ensure)


async def put_bytes(key: str, data: bytes, content_type: str | None = None) -> None:
    """바이트를 분류 버킷에 저장한다."""
    def _put():
        extra = {"ContentType": content_type} if content_type else {}
        _get_client().put_object(Bucket=bucket(), Key=key, Body=data, **extra)

    await asyncio.to_thread(_put)


async def put_json(key: str, body: str) -> None:
    """JSON(텍스트)을 분류 버킷에 저장한다."""
    def _put():
        _get_client().put_object(
            Bucket=bucket(), Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json; charset=utf-8",
        )

    await asyncio.to_thread(_put)


async def get_text(key: str) -> str:
    """분류 버킷의 객체를 텍스트로 읽는다(manifest 조회용)."""
    def _get() -> str:
        resp = _get_client().get_object(Bucket=bucket(), Key=key)
        return resp["Body"].read().decode("utf-8")

    return await asyncio.to_thread(_get)


async def get_bytes(key: str) -> bytes:
    """분류 버킷의 객체를 바이트로 읽는다(분석 시 원본 재읽기용)."""
    def _get() -> bytes:
        resp = _get_client().get_object(Bucket=bucket(), Key=key)
        return resp["Body"].read()

    return await asyncio.to_thread(_get)


async def prefix_size(prefix: str) -> int:
    """prefix 하위 모든 객체 크기 합(byte) — S3 ``list_objects_v2`` 로 집계(실제 디렉토리 크기)."""
    p = prefix.rstrip("/") + "/"
    b = bucket()

    def _do() -> int:
        client = _get_client()
        total = 0
        token = None
        while True:
            kw = {"Bucket": b, "Prefix": p}
            if token:
                kw["ContinuationToken"] = token
            resp = client.list_objects_v2(**kw)
            for o in resp.get("Contents", []):
                total += int(o.get("Size", 0) or 0)
            if resp.get("IsTruncated"):
                token = resp.get("NextContinuationToken")
            else:
                break
        return total

    return await asyncio.to_thread(_do)


async def delete_objects(keys: list[str]) -> None:
    """주어진 키들의 객체를 삭제한다(이미지 부분 삭제용)."""
    if not keys:
        return
    b = bucket()

    def _do():
        client = _get_client()
        objs = [{"Key": k} for k in keys]
        for i in range(0, len(objs), 1000):
            client.delete_objects(Bucket=b, Delete={"Objects": objs[i : i + 1000]})

    await asyncio.to_thread(_do)


async def delete_prefix(prefix: str) -> int:
    """prefix 하위 모든 객체를 삭제하고 삭제 개수를 반환한다(이력 삭제용)."""
    b = bucket()

    def _do() -> int:
        client = _get_client()
        count = 0
        token = None
        while True:
            kw = {"Bucket": b, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            resp = client.list_objects_v2(**kw)
            objs = [{"Key": o["Key"]} for o in resp.get("Contents", [])]
            count += len(objs)
            for i in range(0, len(objs), 1000):
                client.delete_objects(Bucket=b, Delete={"Objects": objs[i : i + 1000]})
            if resp.get("IsTruncated"):
                token = resp.get("NextContinuationToken")
            else:
                break
        return count

    return await asyncio.to_thread(_do)
