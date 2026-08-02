# SPDX-License-Identifier: Apache-2.0
"""modelmgr 스키마 — 서버(deploy 오케스트레이터)가 보내는 설치 요청/결과."""

from pydantic import BaseModel, Field


class ModelInstallRequest(BaseModel):
    """모델 아카이브 1개를 도커 볼륨에 전개하라는 요청.

    서버가 모델 저장소(argus-models 버킷)의 manifest 를 읽어 값을 채우고, 아카이브는
    presigned URL 로 전달한다(에이전트에 S3 자격증명을 주지 않기 위함).
    """

    volume: str = Field(..., max_length=200)        # 대상 도커 볼륨(예: argus-rag-vlm-models)
    subdir: str = Field(..., max_length=200)        # 볼륨 내 전개 디렉터리(모델 name)
    archive_url: str = Field(..., max_length=4000)  # presigned 다운로드 URL
    archive: str = Field(..., max_length=200)       # 파일명(model.tar.zst | model.tar.gz)
    sha256: str = Field(..., min_length=64, max_length=64)
    size_bytes: int = Field(0, ge=0)
    revision: str = Field("main", max_length=100)
    # 전개 레이아웃 — flat: {volume}/{subdir}/ 에 그대로(vLLM 로컬 경로 서빙),
    # hf-cache: HF 허브 캐시 구조(models--{org}--{name}/snapshots/{rev} + refs)로 재구성
    # (sentence-transformers/transformers 가 이름으로 캐시 조회하는 서버용).
    layout: str = Field("flat", max_length=20)
    repo: str = Field("", max_length=300)  # hf-cache 레이아웃의 디렉터리명 구성에 필요


class ModelInstallResult(BaseModel):
    status: str          # installed | skipped(이미 동일 sha 설치됨)
    path: str            # 호스트 상 전개 경로
    sha256: str
    bytes_downloaded: int = 0
