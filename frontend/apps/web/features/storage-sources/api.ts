// 스토리지 소스 REST 클라이언트 — 소스 CRUD·연결 테스트·경로 브라우징(인테이크 피커).

import { authFetch, throwOnError } from "@/features/auth/auth-fetch"
import type {
  SourceListResult,
  SourceTestResult,
  StorageSource,
  StorageSourceCreate,
  StorageSourceUpdate,
} from "./data/schema"

const BASE = "/api/v1/storage-sources"

export async function listSources(): Promise<StorageSource[]> {
  const res = await authFetch(BASE)
  if (!res.ok) await throwOnError(res, "소스 목록 조회 실패")
  return res.json()
}

export async function createSource(payload: StorageSourceCreate): Promise<StorageSource> {
  const res = await authFetch(BASE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!res.ok) await throwOnError(res, "소스 등록 실패")
  return res.json()
}

export async function updateSource(
  sourceId: string,
  payload: StorageSourceUpdate
): Promise<StorageSource> {
  const res = await authFetch(`${BASE}/${sourceId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!res.ok) await throwOnError(res, "소스 수정 실패")
  return res.json()
}

export async function deleteSource(sourceId: string): Promise<void> {
  const res = await authFetch(`${BASE}/${sourceId}`, { method: "DELETE" })
  if (!res.ok) await throwOnError(res, "소스 삭제 실패")
}

/** 연결 검증 — 루트 list 1회로 접근 가능/자격증명 확인. */
export async function testSource(sourceId: string): Promise<SourceTestResult> {
  const res = await authFetch(`${BASE}/${sourceId}/test`, { method: "POST" })
  if (!res.ok) await throwOnError(res, "소스 테스트 실패")
  return res.json()
}

/** 소스 내 경로 브라우징 — 인테이크 '소스에서 가져오기' 피커용. */
export async function listSourceDirectory(
  sourceId: string,
  prefix = "",
  recursive = false
): Promise<SourceListResult> {
  const qs = new URLSearchParams({ prefix, recursive: String(recursive) })
  const res = await authFetch(`${BASE}/${sourceId}/list?${qs}`)
  if (!res.ok) await throwOnError(res, "경로 조회 실패")
  return res.json()
}

// ── 소스 워치(자동 수집 — 드롭존 무인화) ──────────────────────────────────────

export type SourceWatch = {
  watch_id: string
  source_id: string
  source_name: string
  name: string
  prefix: string
  recursive: boolean
  interval_seconds: number
  enabled: boolean
  next_run_at?: string | null
  last_run_at?: string | null
  last_status?: string | null // ok | error | null(미실행)
  last_error?: string | null
  last_counts: Record<string, number>
  consecutive_failures: number
  created_by?: string | null
  created_at?: string | null
}

export type SourceWatchRun = {
  started_at: string
  finished_at?: string | null
  scanned: number
  skipped: number
  counts: Record<string, number>
  truncated: boolean
  error?: string | null
}

export type SourceWatchCreate = {
  source_id: string
  name: string
  prefix?: string
  recursive?: boolean
  interval_seconds?: number
  enabled?: boolean
}

const WATCH_BASE = "/api/v1/source-watches"

export async function listWatches(): Promise<SourceWatch[]> {
  const res = await authFetch(WATCH_BASE)
  if (!res.ok) await throwOnError(res, "워치 목록 조회 실패")
  return res.json()
}

export async function createWatch(payload: SourceWatchCreate): Promise<SourceWatch> {
  const res = await authFetch(WATCH_BASE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!res.ok) await throwOnError(res, "워치 등록 실패")
  return res.json()
}

export async function updateWatch(
  watchId: string,
  payload: Partial<Omit<SourceWatchCreate, "source_id">>
): Promise<SourceWatch> {
  const res = await authFetch(`${WATCH_BASE}/${watchId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!res.ok) await throwOnError(res, "워치 수정 실패")
  return res.json()
}

export async function deleteWatch(watchId: string): Promise<void> {
  const res = await authFetch(`${WATCH_BASE}/${watchId}`, { method: "DELETE" })
  if (!res.ok) await throwOnError(res, "워치 삭제 실패")
}

/** 지금 실행 — 워처 루프가 다음 tick(기본 15초 내)에 집어간다. */
export async function runWatchNow(watchId: string): Promise<void> {
  const res = await authFetch(`${WATCH_BASE}/${watchId}/run`, { method: "POST" })
  if (!res.ok) await throwOnError(res, "실행 요청 실패")
}

export async function listWatchRuns(watchId: string): Promise<SourceWatchRun[]> {
  const res = await authFetch(`${WATCH_BASE}/${watchId}/runs`)
  if (!res.ok) await throwOnError(res, "실행 이력 조회 실패")
  return res.json()
}
