// 통합 배포 API(/api/v1/deploy) + 클러스터 등록 클라이언트. 설계 design/deploy-strategy.md.
import { authFetch, throwOnError } from "@/features/auth"

const BASE = "/api/v1/deploy"

export type ServiceKind = "worker" | "embedding" | "reranker" | "detection" | "hwp_render" | "vlm"

// VLM 모델 카탈로그(사전 정의 + 설정 image_classification.extra_models 추가분)
export type VlmModel = { name: string; repo: string; max_len: number; note: string; builtin: boolean }

export async function listVlmModels(): Promise<{ models: VlmModel[]; default: string }> {
  const res = await authFetch("/api/v1/deploy/vlm-models")
  if (!res.ok) await throwOnError(res, "VLM 모델 목록 조회 실패")
  return res.json()
}

// 모델 매니페스트 + 모델 저장소(argus-models) 보유 여부 — 에어갭 반입 관리.
export type CatalogModel = VlmModel & {
  kind: string
  source: string
  target?: string
  approx_gb?: number | null
  enabled?: boolean
  available: boolean
  revisions: string[]
}

// 매니페스트에 없는데 버킷에는 있는 반입분(임의 repo 팩)
export type UnlistedModel = { key: string; revisions: string[] }

export async function listModelCatalog(): Promise<{
  models: CatalogModel[]
  unlisted?: UnlistedModel[]
  bucket: string
}> {
  const res = await authFetch("/api/v1/deploy/model-catalog")
  if (!res.ok) await throwOnError(res, "모델 카탈로그 조회 실패")
  return res.json()
}

export type DeployTarget = {
  type: "agent_host" | "k8s"
  hostname?: string
  method?: "docker" | "systemd"
  cluster_id?: string
  namespace?: string
}

export type DeploySpec = {
  kind: ServiceKind
  replicas?: number
  variant?: string
  image?: string
  version?: string
  env?: Record<string, string>
  gpu?: boolean
  wire_settings?: boolean
  network?: string
  extra_hosts?: string[]
  db_url?: string
  os_endpoint?: string
  host_port?: number // 호스트 포트 오버라이드(docker 전용) — 기본 포트 점유 시
}

export type ManagedInstance = { id: string; state: string; node?: string | null }
export type ManagedService = {
  name: string
  kind: string
  runtime: "docker" | "systemd" | "k8s"
  desired_replicas: number
  ready_replicas: number
  state: string
  image?: string | null
  version?: string | null
  endpoint?: string | null
  started_at?: string | null
  exit_code?: number | null
  message?: string | null
  restart_count?: number | null
  health?: string | null
  cpu_percent?: number | null
  mem_percent?: number | null
  // worker 전용 — 워커 레지스트리 교차참조
  worker_alive?: boolean | null
  worker_status?: string | null
  worker_current_job?: string | null
  worker_processed_total?: number | null
  worker_mode?: string | null
  command?: string[]
  stats?: ServiceStats | null // heartbeat /stats 요약(overview 가 병합)
  instances: ManagedInstance[]
}

// heartbeat /stats 요약 — 서비스 관리 2행 상세(모델·디바이스·GPU·업타임).
export type ServiceStats = {
  model?: string | null
  models_loaded?: string[]
  device?: string | null
  uptime_seconds?: number | null
  server_version?: string | null
  cpu_percent?: number | null
  mem_percent?: number | null
  gpu?: { name?: string | null; utilization_percent?: number | null; mem_used_bytes?: number | null; mem_total_bytes?: number | null }[]
}

export type Cluster = {
  cluster_id: string
  name: string
  api_server: string
  verify_ssl: boolean
  default_namespace: string
  default_arch: string
  has_token: boolean
}

export type ClusterIn = {
  cluster_id: string
  name: string
  api_server: string
  token?: string
  ca_cert?: string
  verify_ssl?: boolean
  default_namespace?: string
  default_arch?: string
}

function targetQuery(t: DeployTarget): string {
  const q = new URLSearchParams({ type: t.type })
  if (t.hostname) q.set("hostname", t.hostname)
  if (t.method) q.set("method", t.method)
  if (t.cluster_id) q.set("cluster_id", t.cluster_id)
  if (t.namespace) q.set("namespace", t.namespace)
  return q.toString()
}

