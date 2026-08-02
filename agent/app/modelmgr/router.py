# SPDX-License-Identifier: Apache-2.0
"""modelmgr API — 서버(deploy 오케스트레이터)가 배포 전에 모델을 볼륨에 설치할 때 호출."""

import logging

from fastapi import APIRouter, HTTPException

from app.modelmgr import service
from app.modelmgr.schemas import ModelInstallRequest, ModelInstallResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/model", tags=["model"])


@router.post("/install", response_model=ModelInstallResult)
async def install_model(req: ModelInstallRequest):
    """모델 아카이브(presigned URL)를 도커 볼륨에 전개한다(sha256 검증·멱등).

    대용량 다운로드·전개로 수 분 걸릴 수 있다 — 호출 측은 긴 타임아웃을 사용할 것.
    """
    try:
        return await service.install(req)
    except Exception as e:  # noqa: BLE001 — 설치 실패 사유를 그대로 전달
        logger.warning("모델 설치 실패: %s/%s — %s", req.volume, req.subdir, e)
        raise HTTPException(status_code=500, detail=str(e))
