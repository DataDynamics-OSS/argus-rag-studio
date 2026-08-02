# SPDX-License-Identifier: Apache-2.0
"""LibreOffice headless 로 오피스 문서를 PDF 로 변환(고충실도 미리보기용).

doc/docx/ppt/pptx/xls/xlsx → PDF. 렌더 엔진이 LibreOffice 자체라 레이아웃·도형·이미지·표가
거의 원본대로 보존되고, 구형 바이너리(.doc/.ppt/.xls)도 처리된다. 변환 결과는 기존 PDF 뷰어로 렌더.

설계: design/hwp-preview.md 의 후속(오피스 고충실도). HWP/HWPX 는 rhwp(클라이언트)가 담당하며
여기서 다루지 않는다.

LibreOffice 미설치 환경에선 is_available()=False → 호출부가 기존 native 미리보기로 폴백한다.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
from collections import OrderedDict

logger = logging.getLogger(__name__)

# 동시 변환 제한·타임아웃 — settings(image_conversion.office_*)에서 읽는다. soffice 는 무겁다.
_sem: asyncio.Semaphore | None = None

_available: bool | None = None

# 변환 PDF 캐시(입력 바이트 해시 → PDF). 재열람 시 재변환 방지.
_CACHE: "OrderedDict[str, bytes]" = OrderedDict()
_CACHE_MAX_ITEMS = 24
_CACHE_MAX_BYTES = 256 * 1024 * 1024
_cache_bytes = 0


def _semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        from app.core.config import settings
        _sem = asyncio.Semaphore(settings.image_conversion_office_concurrency)
    return _sem


def soffice_bin() -> str | None:
    """soffice 실행 파일 경로. ARGUS_SOFFICE_PATH 우선(비표준 경로 대응)."""
    return (
        os.environ.get("ARGUS_SOFFICE_PATH")
        or shutil.which("soffice")
        or shutil.which("libreoffice")
    )


def is_available() -> bool:
    """LibreOffice 사용 가능 여부(탐지 + 실행 검증, 결과 캐시)."""
    global _available
    if _available is None:
        binary = soffice_bin()
        try:
            _available = bool(binary) and subprocess.run(
                [binary, "--version"], capture_output=True, timeout=15
            ).returncode == 0
        except Exception:  # noqa: BLE001
            _available = False
        logger.info("LibreOffice 변환 가용: %s (bin=%s)", _available, binary)
    return _available


def _cache_get(key: str) -> bytes | None:
    pdf = _CACHE.get(key)
    if pdf is not None:
        _CACHE.move_to_end(key)
    return pdf


def _cache_put(key: str, pdf: bytes) -> None:
    global _cache_bytes
    if key in _CACHE:
        return
    _CACHE[key] = pdf
    _cache_bytes += len(pdf)
    while _CACHE and (len(_CACHE) > _CACHE_MAX_ITEMS or _cache_bytes > _CACHE_MAX_BYTES):
        _, old = _CACHE.popitem(last=False)
        _cache_bytes -= len(old)


async def convert_to_pdf(data: bytes, ext: str) -> bytes:
    """오피스 문서 바이트를 PDF 바이트로 변환한다. 동시성 제한 + 타임아웃 + 캐시."""
    from app.core.config import settings
    timeout = settings.image_conversion_office_timeout
    binary = soffice_bin()
    if not binary:
        raise RuntimeError("LibreOffice(soffice) 를 찾을 수 없습니다.")

    key = hashlib.sha256(data).hexdigest()
    cached = _cache_get(key)
    if cached is not None:
        return cached

    async with _semaphore():
        # 캐시 재확인(대기 중 다른 요청이 채웠을 수 있음)
        cached = _cache_get(key)
        if cached is not None:
            return cached

        tmp = tempfile.mkdtemp(prefix="lo_conv_")
        try:
            src = os.path.join(tmp, f"input.{(ext or 'bin').lower()}")
            with open(src, "wb") as f:
                f.write(data)
            profile = os.path.join(tmp, "profile")

            proc = await asyncio.create_subprocess_exec(
                binary, "--headless", "--nologo", "--nofirststartwizard",
                f"-env:UserInstallation=file://{profile}",
                "--convert-to", "pdf", "--outdir", tmp, src,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise RuntimeError(f"변환 시간 초과({timeout}s)")

            out = os.path.join(tmp, "input.pdf")
            if not os.path.exists(out):
                msg = (stderr or b"").decode("utf-8", "ignore").strip()[:200]
                raise RuntimeError(f"PDF 변환 실패: {msg or 'output 없음'}")

            with open(out, "rb") as f:
                pdf = f.read()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    _cache_put(key, pdf)
    logger.info("오피스→PDF 변환: ext=%s in=%dB out=%dB", ext, len(data), len(pdf))
    return pdf
