// 파이프라인 REST 클라이언트.

import { authFetch, throwOnError } from "@/features/auth/auth-fetch"
import type { CompareResult, Diff, Pipeline, PipelineConfig, PipelineVersion } from "./data/schema"

const BASE = "/api/v1/pipelines"

export async function listPipelines(): Promise<Pipeline[]> {
  const res = await authFetch(BASE)
  if (!res.ok) await throwOnError(res, "파이프라인 조회 실패")
  return res.json()
}

export async function createPipeline(input: {
  name: string
  description?: string | null
  stage?: string
  config?: PipelineConfig
}): Promise<Pipeline> {
  const res = await authFetch(BASE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "파이프라인 생성 실패")
  return res.json()
}

// 외부 노출 식별자는 파이프라인 UUID(pipeline_id). 내부 PK(id)는 응답에 함께 온다.
export async function getPipeline(pipelineUuid: string): Promise<Pipeline> {
  const res = await authFetch(`${BASE}/${pipelineUuid}`)
  if (!res.ok) await throwOnError(res, "파이프라인 조회 실패")
  return res.json()
}

export async function updateConfig(id: number, config: PipelineConfig, note?: string): Promise<Pipeline> {
  const res = await authFetch(`${BASE}/${id}/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config, note }),
  })
  if (!res.ok) await throwOnError(res, "설정 저장 실패")
  return res.json()
}

/** stage / description 등 메타데이터 수정(버전 생성 없음). */
export async function updateMeta(
  id: number,
  meta: { stage?: string; description?: string | null }
): Promise<Pipeline> {
  const res = await authFetch(`${BASE}/${id}/meta`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(meta),
  })
  if (!res.ok) await throwOnError(res, "메타데이터 저장 실패")
  return res.json()
}

export async function activateVersion(id: number, version: number): Promise<Pipeline> {
  const res = await authFetch(`${BASE}/${id}/activate/${version}`, { method: "POST" })
  if (!res.ok) await throwOnError(res, "버전 활성화 실패")
  return res.json()
}

export async function deletePipeline(id: number): Promise<void> {
  const res = await authFetch(`${BASE}/${id}`, { method: "DELETE" })
  if (!res.ok) await throwOnError(res, "파이프라인 삭제 실패")
}

export async function listVersions(id: number): Promise<PipelineVersion[]> {
  const res = await authFetch(`${BASE}/${id}/versions`)
  if (!res.ok) await throwOnError(res, "버전 조회 실패")
  return res.json()
}

export async function getDiff(id: number, from: number, to: number): Promise<Diff> {
  const res = await authFetch(`${BASE}/${id}/diff?from=${from}&to=${to}`)
  if (!res.ok) await throwOnError(res, "diff 조회 실패")
  return res.json()
}

export async function compare(
  id: number,
  body: { query: string; collection_id: number; version_a: number; version_b: number }
): Promise<CompareResult> {
  const res = await authFetch(`${BASE}/${id}/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) await throwOnError(res, "비교 실패")
  return res.json()
}
