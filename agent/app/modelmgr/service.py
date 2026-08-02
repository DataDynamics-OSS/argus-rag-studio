# SPDX-License-Identifier: Apache-2.0
"""모델 설치 — presigned URL 다운로드 → sha256 검증 → 도커 볼륨에 전개(멱등).

설계: backend design/model-packaging.md §3.4. 볼륨 쓰기는 호스트 마운트포인트에 직접
수행한다(에이전트는 root) — `docker volume inspect` 로 경로를 얻는다. 전개는
``{subdir}.tmp`` 에 풀고 원자적 rename 으로 교체하며, ``.model-manifest.json`` 마커의
sha256 이 요청과 같으면 스킵한다(재배포 멱등).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

import httpx

from app.containermgr.service import CONTAINER_CMD, _run
from app.modelmgr.schemas import ModelInstallRequest, ModelInstallResult

logger = logging.getLogger(__name__)

_MARKER = ".model-manifest.json"


async def _volume_mountpoint(volume: str) -> Path:
    """볼륨을 보장(create 멱등)하고 호스트 마운트포인트를 반환한다."""
    code, _out, err = await _run(["volume", "create", volume])
    if code != 0:
        raise RuntimeError(f"volume create 실패: {err}")
    code, out, err = await _run(["volume", "inspect", "-f", "{{.Mountpoint}}", volume])
    if code != 0 or not out.strip():
        raise RuntimeError(f"volume inspect 실패: {err or out}")
    return Path(out.strip())


def _extract(archive: Path, dest: Path) -> None:
    """아카이브를 dest 에 전개 — tar.zst(zstd CLI 필요) / tar.gz(파이썬 내장)."""
    dest.mkdir(parents=True, exist_ok=True)
    name = archive.name
    if name.endswith(".tar.zst"):
        if not shutil.which("zstd"):
            raise RuntimeError("zstd 가 설치돼 있지 않아 tar.zst 를 전개할 수 없습니다.")
        # zstd -dc | tar -x — GNU tar --zstd 미지원 환경까지 커버.
        ps = subprocess.Popen(["zstd", "-dc", str(archive)], stdout=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=ps.stdout, mode="r|") as tf:
                tf.extractall(dest)  # noqa: S202 — 사내 팩 아카이브(사전 sha256 검증됨)
        finally:
            ps.stdout.close()  # type: ignore[union-attr]
            if ps.wait() != 0:
                raise RuntimeError("zstd 압축 해제 실패")
        return
    with tarfile.open(archive, "r:*") as tf:
        tf.extractall(dest)  # noqa: S202


def _target_dir(mount: Path, req: ModelInstallRequest) -> Path:
    """레이아웃별 설치 루트 — flat: {subdir}/, hf-cache: models--{org}--{name}/."""
    if req.layout == "hf-cache":
        if not req.repo:
            raise RuntimeError("hf-cache 레이아웃에는 repo 가 필요합니다.")
        return mount / f"models--{req.repo.replace('/', '--')}"
    return mount / req.subdir


def _finalize_layout(work: Path, req: ModelInstallRequest) -> None:
    """전개 후 레이아웃 마무리 — hf-cache 는 snapshots/{rev} + refs/{main} 구조로 재배치."""
    if req.layout != "hf-cache":
        return
    snap = work / "snapshots" / req.revision
    snap.parent.mkdir(parents=True)
    files = [p for p in work.iterdir() if p.name not in ("snapshots", _MARKER)]
    snap.mkdir()
    for p in files:
        p.rename(snap / p.name)
    refs = work / "refs"
    refs.mkdir()
    (refs / "main").write_text(req.revision)


async def install(req: ModelInstallRequest) -> ModelInstallResult:
    """모델 아카이브를 볼륨에 설치한다(다운로드→검증→전개→마커). 동일 sha 면 스킵."""
    mount = await _volume_mountpoint(req.volume)
    target = _target_dir(mount, req)
    marker = target / _MARKER

    # 멱등 — 동일 sha256 이 이미 설치돼 있으면 스킵.
    if marker.exists():
        try:
            if json.loads(marker.read_text()).get("sha256") == req.sha256:
                logger.info("모델 설치 스킵(동일 sha256): %s/%s", req.volume, req.subdir)
                return ModelInstallResult(status="skipped", path=str(target), sha256=req.sha256)
        except (ValueError, OSError):
            pass  # 마커 손상 — 재설치

    # 1) 다운로드(스트리밍) + sha256 동시 계산.
    digest = hashlib.sha256()
    downloaded = 0
    with tempfile.NamedTemporaryFile(suffix=f"-{req.archive}", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=600.0)) as client:
                async with client.stream("GET", req.archive_url) as resp:
                    if resp.status_code != 200:
                        raise RuntimeError(f"아카이브 다운로드 실패({resp.status_code})")
                    async for chunk in resp.aiter_bytes(1024 * 1024):
                        tmp.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
    try:
        # 2) 체크섬 검증 — 불일치면 전개하지 않는다(손상/변조 방어).
        actual = digest.hexdigest()
        if actual != req.sha256:
            raise RuntimeError(f"sha256 불일치: 기대 {req.sha256[:12]}… 실제 {actual[:12]}…")

        # 3) 전개 — tmp 디렉터리에 풀고 원자적 교체.
        work = mount / f"{target.name}.tmp"
        if work.exists():
            shutil.rmtree(work)
        await asyncio.to_thread(_extract, tmp_path, work)
        await asyncio.to_thread(_finalize_layout, work, req)
        (work / _MARKER).write_text(json.dumps({
            "sha256": req.sha256, "archive": req.archive, "layout": req.layout,
            "revision": req.revision, "size_bytes": req.size_bytes,
        }, ensure_ascii=False))
        if target.exists():
            shutil.rmtree(target)
        work.rename(target)
    finally:
        tmp_path.unlink(missing_ok=True)

    logger.info(
        "모델 설치 완료: %s/%s (%.1f MB, runtime=%s)",
        req.volume, req.subdir, downloaded / 1e6, CONTAINER_CMD,
    )
    return ModelInstallResult(
        status="installed", path=str(target), sha256=req.sha256, bytes_downloaded=downloaded
    )
