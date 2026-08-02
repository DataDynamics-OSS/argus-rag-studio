// 모델 레지스트리 API(/api/v1/models) — 모델 관리 화면·배포 모델 콤보가 사용.
// 설계 design/model-registry.md. 등록/수정/삭제는 관리자 전용.
import { authFetch, throwOnError } from "@/features/auth"

const BASE = "/api/v1/models"

export type ModelKind = "embedding" | "reranker" | "vlm" | "detection"

export type RegistryModel = {
  model_id: string
  kind: ModelKind
  name: string
  repo: string
  revision: string
  source: string // hf | paddle(수동 반입)
  target: string // hf-cache | flat
  note: string
  enabled: boolean
  builtin: boolean
  max_len: number | null
  approx_gb: number | null
  // Model Repository(argus-models) 보유 현황
  available: boolean
  revisions: string[]
}

// Model Repository 에는 있지만 레지스트리에 없는 반입분
export type UnlistedModel = { key: string; revisions: string[] }

export type ModelCatalog = {
  models: RegistryModel[]
  unlisted: UnlistedModel[]
  bucket: string
}

export async function listModels(kind?: ModelKind): Promise<ModelCatalog> {
  const res = await authFetch(kind ? `${BASE}?kind=${kind}` : BASE)
  if (!res.ok) await throwOnError(res, "모델 목록 조회 실패")
  return res.json()
}

export type ModelCreateIn = {
  kind: ModelKind
  name: string
  repo: string
  revision?: string
  note?: string
  max_len?: number | null
  enabled?: boolean
}

export async function createModel(body: ModelCreateIn): Promise<RegistryModel> {
  const res = await authFetch(BASE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) await throwOnError(res, "모델 등록 실패")
  return res.json()
}

export type ModelUpdateIn = Partial<Omit<ModelCreateIn, "kind">>

export async function updateModel(modelId: string, body: ModelUpdateIn): Promise<RegistryModel> {
  const res = await authFetch(`${BASE}/${encodeURIComponent(modelId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) await throwOnError(res, "모델 수정 실패")
  return res.json()
}

export async function deleteModel(modelId: string): Promise<void> {
  const res = await authFetch(`${BASE}/${encodeURIComponent(modelId)}`, { method: "DELETE" })
  if (!res.ok) await throwOnError(res, "모델 삭제 실패")
}

// ── 서버에서 팩(온라인 개발망 편의) ──────────────────────────────────────────

export type PackJob = {
  model_id: string
  kind: string
  name: string
  repo: string
  revision: string
  status: "running" | "done" | "error"
  detail: string
  started_at: number
  finished_at: number | null
}

/** HF 도달성 — false(에어갭)면 서버 팩 버튼을 숨긴다. */
export async function checkOnline(): Promise<boolean> {
  const res = await authFetch(`${BASE}/online`)
  if (!res.ok) return false
  const d = await res.json()
  return !!d.online
}

export async function listPackJobs(): Promise<PackJob[]> {
  const res = await authFetch(`${BASE}/pack-jobs`)
  if (!res.ok) await throwOnError(res, "팩 잡 조회 실패")
  const d = await res.json()
  return d.jobs ?? []
}

export async function startPack(modelId: string): Promise<PackJob> {
  const res = await authFetch(`${BASE}/${encodeURIComponent(modelId)}/pack`, { method: "POST" })
  if (!res.ok) await throwOnError(res, "서버 팩 시작 실패")
  const d = await res.json()
  return d.job
}
