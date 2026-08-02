// 어노테이션 REST 클라이언트 — 업로드 + 조회 + 박스/메타 저장 + 내보내기.

import { authFetch, getAccessToken, throwOnError } from "@/features/auth/auth-fetch"
import type {
  AnnotationDetail,
  AnnotationMeta,
  Box,
  DetectedBox,
  PaginatedImages,
  UploadImageResult,
} from "./data/schema"

/** 파일을 로드해 원본 픽셀 크기를 읽는다(업로드 시 좌표계 기준으로 전송). */
export function readImageSize(file: File): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      resolve({ width: img.naturalWidth, height: img.naturalHeight })
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error("이미지를 읽을 수 없습니다."))
    }
    img.src = url
  })
}

export async function uploadImage(
  file: File,
  opts?: {
    collectionId?: number
    folder?: string
    relativePath?: string
    overwrite?: boolean
    signal?: AbortSignal
  }
): Promise<UploadImageResult> {
  const { width, height } = await readImageSize(file)
  const form = new FormData()
  form.append("file", file)
  form.append("width", String(width))
  form.append("height", String(height))
  if (opts?.collectionId != null) form.append("collection_id", String(opts.collectionId))
  if (opts?.folder) form.append("folder", opts.folder)
  if (opts?.relativePath) form.append("relative_path", opts.relativePath)
  if (opts?.overwrite) form.append("overwrite", "true")
  const res = await authFetch(`/api/v1/annotations/images`, {
    method: "POST",
    body: form,
    signal: opts?.signal,
  })
  if (!res.ok) await throwOnError(res, "업로드 실패")
  return res.json()
}

export interface ConvertDocumentResult {
  filename: string
  pages: number
  created: number
  overwritten: number
  images: { image_id: string; filename: string; width: number; height: number }[]
}

export interface ConvertConfig {
  /** HWP/HWPX 변환 엔진: "rhwp"(클라이언트) | "libreoffice"(서버). */
  hwp_engine: string
  /** rhwp 클라이언트 렌더 배율. */
  hwp_scale: number
  /** 서버 변환 해상도(DPI, 참고용). */
  dpi: number
}

/** 문서 변환 클라이언트 설정 조회(HWP 엔진). 인증된 사용자 누구나 가능. */
export async function getConvertConfig(): Promise<ConvertConfig> {
  const res = await authFetch(`/api/v1/annotations/convert-config`)
  if (!res.ok) await throwOnError(res, "변환 설정 조회 실패")
  return res.json()
}

/** 문서(PDF·오피스·HWP)를 페이지별 이미지로 변환해 현재 폴더에 업로드한다. */
export async function convertDocument(
  file: File,
  opts?: { collectionId?: number; folder?: string; signal?: AbortSignal }
): Promise<ConvertDocumentResult> {
  const form = new FormData()
  form.append("file", file)
  if (opts?.collectionId != null) form.append("collection_id", String(opts.collectionId))
  if (opts?.folder) form.append("folder", opts.folder)
  const res = await authFetch(`/api/v1/annotations/convert-document`, {
    method: "POST",
    body: form,
    signal: opts?.signal,
  })
  if (!res.ok) await throwOnError(res, "문서 변환 실패")
  return res.json()
}

export async function listImages(params?: {
  status?: string
  search?: string
  folder?: string
  page?: number
  pageSize?: number
}): Promise<PaginatedImages> {
  const q = new URLSearchParams()
  if (params?.status) q.set("status", params.status)
  if (params?.search) q.set("search", params.search)
  if (params?.folder != null) q.set("folder", params.folder)
  if (params?.page) q.set("page", String(params.page))
  if (params?.pageSize) q.set("page_size", String(params.pageSize))
  const res = await authFetch(`/api/v1/annotations/images?${q.toString()}`)
  if (!res.ok) await throwOnError(res, "목록 조회 실패")
  return res.json()
}

