// 파인튜닝 학습 데이터셋 REST 클라이언트.

import { authFetch, throwOnError } from "@/features/auth/auth-fetch"
import type {
  FtBuilderResult,
  FtDataset,
  FtExample,
  FtGlossaryTerm,
  FtJob,
  FtManifest,
  FtModel,
  FtSplit,
  FtTask,
} from "./data/schema"

const BASE = "/api/v1/finetune"

export async function listDatasets(): Promise<FtDataset[]> {
  const res = await authFetch(`${BASE}/datasets`)
  if (!res.ok) await throwOnError(res, "데이터셋 조회 실패")
  return res.json()
}

// 외부 노출 식별자는 UUID(dataset_id/job_id/model_id). 내부 PK(id)는 응답에 함께 온다.
export async function getDataset(datasetUuid: string): Promise<FtDataset> {
  const res = await authFetch(`${BASE}/datasets/${datasetUuid}`)
  if (!res.ok) await throwOnError(res, "데이터셋 조회 실패")
  return res.json()
}

export async function createDataset(input: {
  name: string
  description?: string | null
  base_collection_id?: number | null
  base_model?: string | null
  task?: FtTask
  prompt_format?: "e5" | "none"
}): Promise<FtDataset> {
  const res = await authFetch(`${BASE}/datasets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "데이터셋 생성 실패")
  return res.json()
}

export async function deleteDataset(id: number): Promise<void> {
  const res = await authFetch(`${BASE}/datasets/${id}`, { method: "DELETE" })
  if (!res.ok) await throwOnError(res, "데이터셋 삭제 실패")
}

export async function listExamples(datasetId: number, split?: FtSplit): Promise<FtExample[]> {
  const qs = split ? `?split=${split}` : ""
  const res = await authFetch(`${BASE}/datasets/${datasetId}/examples${qs}`)
  if (!res.ok) await throwOnError(res, "예시 조회 실패")
  return res.json()
}

export async function addExample(
  datasetId: number,
  input: {
    query: string
    positive: string
    negatives: string[]
    split: FtSplit
    source?: string
  },
): Promise<FtExample> {
  const res = await authFetch(`${BASE}/datasets/${datasetId}/examples`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "예시 추가 실패")
  return res.json()
}

export async function deleteExample(exampleUuid: string): Promise<void> {
  const res = await authFetch(`${BASE}/examples/${exampleUuid}`, { method: "DELETE" })
  if (!res.ok) await throwOnError(res, "예시 삭제 실패")
}

export async function getManifest(datasetId: number): Promise<FtManifest> {
  const res = await authFetch(`${BASE}/datasets/${datasetId}/manifest`)
  if (!res.ok) await throwOnError(res, "매니페스트 조회 실패")
  return res.json()
}

/** train|valid 를 JSONL 파일로 내려받는다(test 는 홀드아웃이라 내보내기 불가). */
export async function downloadExport(datasetId: number, split: "train" | "valid"): Promise<void> {
  const res = await authFetch(`${BASE}/datasets/${datasetId}/export/${split}`)
  if (!res.ok) await throwOnError(res, "내보내기 실패")
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = `${split}.jsonl`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// ---------------------------------------------------------------------------
// 학습 작업(Job)
// ---------------------------------------------------------------------------

export async function listJobs(datasetId?: number): Promise<FtJob[]> {
  const qs = datasetId != null ? `?dataset_id=${datasetId}` : ""
  const res = await authFetch(`${BASE}/jobs${qs}`)
  if (!res.ok) await throwOnError(res, "작업 조회 실패")
  return res.json()
}

export async function getJob(jobUuid: string): Promise<FtJob> {
  const res = await authFetch(`${BASE}/jobs/${jobUuid}`)
  if (!res.ok) await throwOnError(res, "작업 조회 실패")
  return res.json()
}

export async function createJob(input: {
  dataset_id: number
  task?: FtTask
  base_model?: string | null
  epochs?: number
  batch_size?: number
  lr?: number
  max_negatives?: number
}): Promise<FtJob> {
  const res = await authFetch(`${BASE}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "작업 생성 실패")
  return res.json()
}

