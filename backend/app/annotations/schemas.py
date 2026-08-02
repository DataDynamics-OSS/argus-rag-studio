# SPDX-License-Identifier: Apache-2.0
"""어노테이션(Annotation) 모듈의 Pydantic 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class BoxItem(BaseModel):
    """bbox 단건(내부 표현 — 축정렬 사각형)."""

    seq: int = Field(..., ge=1)
    data: str = ""
    x1: int = Field(..., ge=0)
    y1: int = Field(..., ge=0)
    x2: int = Field(..., ge=0)
    y2: int = Field(..., ge=0)

    @model_validator(mode="after")
    def _normalize(self) -> "BoxItem":
        # x1<=x2, y1<=y2 를 보장(좌상단/우하단 정규화)
        if self.x1 > self.x2:
            self.x1, self.x2 = self.x2, self.x1
        if self.y1 > self.y2:
            self.y1, self.y2 = self.y2, self.y1
        return self


class BoxesUpdateRequest(BaseModel):
    """이미지의 박스 전체를 일괄 교체(멱등)."""

    boxes: list[BoxItem] = Field(default_factory=list)


class DetectedBoxItem(BoxItem):
    """자동 인식 후보 박스 — 내부 박스 + 검출 신뢰도(score)."""

    score: float = 0.0


class DetectResponse(BaseModel):
    """자동 인식 결과(후보 — 저장하지 않고 프론트가 검수 후 반영)."""

    boxes: list[DetectedBoxItem] = Field(default_factory=list)


class ImageUpdateRequest(BaseModel):
    """이미지 메타데이터/상태 부분 갱신."""

    status: str | None = Field(None, max_length=20)
    collection_id: int | None = None
    meta: dict | None = None


class AnnotationImageResponse(BaseModel):
    id: int
    image_id: str
    collection_id: int | None = None
    filename: str
    folder: str = ""
    source_uri: str | None = None
    content_type: str | None = None
    content_hash: str | None = None
    width: int
    height: int
    size_bytes: int
    status: str
    has_thumbnail: bool = False
    meta: dict | None = None
    box_count: int = 0
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
    # 읽기전용 원본 오브젝트(예: 분할 크롭) — DB 미등록. object_key 로 바이트를 받는다.
    readonly: bool = False
    object_key: str | None = None


class AnnotationDetailResponse(AnnotationImageResponse):
    """단건 상세 — 박스 목록 포함."""

    boxes: list[BoxItem] = Field(default_factory=list)


class PaginatedImagesResponse(BaseModel):
    items: list[AnnotationImageResponse]
    total: int
    page: int
    page_size: int


class UploadImageResponse(BaseModel):
    id: int
    image_id: str
    filename: str
    width: int
    height: int
    status: str
    overwritten: bool = False  # 같은 폴더의 동일 파일명을 덮어썼는지