// ── 폴더(가상 디렉터리) ────────────────────────────────────────────────────

/** parent 바로 아래 자식 폴더 경로 목록(루트 기준 전체 경로). parent 미지정=루트. */
export async function listFolders(parent?: string): Promise<string[]> {
  const q = new URLSearchParams()
  if (parent != null && parent !== "") q.set("parent", parent)
  const res = await authFetch(`/api/v1/annotations/folders?${q.toString()}`)
  if (!res.ok) await throwOnError(res, "폴더 조회 실패")
  const data = (await res.json()) as { folders: string[] }
  return data.folders
}

export async function createFolder(path: string): Promise<void> {
  const res = await authFetch(`/api/v1/annotations/folders`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  })
  if (!res.ok) await throwOnError(res, "폴더 생성 실패")
}

export async function deleteFolder(path: string): Promise<void> {
  const res = await authFetch(
    `/api/v1/annotations/folders?path=${encodeURIComponent(path)}`,
    { method: "DELETE" }
  )
  if (!res.ok) await throwOnError(res, "폴더 삭제 실패")
}

export async function getImage(imageId: string): Promise<AnnotationDetail> {
  const res = await authFetch(`/api/v1/annotations/images/${imageId}`)
  if (!res.ok) await throwOnError(res, "상세 조회 실패")
  return res.json()
}

/** 캔버스 배경 이미지 URL(동일출처 프록시 + Bearer 토큰을 blob 으로). */
export async function getImageBlobUrl(imageId: string): Promise<string> {
  const res = await authFetch(`/api/v1/annotations/images/${imageId}/file`)
  if (!res.ok) await throwOnError(res, "이미지 로드 실패")
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

/** DB 미등록 이미지 오브젝트(분할 크롭 등)를 키로 받아 blob URL 로 — 읽기전용 미리보기용. */
export async function getObjectBlobUrl(key: string): Promise<string> {
  const res = await authFetch(`/api/v1/annotations/object?key=${encodeURIComponent(key)}`)
  if (!res.ok) await throwOnError(res, "오브젝트 로드 실패")
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

/** 썸네일 blob URL. 썸네일이 없으면(404) null 을 반환(프론트는 원본으로 폴백). */
export async function getThumbBlobUrl(imageId: string): Promise<string | null> {
  const res = await authFetch(`/api/v1/annotations/images/${imageId}/thumbnail`)
  if (res.status === 404) return null
  if (!res.ok) await throwOnError(res, "썸네일 로드 실패")
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

/** 클라이언트에서 만든 썸네일(JPEG Blob)을 업로드한다. */
export async function uploadThumbnail(imageId: string, blob: Blob): Promise<void> {
  const form = new FormData()
  form.append("file", blob, "thumbnail.jpg")
  const res = await authFetch(`/api/v1/annotations/images/${imageId}/thumbnail`, {
    method: "POST",
    body: form,
  })
  if (!res.ok) await throwOnError(res, "썸네일 업로드 실패")
}

export async function saveBoxes(imageId: string, boxes: Box[]): Promise<AnnotationDetail> {
  const res = await authFetch(`/api/v1/annotations/images/${imageId}/boxes`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ boxes }),
  })
  if (!res.ok) await throwOnError(res, "박스 저장 실패")
  return res.json()
}

/**
 * 자동 bbox 인식 — 검출 서버(PaddleOCR)로 후보 박스를 받아온다(저장하지 않음).
 * 검출이 비활성/실패면 백엔드가 503 을 주며 throwOnError 로 메시지를 던진다.
 */
export async function detectBoxes(
  imageId: string,
  opts?: { withText?: boolean; minScore?: number }
): Promise<DetectedBox[]> {
  const q = new URLSearchParams()
  if (opts?.withText === false) q.set("with_text", "false")
  if (opts?.minScore != null) q.set("min_score", String(opts.minScore))
  const res = await authFetch(
    `/api/v1/annotations/images/${imageId}/detect?${q.toString()}`,
    { method: "POST" }
  )
  if (!res.ok) await throwOnError(res, "자동 인식 실패")
  const data = (await res.json()) as { boxes: DetectedBox[] }
  return data.boxes
}

