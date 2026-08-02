// 문서 라우팅 도메인 타입 — 백엔드 routing/schemas.py 와 매칭.

export type RouterInfo = {
  id: string
  label: string
  description: string
  config_schema: Record<string, unknown>
  available: boolean
}

export type RoutingMode = "first_match" | "weighted_vote"

export type RoutingStage = {
  id: string
  config: Record<string, unknown>
  weight: number
  min_confidence: number
}

export type RoutingPolicyConfig = {
  mode: RoutingMode
  stages: RoutingStage[]
  fallback_collection_id: number | null
  review_below: number
}

export type RoutingPolicy = {
  id: number
  policy_id: string
  name: string
  description: string | null
  active_version: number
  version_count: number
  config: RoutingPolicyConfig
  created_by: string | null
  created_at: string
  updated_at: string
}

export type RoutingPolicyVersion = {
  version: number
  config: RoutingPolicyConfig
  note: string | null
  created_by: string | null
  created_at: string
}

// --- 라우팅 결정(미리보기/인테이크 공통) ---

export type RouteCandidate = { collection_id: number; score: number; reason: string }
export type RouteTraceEntry = { router: string; candidates: RouteCandidate[] }

export type RouteDecision = {
  collection_id: number | null
  collection_name: string | null
  confidence: number
  mode: string
  matched_router: string | null
  fallback_used: boolean
  review: boolean
  policy_version: number | null
  trace: RouteTraceEntry[]
}

export type RoutePreviewResult = {
  filename: string
  metadata: Record<string, unknown>
  decision: RouteDecision
  source_path?: string | null // 참조/경로 시뮬레이션일 때 소스 내 경로
  storage?: string | null     // 참조/경로 시뮬레이션일 때 소스 논리명
}

/** 참조/경로 미리보기 요청 — path_only=true 면 소스 접근 없이 경로 신호만으로 시뮬레이션. */
export type ReferencePreviewRequest = {
  path: string
  source_id?: string | null
  storage?: string | null
  path_only?: boolean
}

export type IntakeResult = {
  document_id: number
  document_uuid: string
  name: string
  status: string
  job_id: string
  decision: RouteDecision
}

// --- 폴더 일괄 인테이크(드롭존) ---

export type ScanIntakeRequest = {
  source_id: string
  prefix: string
  recursive: boolean
  dry_run: boolean
  limit?: number
}

export type ScanItemStatus = "routed" | "duplicate" | "no_route" | "failed"

export type ScanItemResult = {
  path: string
  status: ScanItemStatus
  collection_id: number | null
  collection_name: string | null
  confidence: number | null
  review: boolean
  fallback_used: boolean
  matched_router: string | null
  document_id: number | null
  job_id: string | null
  detail: string | null
}

export type ScanIntakeResult = {
  source_name: string
  prefix: string
  recursive: boolean
  dry_run: boolean
  scanned: number
  truncated: boolean
  counts: Record<string, number>
  items: ScanItemResult[]
}
