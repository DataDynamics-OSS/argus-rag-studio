# SPDX-License-Identifier: Apache-2.0
"""이미지 추출 및 분석 API — 문서 업로드 → 이미지 추출·분류(진단 화면용).

- POST /image-recognition/analyze : 문서(멀티파트) → 이미지별 유형·내용·썸네일

저장하지 않는 휘발성 분석이다. 로그인 사용자면 사용 가능(자기 문서 테스트).
"""

import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.database import get_session
from app.imagerecog import service
from app.imagerecog.schemas import AnalyzeResponse, PaginatedRunsResponse, RunDetail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/image-recognition", tags=["image-recognition"])

# 업로드 최대 크기(MB) — 진단 도구라 과대 업로드를 막는다.
_MAX_UPLOAD_MB = 50


@router.get("/config")
async def get_config(_user: CurrentUser):
    """이미지 추출 및 분석 화면용 경량 설정(작은 이미지 제거 기준 KB 등). 일반 사용자 접근 가능."""
    from app.core.config import settings

    return {"small_image_min_kb": settings.image_classification_small_image_min_kb}


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(_user: CurrentUser, file: UploadFile = File(...)):
    """문서에서 이미지를 추출해 유형·내용을 자동 인식하고 썸네일과 함께 반환한다."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    if len(data) > _MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"파일이 너무 큽니다(최대 {_MAX_UPLOAD_MB}MB).")
    try:
        return await service.analyze_document(file.filename or "upload", data)
    except RuntimeError as e:  # 비활성/미설정/미설치/미지원 — 사용자 안내성 오류
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning("이미지 추출 및 분석 실패: file=%s err=%s", file.filename, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"이미지 추출 및 분석 실패: {str(e)[:200]}")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/extract-stream")
async def extract_stream(
    user: CurrentUser,
    file: UploadFile = File(...),
    batch_id: str | None = Form(default=None),
):
    """업로드 문서/이미지에서 이미지를 추출·저장하며 SSE 로 흘린다(분석은 안 함).

    이벤트(JSON ``type``): ``start``(run_id·총수) → 장마다 ``image``(썸네일·원본) → ``done``.
    분석은 이후 ``POST /runs/{run_id}/analyze-stream`` 으로 선택 이미지만 수행한다."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    if len(data) > _MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"파일이 너무 큽니다(최대 {_MAX_UPLOAD_MB}MB).")
    filename = file.filename or "upload"

    async def gen():
        try:
            async for ev in service.extract_document_stream(
                filename, data, batch_id=batch_id, created_by=user.username,
                content_type=file.content_type,
            ):
                yield _sse(ev)
        except RuntimeError as e:  # 비활성/미지원 — 안내성 오류
            yield _sse({"type": "error", "detail": str(e)})
        except Exception as e:  # noqa: BLE001
            logger.warning("이미지 추출(스트림) 실패: file=%s err=%s", filename, e, exc_info=True)
            yield _sse({"type": "error", "detail": f"이미지 추출 실패: {str(e)[:200]}"})

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/extract-url-stream")
async def extract_url_stream(
    user: CurrentUser,
    url: str = Form(...),
    drop_small: bool = Form(default=True),
    batch_id: str | None = Form(default=None),
):
    """외부 URL 의 HTML 이미지를 받는 대로 한 장씩 추출·저장하며 SSE 로 흘린다(분석은 안 함).

    이벤트는 ``/extract-stream`` 과 동일하다. ``drop_small`` 이면 작은 이미지를 버린다."""
    if not (url or "").strip():
        raise HTTPException(status_code=400, detail="URL 을 입력하세요.")

    async def gen():
        try:
            async for ev in service.extract_url_stream(
                url, drop_small=drop_small, batch_id=batch_id, created_by=user.username
            ):
                yield _sse(ev)
        except RuntimeError as e:  # 비활성/잘못된 URL — 안내성 오류
            yield _sse({"type": "error", "detail": str(e)})
        except Exception as e:  # noqa: BLE001
            logger.warning("URL 이미지 가져오기 실패: url=%s err=%s", url, e, exc_info=True)
            yield _sse({"type": "error", "detail": f"URL 가져오기 실패: {str(e)[:200]}"})

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/runs/{run_id}/analyze-stream")
async def analyze_run_stream(
    run_id: str,
    _user: CurrentUser,
    indices: str | None = Form(default=None),
):
    """추출된 실행(run)의 선택 이미지를 분석하며 SSE 로 흘린다.

    ``indices`` 는 콤마구분 정수(예: ``0,2,5``). 비우면 전체 분석. 이벤트: 장마다
    ``analyzing``/``item`` → ``done``."""
    idx_list: list[int] | None = None
    if indices and indices.strip():
        try:
            idx_list = [int(x) for x in indices.split(",") if x.strip() != ""]
        except ValueError:
            raise HTTPException(status_code=400, detail="indices 형식이 잘못되었습니다(콤마구분 정수).")

    async def gen():
        try:
            async for ev in service.analyze_run_stream(run_id, idx_list):
                yield _sse(ev)
        except RuntimeError as e:  # 비활성/미설정/실행 없음 — 안내성 오류
            yield _sse({"type": "error", "detail": str(e)})
        except Exception as e:  # noqa: BLE001
            logger.warning("이미지 분석(스트림) 실패: run=%s err=%s", run_id, e, exc_info=True)
            yield _sse({"type": "error", "detail": f"이미지 분석 실패: {str(e)[:200]}"})

    return StreamingResponse(gen(), media_type="text/event-stream")


