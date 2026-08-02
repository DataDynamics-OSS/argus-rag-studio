// 이미지 추출 및 분석 REST 클라이언트 — POST /image-recognition/analyze(일괄), analyze-stream(스트리밍).

import { authFetch, throwOnError } from "@/features/auth/auth-fetch"
import type {
  AnalyzeResult,
  PaginatedRuns,
  RecognitionStreamEvent,
  RunDetail,
} from "./data/schema"

/** 문서를 업로드해 안의 이미지를 추출·분류한다(저장 없는 휘발성 분석, 일괄 응답). */
export async function analyzeDocument(
  file: File,
  opts?: { signal?: AbortSignal },
): Promise<AnalyzeResult> {
  const form = new FormData()
  form.append("file", file)
  const res = await authFetch(`/api/v1/image-recognition/analyze`, {
    method: "POST",
    body: form,
    signal: opts?.signal,
  })
  if (!res.ok) await throwOnError(res, "이미지 추출 및 분석 실패")
  return res.json()
}

/** SSE(data: {...}\n\n) 응답을 읽어 onEvent 로 전달하는 공통 파서(멀티파트 POST 라 직접 파싱). */
async function consumeSSE(
  res: Response,
  onEvent: (e: RecognitionStreamEvent) => void,
): Promise<void> {
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split("\n\n")
    buffer = frames.pop() ?? ""
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data:"))
      if (!line) continue
      try {
        onEvent(JSON.parse(line.slice(5).trim()) as RecognitionStreamEvent)
      } catch {
        // 부분 프레임 무시
      }
    }
  }
}

/**
 * 업로드 문서/이미지에서 이미지를 추출·저장하며 진행 상황을 SSE 로 받는다(분석은 안 함).
 * start → image(한 장씩) → done. 분석은 이후 analyzeRunStream 으로.
 */
export async function extractDocumentStream(
  file: File,
  onEvent: (e: RecognitionStreamEvent) => void,
  opts?: { signal?: AbortSignal; batchId?: string },
): Promise<void> {
  const form = new FormData()
  form.append("file", file)
  if (opts?.batchId) form.append("batch_id", opts.batchId)
  const res = await authFetch(`/api/v1/image-recognition/extract-stream`, {
    method: "POST",
    body: form,
    signal: opts?.signal,
  })
  if (!res.ok || !res.body) await throwOnError(res, "이미지 추출 실패")
  await consumeSSE(res, onEvent)
}

/**
 * 외부 URL 의 HTML 이미지를 받는 대로 한 장씩 추출·저장하며 SSE 로 받는다(분석은 안 함).
 * dropSmall=true 면 작은 이미지(아이콘·트래킹 픽셀 등)를 버린다.
 */
export async function extractUrlStream(
  url: string,
  dropSmall: boolean,
  onEvent: (e: RecognitionStreamEvent) => void,
  opts?: { signal?: AbortSignal; batchId?: string },
): Promise<void> {
  const form = new FormData()
  form.append("url", url)
  form.append("drop_small", String(dropSmall))
  if (opts?.batchId) form.append("batch_id", opts.batchId)
  const res = await authFetch(`/api/v1/image-recognition/extract-url-stream`, {
    method: "POST",
    body: form,
    signal: opts?.signal,
  })
  if (!res.ok || !res.body) await throwOnError(res, "URL 가져오기 실패")
  await consumeSSE(res, onEvent)
}

/**
 * 추출된 실행(run)의 선택 이미지를 분석한다(SSE). indices 가 비면 전체 분석.
 * analyzing/item → done.
 */
export async function analyzeRunStream(
  runId: string,
  indices: number[],
  onEvent: (e: RecognitionStreamEvent) => void,
  opts?: { signal?: AbortSignal },
): Promise<void> {
  const form = new FormData()
  if (indices.length > 0) form.append("indices", indices.join(","))
  const res = await authFetch(
    `/api/v1/image-recognition/runs/${encodeURIComponent(runId)}/analyze-stream`,
    { method: "POST", body: form, signal: opts?.signal },
  )
  if (!res.ok || !res.body) await throwOnError(res, "이미지 분석 실패")
  await consumeSSE(res, onEvent)
}

/** 이미지 추출 및 분석 화면용 경량 설정(작은 이미지 제거 기준 KB 등). */
export async function getConfig(): Promise<{ small_image_min_kb: number }> {
  const res = await authFetch(`/api/v1/image-recognition/config`)
  if (!res.ok) await throwOnError(res, "설정 조회 실패")
  return res.json()
}

// ── 실행 이력(분류 버킷에 저장된 과거 실행) ──────────────────────────────────

/** 이미지 추출 및 분석 실행 이력 목록(최신순, 페이지네이션). */
export async function listRuns(params?: {
  page?: number
  page_size?: number
  batch_id?: string
}): Promise<PaginatedRuns> {
  const q = new URLSearchParams()
  if (params?.page) q.set("page", String(params.page))
  if (params?.page_size != null) q.set("page_size", String(params.page_size))
  if (params?.batch_id) q.set("batch_id", params.batch_id)
  const qs = q.toString()
  const res = await authFetch(`/api/v1/image-recognition/runs${qs ? `?${qs}` : ""}`)
  if (!res.ok) await throwOnError(res, "이력 조회 실패")
  return res.json()
}

/** 실행 1건 상세 — 이미지별 presigned URL + 분석 결과. */
export async function getRun(runId: string): Promise<RunDetail> {
  const res = await authFetch(`/api/v1/image-recognition/runs/${encodeURIComponent(runId)}`)
  if (!res.ok) await throwOnError(res, "이력 상세 조회 실패")
  return res.json()
}

/** 업로드 원본 파일을 동일출처 프록시로 받아 다운로드한다(authFetch→blob, presigned CORS 회피). */
export async function downloadRunSource(runId: string, filename: string): Promise<void> {
  const res = await authFetch(
    `/api/v1/image-recognition/runs/${encodeURIComponent(runId)}/source`,
  )
  if (!res.ok) await throwOnError(res, "원본 파일 다운로드 실패")
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename || "download"
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** 실행에서 선택한 이미지(인덱스)만 삭제한다(이력 자체는 유지). */
export async function deleteRunImages(
  runId: string,
  indices: number[],
): Promise<{ deleted: number; remaining: number }> {
  const form = new FormData()
  form.append("indices", indices.join(","))
  const res = await authFetch(
    `/api/v1/image-recognition/runs/${encodeURIComponent(runId)}/delete-images`,
    { method: "POST", body: form },
  )
  if (!res.ok) await throwOnError(res, "이미지 삭제 실패")
  return res.json()
}

/** 실행 1건 삭제 — 분류 버킷 객체 + 이력 레코드 제거. */
export async function deleteRun(runId: string): Promise<void> {
  const res = await authFetch(`/api/v1/image-recognition/runs/${encodeURIComponent(runId)}`, {
    method: "DELETE",
  })
  if (!res.ok) await throwOnError(res, "이력 삭제 실패")
}
