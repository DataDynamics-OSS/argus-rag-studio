// 문서 라우팅 REST 클라이언트 — 라우터 레지스트리·정책 버전 관리·미리보기·인테이크(multipart).

import { authFetch, throwOnError } from "@/features/auth/auth-fetch"
import type {
  IntakeResult,
  ReferencePreviewRequest,
  RouterInfo,
  RoutePreviewResult,
  RoutingPolicy,
  RoutingPolicyConfig,
  RoutingPolicyVersion,
  ScanIntakeRequest,
  ScanIntakeResult,
} from "./data/schema"

const BASE = "/api/v1/routing"

/** 정책에 끼울 수 있는 라우터 레지스트리(정책 빌더용). */
export async function listRouters(): Promise<{ routers: RouterInfo[] }> {
  const res = await authFetch(`${BASE}/routers`)
  if (!res.ok) await throwOnError(res, "라우터 목록 조회 실패")
  return res.json()
}

/** 활성 라우팅 정책(단일 'default'). 없으면 백엔드가 기본값으로 생성해 반환. */
export async function getPolicy(): Promise<RoutingPolicy> {
  const res = await authFetch(`${BASE}/policy`)
  if (!res.ok) await throwOnError(res, "정책 조회 실패")
  return res.json()
}

/** 정책 수정 — 새 버전을 생성하고 active 로 만든다(append-only). */
export async function updatePolicy(
  config: RoutingPolicyConfig,
  note?: string
): Promise<RoutingPolicy> {
  const res = await authFetch(`${BASE}/policy`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config, note }),
  })
  if (!res.ok) await throwOnError(res, "정책 저장 실패")
  return res.json()
}

export async function listPolicyVersions(): Promise<RoutingPolicyVersion[]> {
  const res = await authFetch(`${BASE}/policy/versions`)
  if (!res.ok) await throwOnError(res, "버전 조회 실패")
  return res.json()
}

/** active 포인터를 지정 버전으로 이동(롤백). */
export async function rollbackPolicy(version: number): Promise<RoutingPolicy> {
  const res = await authFetch(`${BASE}/policy/rollback?version=${version}`, { method: "POST" })
  if (!res.ok) await throwOnError(res, "버전 롤백 실패")
  return res.json()
}

/** 저장 없이 "이 파일이 어디로 라우팅될지" + 라우터별 trace 를 받는다. */
export async function routePreview(file: File): Promise<RoutePreviewResult> {
  const form = new FormData()
  form.append("file", file)
  // Content-Type 은 브라우저가 multipart boundary 와 함께 자동 설정하므로 지정하지 않는다.
  const res = await authFetch(`${BASE}/route-preview`, { method: "POST", body: form })
  if (!res.ok) await throwOnError(res, "라우팅 미리보기 실패")
  return res.json()
}

/** 컬렉션 미지정 업로드 → 라우팅 → 등록 → 인제스천 잡 enqueue. */
export async function intake(file: File): Promise<IntakeResult> {
  const form = new FormData()
  form.append("file", file)
  const res = await authFetch(`${BASE}/intake`, { method: "POST", body: form })
  if (!res.ok) await throwOnError(res, "인테이크 실패")
  return res.json()
}

/** 등록된 스토리지 소스의 문서를 경로로 가져와(pull) → 라우팅 → 등록 → 잡 enqueue. */
export async function intakeByReference(sourceId: string, path: string): Promise<IntakeResult> {
  const res = await authFetch(`${BASE}/intake-by-reference`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_id: sourceId, path }),
  })
  if (!res.ok) await throwOnError(res, "참조 인테이크 실패")
  return res.json()
}

