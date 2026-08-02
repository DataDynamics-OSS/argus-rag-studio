import { authFetch } from "@/features/auth/auth-fetch"
import { type Server } from "./data/schema"

const BASE = "/api/v1/servermgr"

type ServerListParams = {
  status?: string[]
  search?: string
  page?: number
  pageSize?: number
}

export type PaginatedServers = {
  items: Server[]
  total: number
  page: number
  pageSize: number
}

function mapServer(s: Record<string, unknown>): Server {
  return {
    hostname: String(s.hostname),
    ipAddress: String(s.ip_address),
    version: s.version as string | null,
    osVersion: s.os_version as string | null,
    arch: s.arch as string | null,
    coreCount: s.core_count as number | null,
    totalMemory: s.total_memory as number | null,
    cpuUsage: s.cpu_usage as number | null,
    memoryUsage: s.memory_usage as number | null,
    diskSwapPercent: s.disk_swap_percent as number | null,
    gpuCount: s.gpu_count as number | null,
    gpuUsage: s.gpu_usage as number | null,
    gpuMemoryUsage: s.gpu_memory_usage as number | null,
    gpuName: s.gpu_name as string | null,
    status: s.status as Server["status"],
    lastHeartbeatSeconds: s.last_heartbeat_seconds as number | null,
    createdAt: new Date(s.created_at as string),
    updatedAt: new Date(s.updated_at as string),
  }
}

export async function registerServers(hostnames: string[]): Promise<{ updated: number }> {
  const res = await authFetch(`${BASE}/servers/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ hostnames }),
  })
  if (!res.ok) throw new Error(`Failed to register servers: ${res.status}`)
  return res.json()
}

export async function unregisterServers(hostnames: string[]): Promise<{ updated: number }> {
  const res = await authFetch(`${BASE}/servers/unregister`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ hostnames }),
  })
  if (!res.ok) throw new Error(`Failed to unregister servers: ${res.status}`)
  return res.json()
}

export async function fetchInspect(hostname: string): Promise<Record<string, unknown>> {
  const res = await authFetch(`${BASE}/servers/${encodeURIComponent(hostname)}/inspect`)
  if (!res.ok) throw new Error(`Failed to inspect server: ${res.status}`)
  return res.json()
}

export async function fetchTop(hostname: string): Promise<Record<string, unknown>> {
  const res = await authFetch(`${BASE}/servers/${encodeURIComponent(hostname)}/top?limit=80`)
  if (!res.ok) throw new Error(`Failed to fetch top data: ${res.status}`)
  return res.json()
}

export async function fetchProcesses(hostname: string): Promise<Record<string, unknown>> {
  const res = await authFetch(
    `${BASE}/servers/${encodeURIComponent(hostname)}/processes?sort_by=pid&limit=0`
  )
  if (!res.ok) throw new Error(`Failed to fetch processes: ${res.status}`)
  return res.json()
}

export async function killProcess(
  hostname: string,
  pid: number,
  signal: string = "SIGKILL"
): Promise<Record<string, unknown>> {
  const res = await authFetch(
    `${BASE}/servers/${encodeURIComponent(hostname)}/processes/kill`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pid, signal }),
    }
  )
  if (!res.ok) throw new Error(`Failed to kill process: ${res.status}`)
  return res.json()
}

export async function fetchServers(params?: ServerListParams): Promise<PaginatedServers> {
  const query = new URLSearchParams()
  if (params?.status && params.status.length > 0) query.set("status", params.status.join(","))
  if (params?.search) query.set("search", params.search)
  query.set("page", String(params?.page ?? 1))
  query.set("page_size", String(params?.pageSize ?? 10))

  const url = `${BASE}/servers?${query.toString()}`
  const res = await authFetch(url)
  if (!res.ok) throw new Error(`Failed to fetch servers: ${res.status}`)
  const data = await res.json()
  return {
    items: (data.items as Record<string, unknown>[]).map(mapServer),
    total: data.total,
    page: data.page,
    pageSize: data.page_size,
  }
}

// ---------------------------------------------------------------------------
// 상세 페이지 — 실시간 메트릭/GPU (servermgr 프록시)
// ---------------------------------------------------------------------------

export type HostMetrics = {
  hostname?: string
  cpu?: { usage_percent: number; core_count?: number; load_avg_1m?: number }
  memory?: {
    total_bytes: number
    used_bytes: number
    usage_percent: number
    swap_total_bytes?: number
    swap_used_bytes?: number
  }
  disks?: { device: string; mount_point: string; fs_type: string; total_bytes: number; used_bytes: number; usage_percent: number }[]
  networks?: { interface: string; bytes_sent: number; bytes_recv: number }[]
}

export type GpuInfo = {
  index: number
  name: string
  util_percent: number | null
  mem_total_mb: number | null
  mem_used_mb: number | null
  temp_c: number | null
  power_w: number | null
  power_limit_w: number | null
}
export type GpuResult = { available: boolean; count: number; gpus: GpuInfo[] }

/** 단일 서버 정보(목록에서 hostname 으로 조회). */
export async function fetchServer(hostname: string): Promise<Server | null> {
  const data = await fetchServers({ search: hostname, pageSize: 50 })
  return data.items.find((s) => s.hostname === hostname) ?? null
}

export async function fetchMetrics(hostname: string): Promise<HostMetrics> {
  const res = await authFetch(`${BASE}/servers/${encodeURIComponent(hostname)}/metrics`)
  if (!res.ok) throw new Error(`메트릭 조회 실패: ${res.status}`)
  return res.json()
}

export async function fetchGpu(hostname: string): Promise<GpuResult> {
  const res = await authFetch(`${BASE}/servers/${encodeURIComponent(hostname)}/gpu`)
  if (!res.ok) throw new Error(`GPU 조회 실패: ${res.status}`)
  return res.json()
}