export async function updateImage(
  imageId: string,
  patch: { status?: string; collection_id?: number | null; meta?: AnnotationMeta }
): Promise<AnnotationDetail> {
  const res = await authFetch(`/api/v1/annotations/images/${imageId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  })
  if (!res.ok) await throwOnError(res, "저장 실패")
  return res.json()
}

export async function deleteImage(imageId: string): Promise<void> {
  const res = await authFetch(`/api/v1/annotations/images/${imageId}`, { method: "DELETE" })
  if (!res.ok && res.status !== 204) await throwOnError(res, "삭제 실패")
}

/** AI-Hub JSON 다운로드(브라우저 파일 저장). */
export async function exportImage(imageId: string, filename: string): Promise<void> {
  const res = await authFetch(`/api/v1/annotations/images/${imageId}/export`)
  if (!res.ok) await throwOnError(res, "내보내기 실패")
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename.replace(/\.[^.]+$/, "") + ".json"
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export interface CropExportResult {
  images: number
  crops: number
  skipped_boxes: number
  location: string
}

/** 이미지 분할 — 각 bbox 를 잘라 학습용 크롭 PNG + JSONL 로 내보낸다(서버 파일시스템). */
export async function exportCrops(imageId: string): Promise<CropExportResult> {
  const res = await authFetch(`/api/v1/annotations/images/${imageId}/crops`, { method: "POST" })
  if (!res.ok) await throwOnError(res, "이미지 분할 실패")
  return res.json()
}

/** 현재 이미지의 AI-Hub JSON 문자열을 받아온다(다운로드 없이 미리보기용). */
export async function fetchExportJson(imageId: string): Promise<string> {
  const res = await authFetch(`/api/v1/annotations/images/${imageId}/export`)
  if (!res.ok) await throwOnError(res, "JSON 조회 실패")
  return res.text()
}

/**
 * AI-Hub JSON 문자열 → 내부 boxes + meta 로 파싱(클라이언트).
 * 백엔드 `aihub.parse_import` 와 동일 규칙: bbox 의 id 가 비었거나 중복이면 1부터 재부여.
 */
export function parseAihubJson(text: string): { boxes: Box[]; meta: AnnotationMeta } {
  const payload = JSON.parse(text) as Record<string, unknown>
  const rawBbox = Array.isArray(payload.bbox) ? (payload.bbox as Record<string, unknown>[]) : []
  const boxes: Box[] = rawBbox.map((b) => {
    const xs = (Array.isArray(b.x) ? b.x : []).map((v) => Number(v))
    const ys = (Array.isArray(b.y) ? b.y : []).map((v) => Number(v))
    if (!xs.length || !ys.length) throw new Error("bbox 좌표(x/y)가 비어 있습니다.")
    return {
      seq: Number(b.id ?? 0),
      data: String(b.data ?? ""),
      x1: Math.min(...xs),
      y1: Math.min(...ys),
      x2: Math.max(...xs),
      y2: Math.max(...ys),
    }
  })
  const seqs = boxes.map((b) => b.seq)
  const needsReseq = seqs.some((s) => s <= 0) || new Set(seqs).size !== seqs.length
  if (needsReseq) boxes.forEach((b, i) => (b.seq = i + 1))
  const meta: AnnotationMeta = {
    Annotation: (payload.Annotation as Record<string, unknown>) ?? {},
    Dataset: (payload.Dataset as Record<string, unknown>) ?? {},
    Images: (payload.Images as Record<string, unknown>) ?? {},
  }
  return { boxes, meta }
}

// getAccessToken 재노출(필요 시 직접 fetch 용)
export { getAccessToken }