/** 소스 폴더(prefix) 하위 파일 일괄 인테이크(드롭존). dry_run=true 면 시뮬레이션만. */
export async function intakeScan(req: ScanIntakeRequest): Promise<ScanIntakeResult> {
  const res = await authFetch(`${BASE}/intake-scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  })
  if (!res.ok) await throwOnError(res, "폴더 일괄 인테이크 실패")
  return res.json()
}

/** 소스 문서(또는 경로 문자열만)로 라우팅 시뮬레이션 — 저장 없음. */
export async function routePreviewByReference(
  req: ReferencePreviewRequest
): Promise<RoutePreviewResult> {
  const res = await authFetch(`${BASE}/route-preview-by-reference`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  })
  if (!res.ok) await throwOnError(res, "경로 미리보기 실패")
  return res.json()
}

// ── 검토 큐(Phase 3 — 결정 로그 조회·확인/재배정) ───────────────────────────

export type RoutingDecisionItem = {
  id: number
  decision_id: string
  document_id: number
  document_uuid: string | null
  document_name: string | null
  document_status: string | null
  collection_id: number | null
  collection_name: string | null
  confidence: number
  mode: string | null
  matched_router: string | null
  fallback_used: boolean
  review: boolean
  policy_version: number | null
  trace: { router: string; candidates: { collection_id: number; score: number; reason: string }[] }[]
  created_by: string | null
  created_at: string
  reviewed_at: string | null
  reviewed_by: string | null
  corrected_collection_id: number | null
  corrected_collection_name: string | null
}

export type RoutingDecisionList = {
  total: number
  pending_review: number // review=true 전체 건수(탭 배지용)
  page: number
  page_size: number
  items: RoutingDecisionItem[]
}

/** 라우팅 결정 로그(최신순) — reviewOnly=true 가 검토 큐. */
export async function listRoutingDecisions(opts?: {
  reviewOnly?: boolean
  page?: number
  pageSize?: number
}): Promise<RoutingDecisionList> {
  const qs = new URLSearchParams({
    review_only: String(opts?.reviewOnly ?? true),
    page: String(opts?.page ?? 1),
    page_size: String(opts?.pageSize ?? 20),
  })
  const res = await authFetch(`${BASE}/decisions?${qs}`)
  if (!res.ok) await throwOnError(res, "결정 로그 조회 실패")
  return res.json()
}

/** 검토 처리 — collectionId 를 주면 재배정(문서 이동+재색인), 없으면 확인만. */
export async function resolveRoutingDecision(
  decisionId: string,
  collectionId?: number
): Promise<{ decision: RoutingDecisionItem; reassigned: boolean; job_id: string | null }> {
  const res = await authFetch(`${BASE}/decisions/${decisionId}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ collection_id: collectionId ?? null }),
  })
  if (!res.ok) await throwOnError(res, "검토 처리 실패")
  return res.json()
}

// ── 수정 피드백 루프(재배정 내역 → 규칙 제안) ───────────────────────────────

export type FeedbackSuggestion = {
  router: string // extension_rule | filename_rule | metadata_match | path_rule
  kind: string // extension | filename_token | doc_type | source_path
  value: string
  field: string | null
  storage: string | null
  collection_id: number
  collection_name: string | null
  support: number // 이 값이 해당 컬렉션으로 수정된 횟수
  total: number
  purity: number
  samples: string[]
}

export type FeedbackSuggestions = {
  total_corrections: number
  already_covered: number
  suggestions: FeedbackSuggestion[]
}

/** 수동 재배정 내역 기반 규칙 제안 — 정책에 이미 있는 매핑은 제외돼 온다. */
export async function listFeedbackSuggestions(): Promise<FeedbackSuggestions> {
  const res = await authFetch(`${BASE}/feedback/suggestions`)
  if (!res.ok) await throwOnError(res, "규칙 제안 조회 실패")
  return res.json()
}

/** 제안 1건을 활성 정책에 반영 — 새 버전 생성(append-only, 롤백 가능). */
export async function applyFeedbackSuggestion(s: FeedbackSuggestion): Promise<RoutingPolicy> {
  const res = await authFetch(`${BASE}/feedback/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      router: s.router,
      value: s.value,
      collection_id: s.collection_id,
      field: s.field,
      storage: s.storage,
      support: s.support,
    }),
  })
  if (!res.ok) await throwOnError(res, "제안 반영 실패")
  return res.json()
}

// ── 라우팅 디스크립터(Phase 2 — 내용 임베딩 라우터) ─────────────────────────

export type RoutingProfileStatus = {
  collection_id: number
  name: string
  built: boolean
  stale: boolean // 전역 임베딩 설정 변경으로 재계산 필요
  source: string | null // chunks | description
  sample_count: number
  built_at: string | null
  space_model: string | null
  dim: number // centroid 차원(라우팅 공간)
  centroid_preview: number[] // 계산된 벡터 앞 16개(표시용)
}

export type ProfileRecomputeResult = {
  collection_id: number
  name: string
  status: string // built | empty | error
  source: string | null
  sample_count: number
  error?: string | null
}

/** 컬렉션별 디스크립터 상태(미계산/유효/stale). */
export async function listRoutingProfiles(): Promise<RoutingProfileStatus[]> {
  const res = await authFetch(`${BASE}/profiles`)
  if (!res.ok) await throwOnError(res, "디스크립터 조회 실패")
  return res.json()
}

/** 디스크립터 재계산(전체 또는 한 컬렉션) — 동기, 수 초~수십 초. */
export async function recomputeRoutingProfiles(
  collectionId?: number
): Promise<ProfileRecomputeResult[]> {
  const qs = collectionId != null ? `?collection_id=${collectionId}` : ""
  const res = await authFetch(`${BASE}/profiles/recompute${qs}`, { method: "POST" })
  if (!res.ok) await throwOnError(res, "디스크립터 재계산 실패")
  return res.json()
}