# ── 실행 이력(분류 버킷에 저장된 과거 실행) ──────────────────────────────────

@router.get("/runs", response_model=PaginatedRunsResponse)
async def list_runs(
    _user: CurrentUser,
    batch_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """이미지 추출 및 분석 실행 이력(최신순, 페이지네이션)."""
    items, total = await service.list_runs(
        session, page=page, page_size=page_size, batch_id=batch_id
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: str,
    _user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    """실행 1건 상세 — 이미지별 presigned URL(원본·썸네일) + 분석 결과."""
    detail = await service.get_run_detail(session, run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="실행 이력을 찾을 수 없습니다.")
    return detail


@router.get("/runs/{run_id}/source")
async def get_run_source(
    run_id: str,
    _user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    """업로드 원본 파일을 동일출처로 스트리밍한다(presigned 직접 fetch 의 CORS·도달 문제 회피)."""
    res = await service.get_run_source(session, run_id)
    if res is None:
        raise HTTPException(status_code=404, detail="원본 파일을 찾을 수 없습니다.")
    data, content_type, _filename = res
    return Response(content=data, media_type=content_type or "application/octet-stream")


@router.post("/runs/{run_id}/delete-images")
async def delete_run_images(
    run_id: str,
    _user: CurrentUser,
    indices: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    """실행에서 선택한 이미지(인덱스, 콤마구분)만 삭제한다(이력 자체는 유지)."""
    try:
        idx_list = [int(x) for x in indices.split(",") if x.strip() != ""]
    except ValueError:
        raise HTTPException(status_code=400, detail="indices 형식이 잘못되었습니다(콤마구분 정수).")
    if not idx_list:
        raise HTTPException(status_code=400, detail="삭제할 이미지를 선택하세요.")
    res = await service.delete_run_images(session, run_id, idx_list)
    if res is None:
        raise HTTPException(status_code=404, detail="실행 이력을 찾을 수 없습니다.")
    return res


@router.delete("/runs/{run_id}")
async def delete_run(
    run_id: str,
    _user: CurrentUser,
    session: AsyncSession = Depends(get_session),
):
    """실행 1건 삭제 — 분류 버킷 객체 + 이력 레코드 제거."""
    ok = await service.delete_run(session, run_id)
    if not ok:
        raise HTTPException(status_code=404, detail="실행 이력을 찾을 수 없습니다.")
    return {"ok": True}