export async function cancelJob(id: number): Promise<FtJob> {
  const res = await authFetch(`${BASE}/jobs/${id}/cancel`, { method: "POST" })
  if (!res.ok) await throwOnError(res, "작업 취소 실패")
  return res.json()
}

export async function deleteJob(id: number): Promise<void> {
  const res = await authFetch(`${BASE}/jobs/${id}`, { method: "DELETE" })
  if (!res.ok) await throwOnError(res, "작업 삭제 실패")
}

/** 성공한 학습 작업의 아티팩트를 등록 모델로 승격한다. */
export async function registerFromJob(jobId: number, name?: string): Promise<FtModel> {
  const qs = name ? `?name=${encodeURIComponent(name)}` : ""
  const res = await authFetch(`${BASE}/jobs/${jobId}/register${qs}`, { method: "POST" })
  if (!res.ok) await throwOnError(res, "모델 등록 실패")
  return res.json()
}

// ---------------------------------------------------------------------------
// 모델 레지스트리(Model)
// ---------------------------------------------------------------------------

export async function listModels(): Promise<FtModel[]> {
  const res = await authFetch(`${BASE}/models`)
  if (!res.ok) await throwOnError(res, "모델 조회 실패")
  return res.json()
}

export async function getModel(modelUuid: string): Promise<FtModel> {
  const res = await authFetch(`${BASE}/models/${modelUuid}`)
  if (!res.ok) await throwOnError(res, "모델 조회 실패")
  return res.json()
}

export async function registerModel(input: {
  name: string
  task?: FtTask
  base_model?: string | null
  embedding_dim?: number | null
  format?: string | null
  artifact_uri?: string | null
  serving_url?: string | null
}): Promise<FtModel> {
  const res = await authFetch(`${BASE}/models`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "모델 등록 실패")
  return res.json()
}

export async function updateModel(
  id: number,
  input: { serving_url?: string | null; status?: string; published_uri?: string | null },
): Promise<FtModel> {
  const res = await authFetch(`${BASE}/models/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "모델 갱신 실패")
  return res.json()
}

export async function deleteModel(id: number): Promise<void> {
  const res = await authFetch(`${BASE}/models/${id}`, { method: "DELETE" })
  if (!res.ok) await throwOnError(res, "모델 삭제 실패")
}

// ---------------------------------------------------------------------------
// 용어 사전(Glossary)
// ---------------------------------------------------------------------------

export async function listTerms(domain?: string): Promise<FtGlossaryTerm[]> {
  const qs = domain ? `?domain=${encodeURIComponent(domain)}` : ""
  const res = await authFetch(`${BASE}/glossary${qs}`)
  if (!res.ok) await throwOnError(res, "용어 조회 실패")
  return res.json()
}

export async function createTerm(input: {
  term: string
  definition?: string | null
  synonyms: string[]
  domain?: string | null
}): Promise<FtGlossaryTerm> {
  const res = await authFetch(`${BASE}/glossary`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "용어 추가 실패")
  return res.json()
}

export async function updateTerm(
  id: number,
  input: { term?: string; definition?: string | null; synonyms?: string[]; domain?: string | null },
): Promise<FtGlossaryTerm> {
  const res = await authFetch(`${BASE}/glossary/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "용어 수정 실패")
  return res.json()
}

export async function deleteTerm(id: number): Promise<void> {
  const res = await authFetch(`${BASE}/glossary/${id}`, { method: "DELETE" })
  if (!res.ok) await throwOnError(res, "용어 삭제 실패")
}

// ---------------------------------------------------------------------------
// 빌더 / 마이닝
// ---------------------------------------------------------------------------

export async function buildFromEval(
  datasetId: number,
  input: { eval_dataset_id: number; split?: FtSplit; top_k?: number; max_negatives?: number },
): Promise<FtBuilderResult> {
  const res = await authFetch(`${BASE}/datasets/${datasetId}/build-from-eval`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "빌드 실패")
  return res.json()
}

export async function mineNegatives(
  datasetId: number,
  input: { per_example?: number; top_k?: number; only_missing?: boolean },
): Promise<FtBuilderResult> {
  const res = await authFetch(`${BASE}/datasets/${datasetId}/mine-negatives`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "마이닝 실패")
  return res.json()
}
