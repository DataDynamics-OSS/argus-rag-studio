// 평가 REST 클라이언트.

import { authFetch, throwOnError } from "@/features/auth/auth-fetch"
import type {
  EvalDataset,
  EvalItem,
  EvalResult,
  EvalRun,
  EvalSweep,
  Leaderboard,
  SweepApplyResult,
  SweepSearchSpace,
} from "./data/schema"

const BASE = "/api/v1/eval"

export async function listDatasets(): Promise<EvalDataset[]> {
  const res = await authFetch(`${BASE}/datasets`)
  if (!res.ok) await throwOnError(res, "데이터셋 조회 실패")
  return res.json()
}

export async function createDataset(input: {
  name: string
  description?: string | null
  collection_id?: number | null
}): Promise<EvalDataset> {
  const res = await authFetch(`${BASE}/datasets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "데이터셋 생성 실패")
  return res.json()
}

// 외부 노출 식별자는 데이터셋 UUID(dataset_id). 내부 PK(id)는 응답에 함께 온다.
export async function getDataset(datasetUuid: string): Promise<EvalDataset> {
  const res = await authFetch(`${BASE}/datasets/${datasetUuid}`)
  if (!res.ok) await throwOnError(res, "데이터셋 조회 실패")
  return res.json()
}

export async function deleteDataset(id: number): Promise<void> {
  const res = await authFetch(`${BASE}/datasets/${id}`, { method: "DELETE" })
  if (!res.ok) await throwOnError(res, "데이터셋 삭제 실패")
}

export async function listItems(datasetId: number): Promise<EvalItem[]> {
  const res = await authFetch(`${BASE}/datasets/${datasetId}/items`)
  if (!res.ok) await throwOnError(res, "항목 조회 실패")
  return res.json()
}

export async function addItem(
  datasetId: number,
  input: { question: string; expected_answer?: string | null; expected_sources: string[] }
): Promise<EvalItem> {
  const res = await authFetch(`${BASE}/datasets/${datasetId}/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "항목 추가 실패")
  return res.json()
}

export async function deleteItem(itemUuid: string): Promise<void> {
  const res = await authFetch(`${BASE}/items/${itemUuid}`, { method: "DELETE" })
  if (!res.ok) await throwOnError(res, "항목 삭제 실패")
}

export async function createRun(
  datasetId: number,
  input: { collection_id?: number | null; mode: string; rerank: boolean; judge: boolean; top_k?: number; pipeline_id?: number | null }
): Promise<EvalRun> {
  const res = await authFetch(`${BASE}/datasets/${datasetId}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "평가 실행 실패")
  return res.json()
}

export async function listRuns(datasetId: number): Promise<EvalRun[]> {
  const res = await authFetch(`${BASE}/datasets/${datasetId}/runs`)
  if (!res.ok) await throwOnError(res, "Run 조회 실패")
  return res.json()
}

/** 전역 평가 런 목록(최신순) — 잡 모니터링용. */
export async function listAllRuns(): Promise<EvalRun[]> {
  const res = await authFetch(`${BASE}/runs`)
  if (!res.ok) await throwOnError(res, "평가 런 목록 조회 실패")
  return res.json()
}

/** 전역 스윕 목록(최신순) — 잡 모니터링용. */
export async function listAllSweeps(): Promise<EvalSweep[]> {
  const res = await authFetch(`${BASE}/sweeps`)
  if (!res.ok) await throwOnError(res, "스윕 목록 조회 실패")
  return res.json()
}

export async function getRun(runId: string): Promise<EvalRun> {
  const res = await authFetch(`${BASE}/runs/${runId}`)
  if (!res.ok) await throwOnError(res, "Run 조회 실패")
  return res.json()
}

export async function listResults(runId: string): Promise<EvalResult[]> {
  const res = await authFetch(`${BASE}/runs/${runId}/results`)
  if (!res.ok) await throwOnError(res, "결과 조회 실패")
  return res.json()
}

// ── 설정 스윕 / 리더보드 ──────────────────────────────────────────────
export async function createSweep(
  datasetId: number,
  input: {
    name: string
    base_collection_id?: number | null
    search_space: SweepSearchSpace
    primary_metric: string
    judge: boolean
    judge_top_n?: number | null
    holdout_ratio?: number
    max_runs: number
  }
): Promise<EvalSweep> {
  const res = await authFetch(`${BASE}/datasets/${datasetId}/sweeps`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "스윕 생성 실패")
  return res.json()
}

export async function listSweeps(datasetId: number): Promise<EvalSweep[]> {
  const res = await authFetch(`${BASE}/datasets/${datasetId}/sweeps`)
  if (!res.ok) await throwOnError(res, "스윕 조회 실패")
  return res.json()
}

export async function getLeaderboard(sweepId: string): Promise<Leaderboard> {
  const res = await authFetch(`${BASE}/sweeps/${sweepId}/leaderboard`)
  if (!res.ok) await throwOnError(res, "리더보드 조회 실패")
  return res.json()
}

export async function cancelSweep(sweepId: string): Promise<EvalSweep> {
  const res = await authFetch(`${BASE}/sweeps/${sweepId}/cancel`, { method: "POST" })
  if (!res.ok) await throwOnError(res, "스윕 취소 실패")
  return res.json()
}

export async function applySweepConfig(
  sweepId: string,
  runId: string
): Promise<SweepApplyResult> {
  const res = await authFetch(`${BASE}/sweeps/${sweepId}/apply/${runId}`, { method: "POST" })
  if (!res.ok) await throwOnError(res, "설정 적용 실패")
  return res.json()
}