// --- 배포/라이프사이클 ---

export type DeployPhase = "agent" | "pull" | "run" | "settings" | "verify" | "done" | "error"
export type DeployEvent = {
  phase: DeployPhase
  status?: "running" | "done" | "error"
  detail?: string
  layers_done?: number
  layers_total?: number
  slot?: string
  service?: ManagedService
  applied_settings?: Record<string, string>
  code?: number
}

/** 배포를 NDJSON 스트림으로 실행하며 단계 이벤트를 콜백으로 전달(상세 progress). */
export async function deployStream(
  spec: DeploySpec,
  target: DeployTarget,
  onEvent: (e: DeployEvent) => void
): Promise<void> {
  const res = await authFetch(`${BASE}/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ spec, target }),
  })
  if (!res.ok || !res.body) {
    await throwOnError(res, "배포 스트림 실패")
    return
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ""
  const flush = (line: string) => {
    const t = line.trim()
    if (!t) return
    try {
      onEvent(JSON.parse(t) as DeployEvent)
    } catch {
      /* 부분 라인 무시 */
    }
  }
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let nl: number
    while ((nl = buf.indexOf("\n")) >= 0) {
      flush(buf.slice(0, nl))
      buf = buf.slice(nl + 1)
    }
  }
  flush(buf)
}

export async function deploy(
  spec: DeploySpec,
  target: DeployTarget
): Promise<{ service: ManagedService; applied_settings: Record<string, string> }> {
  const res = await authFetch(BASE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ spec, target }),
  })
  if (!res.ok) await throwOnError(res, "배포 실패")
  return res.json()
}

export async function listServices(target: DeployTarget): Promise<ManagedService[]> {
  const res = await authFetch(`${BASE}?${targetQuery(target)}`)
  if (!res.ok) await throwOnError(res, "서비스 목록 조회 실패")
  return res.json()
}

// --- 전체 서비스 집계 (에이전트 > 서비스 관리 탭 — design/agent-services-overview.md) ---

export type OverviewTarget = {
  target: DeployTarget
  services: ManagedService[]
  error: string | null
}

// 관리 외(수동 배포) 서비스 — heartbeat 자기 등록 또는 전역 설정 URL 폴링으로 관측.
export type ExternalService = {
  kind: string
  url: string
  ok: boolean
  error: string | null
  source: "heartbeat" | "settings" | "worker"
  version?: string | null
  model?: string | null
  device?: string | null
  uptime_seconds?: number | null
  cpu_percent?: number | null
  mem_percent?: number | null
  detail?: string | null // 부가 표시(워커: mode·상태·처리량 등)
}

export type Overview = {
  targets: OverviewTarget[]
  external: ExternalService[]
  generated_at: string
}

/** 등록 서버×{docker,systemd} + 클러스터 전체의 배포 서비스 집계(부분 실패는 error 병합). */
export async function fetchOverview(): Promise<Overview> {
  const res = await authFetch(`${BASE}/overview`)
  if (!res.ok) await throwOnError(res, "서비스 집계 조회 실패")
  return res.json()
}

export async function serviceAction(
  target: DeployTarget,
  name: string,
  action: "start" | "stop" | "restart"
): Promise<ManagedService> {
  const res = await authFetch(`${BASE}/${encodeURIComponent(name)}/${action}?${targetQuery(target)}`, {
    method: "POST",
  })
  if (!res.ok) await throwOnError(res, `${action} 실패`)
  return res.json()
}

export async function scaleService(
  target: DeployTarget,
  name: string,
  replicas: number
): Promise<ManagedService> {
  const res = await authFetch(
    `${BASE}/${encodeURIComponent(name)}/scale/${replicas}?${targetQuery(target)}`,
    { method: "POST" }
  )
  if (!res.ok) await throwOnError(res, "스케일 실패")
  return res.json()
}

export async function removeService(target: DeployTarget, name: string): Promise<void> {
  const res = await authFetch(`${BASE}/${encodeURIComponent(name)}?${targetQuery(target)}`, {
    method: "DELETE",
  })
  if (!res.ok) await throwOnError(res, "제거 실패")
}

export async function serviceLogs(
  target: DeployTarget,
  name: string,
  tail = 200
): Promise<string> {
  const res = await authFetch(
    `${BASE}/${encodeURIComponent(name)}/logs?tail=${tail}&${targetQuery(target)}`
  )
  if (!res.ok) await throwOnError(res, "로그 조회 실패")
  const d = await res.json()
  return d.logs ?? ""
}

// --- 클러스터 등록 ---

export async function listClusters(): Promise<Cluster[]> {
  const res = await authFetch(`${BASE}/clusters`)
  if (!res.ok) await throwOnError(res, "클러스터 목록 조회 실패")
  return res.json()
}

export async function upsertCluster(body: ClusterIn): Promise<Cluster> {
  const res = await authFetch(`${BASE}/clusters`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) await throwOnError(res, "클러스터 등록 실패")
  return res.json()
}

export async function deleteCluster(clusterId: string): Promise<void> {
  const res = await authFetch(`${BASE}/clusters/${encodeURIComponent(clusterId)}`, {
    method: "DELETE",
  })
  if (!res.ok) await throwOnError(res, "클러스터 삭제 실패")
}

// --- 권한/런타임 표시 ---

/** ISO 시작시각 → "2일 3시간" / "3시간 12분" / "12분" / "30초" 가동시간. */
export function formatUptime(iso?: string | null): string {
  if (!iso) return "-"
  const start = new Date(iso).getTime()
  if (Number.isNaN(start)) return "-"
  let s = Math.floor((Date.now() - start) / 1000)
  if (s < 0) return "-"
  const d = Math.floor(s / 86400)
  s -= d * 86400
  const h = Math.floor(s / 3600)
  s -= h * 3600
  const m = Math.floor(s / 60)
  s -= m * 60
  if (d > 0) return `${d}일 ${h}시간`
  if (h > 0) return `${h}시간 ${m}분`
  if (m > 0) return `${m}분`
  return `${s}초`
}

export const runtimePrivilege: Record<string, { label: string; privilege: string; cls: string }> = {
  docker: { label: "Docker (호스트)", privilege: "host_docker", cls: "bg-blue-500/10 text-blue-600 border-blue-500/20" },
  systemd: { label: "systemd (root)", privilege: "host_root", cls: "bg-red-500/10 text-red-600 border-red-500/20" },
  k8s: { label: "Kubernetes (RBAC)", privilege: "cluster_rbac", cls: "bg-green-500/10 text-green-600 border-green-500/20" },
}

// ── 설정 픽커용 서비스 엔드포인트(실행 중 관리형+수동) ──────────────────────

export type ServiceEndpoint = {
  kind: string
  name: string
  url: string
  model: string | null
  runtime: string // docker | systemd | k8s | manual
  location: string
}

// 프론트 메모리 캐시 — 백엔드에도 60s TTL 캐시가 있지만, 화면 내 여러 픽커가 즉시
// 표시되도록 브라우저 쪽에서도 같은 TTL 로 캐싱하고 동시 요청은 한 번으로 합친다.
const EP_TTL_MS = 60_000
const epCache = new Map<string, { ts: number; rows: ServiceEndpoint[] }>()
const epInflight = new Map<string, Promise<ServiceEndpoint[]>>()

/** 실행 중 서비스 엔드포인트 목록 — TTL(60s) 메모리 캐시, refresh 로 강제 갱신. */
export async function fetchServiceEndpoints(
  kind?: string,
  opts?: { refresh?: boolean }
): Promise<ServiceEndpoint[]> {
  const key = kind ?? "__all__"
  const hit = epCache.get(key)
  if (!opts?.refresh && hit && Date.now() - hit.ts < EP_TTL_MS) return hit.rows
  const inflight = epInflight.get(key)
  if (!opts?.refresh && inflight) return inflight

  const params = new URLSearchParams()
  if (kind) params.set("kind", kind)
  if (opts?.refresh) params.set("refresh", "true")
  const qs = params.size ? `?${params.toString()}` : ""
  const p = (async () => {
    try {
      const res = await authFetch(`/api/v1/deploy/service-endpoints${qs}`)
      if (!res.ok) throw new Error("서비스 엔드포인트 조회 실패")
      const rows: ServiceEndpoint[] = await res.json()
      epCache.set(key, { ts: Date.now(), rows })
      return rows
    } finally {
      epInflight.delete(key)
    }
  })()
  epInflight.set(key, p)
  return p
}
