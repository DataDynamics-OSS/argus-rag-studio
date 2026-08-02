// 어노테이션 도메인 타입 — 백엔드(app/annotations/schemas.py)와 1:1 대응.

export type AnnotationStatus = "draft" | "in_progress" | "completed"

/** bbox 단건 — 내부 표현(축정렬 사각형). 좌표는 원본 이미지 픽셀 기준. */
export interface Box {
  seq: number
  data: string
  x1: number
  y1: number
  x2: number
  y2: number
}

/** 자동 인식 후보 박스 — 내부 박스 + 검출 신뢰도(score). */
export interface DetectedBox extends Box {
  score: number
}

/** AI-Hub 메타 블록(Annotation/Dataset/Images). 키는 규격 그대로 유지. */
export interface AnnotationMeta {
  Annotation?: Record<string, unknown>
  Dataset?: Record<string, unknown>
  Images?: Record<string, unknown>
}

export interface AnnotationImage {
  id: number
  image_id: string
  collection_id: number | null
  filename: string
  folder: string
  source_uri: string | null
  content_type: string | null
  content_hash: string | null
  width: number
  height: number
  size_bytes: number
  status: AnnotationStatus
  has_thumbnail: boolean
  meta: AnnotationMeta | null
  box_count: number
  created_by: string | null
  created_at: string
  updated_at: string
  // 읽기전용 원본 오브젝트(예: 분할 크롭) — DB 미등록. object_key 로 미리보기 바이트를 받는다.
  readonly?: boolean
  object_key?: string | null
}

export interface AnnotationDetail extends AnnotationImage {
  boxes: Box[]
}

export interface PaginatedImages {
  items: AnnotationImage[]
  total: number
  page: number
  page_size: number
}

export interface UploadImageResult {
  id: number
  image_id: string
  filename: string
  width: number
  height: number
  status: AnnotationStatus
  overwritten?: boolean
}
