// 인제스천 REST 클라이언트 — 업로드(multipart) + 잡 상태 폴링 + 재처리.

import { authFetch, throwOnError } from "@/features/auth/auth-fetch"
import type {
  ChunkPreview,
  ExtServerStat,
  IngestionJob,
  JobsSummary,
  PaginatedJobs,
  ParsePreview,
  UploadResult,
  WorkerInfo,
} from "./data/schema"

/** 외부 확장 서버(임베딩·리랭커·검출) 런타임 메트릭 — 잡 모니터링 '외부 서버' 탭. */
export async function getExtServerStats(): Promise<ExtServerStat[]> {
  const res = await authFetch(`/api/v1/embedding/server-stats`)
  if (!res.ok) await throwOnError(res, "외부 서버 상태 조회 실패")
  return res.json()
}

/** 인제스천 워커 목록(하트비트 기반 생존·현재 잡·처리량) — 잡 모니터링 '워커' 탭. */
export async function getWorkers(): Promise<WorkerInfo[]> {
  const res = await authFetch(`/api/v1/workers`)
  if (!res.ok) await throwOnError(res, "워커 상태 조회 실패")
  return res.json()
}

/** 등록된 확장 서버 레플리카(하트비트) — LB 뒤 풀 전체. '외부 서버' 탭. */
export async function getRegisteredExtServers(): Promise<ExtServerStat[]> {
  const res = await authFetch(`/api/v1/ext-servers`)
  if (!res.ok) await throwOnError(res, "확장 서버 레플리카 조회 실패")
  return res.json()
}

/** 전역 인제스천 잡 목록(필터·페이지) — 모니터링 페이지용. */
export async function listJobs(params?: {
  status?: string
  collection_id?: number
  page?: number
  page_size?: number
}): Promise<PaginatedJobs> {
  const q = new URLSearchParams()
  if (params?.status) q.set("status", params.status)
  if (params?.collection_id != null) q.set("collection_id", String(params.collection_id))
  if (params?.page) q.set("page", String(params.page))
  if (params?.page_size != null) q.set("page_size", String(params.page_size))
  const qs = q.toString()
  const res = await authFetch(`/api/v1/ingestion/jobs${qs ? `?${qs}` : ""}`)
  if (!res.ok) await throwOnError(res, "잡 목록 조회 실패")
  return res.json()
}

/** 잡 요약 집계(대기/진행중/24h 완료·실패). */
export async function getJobsSummary(): Promise<JobsSummary> {
  const res = await authFetch(`/api/v1/ingestion/jobs/summary`)
  if (!res.ok) await throwOnError(res, "잡 요약 조회 실패")
  return res.json()
}

export async function uploadDocument(
  collectionId: number,
  file: File
): Promise<UploadResult> {
  const form = new FormData()
  form.append("file", file)
  // Content-Type 은 브라우저가 multipart boundary 와 함께 자동 설정하므로 지정하지 않는다.
  const res = await authFetch(`/api/v1/collections/${collectionId}/ingest`, {
    method: "POST",
    body: form,
  })
  if (!res.ok) await throwOnError(res, "업로드 실패")
  return res.json()
}

export async function getJob(jobId: string): Promise<IngestionJob> {
  const res = await authFetch(`/api/v1/ingestion/jobs/${jobId}`)
  if (!res.ok) await throwOnError(res, "잡 조회 실패")
  return res.json()
}

export async function reindexDocument(documentUuid: string): Promise<UploadResult> {
  const res = await authFetch(`/api/v1/documents/${documentUuid}/reindex`, { method: "POST" })
  if (!res.ok) await throwOnError(res, "재처리 실패")
  return res.json()
}

/** 파싱 미리보기 — 등록된 문서를 저장·임베딩 없이 다시 파싱해 결과 텍스트를 받는다. */
export async function parsePreviewDocument(
  documentUuid: string,
  opts?: { strategy?: string; maxChars?: number }
): Promise<ParsePreview> {
  const q = new URLSearchParams()
  if (opts?.strategy) q.set("strategy", opts.strategy)
  if (opts?.maxChars != null) q.set("max_chars", String(opts.maxChars))
  const qs = q.toString()
  const res = await authFetch(`/api/v1/documents/${documentUuid}/parse-preview${qs ? `?${qs}` : ""}`)
  if (!res.ok) await throwOnError(res, "파싱 미리보기 실패")
  return res.json()
}

/** 청킹 전(전문)/후(청크) 비교 — 저장·임베딩 없이 재파싱+재청킹. 전략·크기·오버랩 override 가능. */
export async function chunkPreviewDocument(
  documentUuid: string,
  opts?: {
    parseStrategy?: string
    strategy?: string
    chunkSize?: number
    chunkOverlap?: number
    chunkUnit?: string
    maxChars?: number
  }
): Promise<ChunkPreview> {
  const q = new URLSearchParams()
  if (opts?.parseStrategy) q.set("parse_strategy", opts.parseStrategy)
  if (opts?.strategy) q.set("strategy", opts.strategy)
  if (opts?.chunkSize != null) q.set("chunk_size", String(opts.chunkSize))
  if (opts?.chunkOverlap != null) q.set("chunk_overlap", String(opts.chunkOverlap))
  if (opts?.chunkUnit) q.set("chunk_unit", opts.chunkUnit)
  if (opts?.maxChars != null) q.set("max_chars", String(opts.maxChars))
  const qs = q.toString()
  const res = await authFetch(`/api/v1/documents/${documentUuid}/chunk-preview${qs ? `?${qs}` : ""}`)
  if (!res.ok) await throwOnError(res, "청킹 미리보기 실패")
  return res.json()
}

/** 드래프트 인제스천 파이프라인(보강 transform)으로 미리보기 — 저장·재인덱싱 없이. */
export async function previewPipeline(
  documentUuid: string,
  draft: {
    post_parse?: { id: string; config?: Record<string, unknown> }[]
    post_chunk?: { id: string; config?: Record<string, unknown> }[]
    parse_strategy?: string
    strategy?: string
    max_chars?: number
  }
): Promise<ChunkPreview> {
  const res = await authFetch(`/api/v1/documents/${documentUuid}/chunk-preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(draft),
  })
  if (!res.ok) await throwOnError(res, "파이프라인 미리보기 실패")
  return res.json()
}

/** 잡이 succeeded/failed 가 될 때까지 폴링한다(onTick 으로 진행률 콜백). */
export async function pollJob(
  jobId: string,
  onTick: (job: IngestionJob) => void,
  opts?: { intervalMs?: number; timeoutMs?: number }
): Promise<IngestionJob> {
  const interval = opts?.intervalMs ?? 1000
  const timeout = opts?.timeoutMs ?? 120_000
  const start = Date.now()
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const job = await getJob(jobId)
    onTick(job)
    if (job.status === "succeeded" || job.status === "failed") return job
    if (Date.now() - start > timeout) return job
    await new Promise((r) => setTimeout(r, interval))
  }
}
