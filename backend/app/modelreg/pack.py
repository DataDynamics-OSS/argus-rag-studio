# SPDX-License-Identifier: Apache-2.0
"""서버에서 바로 팩 — 온라인 개발망 편의(design/model-registry.md §3.4, Step 3).

인터넷이 되는 개발망 한정: 모델 관리 화면의 "서버에서 팩" 버튼이 백엔드에서
HF 다운로드 → 아카이브(pack_model 헬퍼 재사용) → Model Repository(argus-models) 업로드를
백그라운드 잡으로 실행한다. 완료되면 해당 모델이 '보유'로 바뀌어 배포에 쓸 수 있다.

에어갭에서는 HF 도달성 검사(``check_online``)가 false 라 화면이 버튼을 숨기고
외부망 팩 안내만 보여준다. 잡은 프로세스 메모리에만 기록된다(서버 재시작 시 이력
소멸 — 개발 편의 기능이므로 충분). 동시 실행은 1개로 제한한다(디스크·대역폭 보호).
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# 스냅샷 + tar + 압축본이 동시에 존재하는 순간이 있어 대략 2.5배 여유를 요구한다.
_DISK_FACTOR = 2.5

_jobs: dict[str, "PackJob"] = {}  # model_id → 최근 잡(1모델 1잡)
_lock = asyncio.Lock()


@dataclass
class PackJob:
    model_id: str
    kind: str
    name: str
    repo: str
    revision: str
    status: str = "running"  # running | done | error
    detail: str = "준비 중"
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


# ── 온라인(HF 도달성) 검사 — 60초 캐시 ─────────────────────────────────────────

_online_cache: tuple[float, bool] | None = None


async def check_online() -> bool:
    """huggingface.co 도달 가능 여부(3초 타임아웃, 60초 캐시). 에어갭이면 False."""
    global _online_cache
    now = time.time()
    if _online_cache and now - _online_cache[0] < 60:
        return _online_cache[1]
    import httpx

    try:
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:
            r = await client.head("https://huggingface.co")
            ok = r.status_code < 500
    except Exception:
        ok = False
    _online_cache = (now, ok)
    return ok


# ── 잡 조회/기동 ──────────────────────────────────────────────────────────────

def list_jobs() -> list[dict]:
    """최근 팩 잡 목록(모델당 1개, 최신 상태)."""
    return [j.as_dict() for j in sorted(_jobs.values(), key=lambda j: -j.started_at)]


def running_job() -> PackJob | None:
    return next((j for j in _jobs.values() if j.status == "running"), None)


async def start_pack(entry: dict) -> PackJob:
    """레지스트리 항목(entry_dict 형태) 1개의 팩 잡을 시작한다.

    RuntimeError: 이미 실행 중(동시 1개 제한) / 디스크 부족 예상.
    """
    async with _lock:
        active = running_job()
        if active:
            raise RuntimeError(f"이미 팩 진행 중입니다: {active.kind}/{active.name} — 완료 후 다시 시도하세요.")

        # 디스크 여유 가드 — approx_gb 를 아는 경우만(사용자 등록분은 통과).
        approx_gb = entry.get("approx_gb")
        if approx_gb:
            free_gb = shutil.disk_usage(tempfile.gettempdir()).free / 1e9
            need = approx_gb * _DISK_FACTOR
            if free_gb < need:
                raise RuntimeError(
                    f"임시 디스크 여유 부족: {free_gb:.0f} GB < 필요 약 {need:.0f} GB "
                    f"(모델 ~{approx_gb} GB × {_DISK_FACTOR}) — 외부망 pack_model 을 사용하세요."
                )

        job = PackJob(
            model_id=entry["model_id"], kind=entry["kind"], name=entry["name"],
            repo=entry["repo"], revision=entry.get("revision") or "main",
        )
        _jobs[entry["model_id"]] = job

    async def _run():
        try:
            await asyncio.to_thread(_run_pack, job, entry.get("target") or "hf-cache")
            job.status, job.detail = "done", "완료 — 보유로 전환됨"
            logger.info("서버 팩 완료: %s/%s", job.kind, job.name)
        except Exception as e:  # 다운로드/업로드 실패 등 — 잡 상태로 노출
            job.status, job.detail = "error", str(e)
            logger.warning("서버 팩 실패: %s/%s — %s", job.kind, job.name, e)
        finally:
            job.finished_at = time.time()

    asyncio.create_task(_run())
    return job


def _run_pack(job: PackJob, target: str) -> None:
    """(스레드) 다운로드 → 아카이브 → sha256 → 버킷 업로드. scripts/pack_model 헬퍼 재사용."""
    from huggingface_hub import snapshot_download

    from app.core.config import settings
    from app.storage.client import _get_client
    from scripts.pack_model import build_manifest, make_archive, sha256_of

    bucket = settings.os_models_bucket
    with tempfile.TemporaryDirectory(prefix="model-pack-") as tmp:
        job.detail = f"HF 다운로드 중: {job.repo}@{job.revision}"
        snap = snapshot_download(
            repo_id=job.repo, revision=job.revision, local_dir=f"{tmp}/snap"
        )
        job.detail = "아카이브 생성 중(tar+압축)"
        archive = make_archive(Path(snap), Path(tmp) / "out")
        digest = sha256_of(archive)
        size = archive.stat().st_size
        manifest = build_manifest(
            kind=job.kind, name=job.name, repo=job.repo, revision=job.revision,
            target=target, archive=archive.name, sha256=digest, size_bytes=size,
        )

        job.detail = f"모델 저장소 업로드 중 ({size / 1e6:.0f} MB)"
        client = _get_client()
        prefix = f"{job.kind}/{job.name}/{job.revision}"
        # upload_file 은 대용량을 자동 멀티파트로 처리한다.
        client.upload_file(str(archive), bucket, f"{prefix}/{archive.name}")
        client.put_object(
            Bucket=bucket, Key=f"{prefix}/manifest.json",
            Body=json.dumps(manifest, ensure_ascii=False).encode(),
            ContentType="application/json",
        )
