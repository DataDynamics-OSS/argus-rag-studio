// 관측 REST 클라이언트.

import { authFetch, throwOnError } from "@/features/auth/auth-fetch"
import type { ObsStats, Trace } from "./data/schema"

export async function getStats(): Promise<ObsStats> {
  const res = await authFetch("/api/v1/observability/stats")
  if (!res.ok) await throwOnError(res, "통계 조회 실패")
  return res.json()
}

export async function listTraces(params?: {
  kind?: string
  status?: string
  collection_id?: number
  limit?: number
}): Promise<Trace[]> {
  const q = new URLSearchParams()
  if (params?.kind) q.set("kind", params.kind)
  if (params?.status) q.set("status", params.status)
  if (params?.collection_id != null) q.set("collection_id", String(params.collection_id))
  q.set("limit", String(params?.limit ?? 50))
  const res = await authFetch(`/api/v1/observability/traces?${q.toString()}`)
  if (!res.ok) await throwOnError(res, "트레이스 조회 실패")
  return res.json()
}
