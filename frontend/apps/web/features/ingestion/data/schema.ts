// 인제스천 도메인 타입 — 백엔드 app/ingestion/schemas.py 와 매칭.

export type IngestionStatus = "queued" | "running" | "succeeded" | "failed"
export type IngestionStage = "parse" | "chunk" | "embed" | "index"

export type IngestionJob = {
  id: number
  job_id: string
  document_id: number
  collection_id: number
  status: string
  stage: string | null
  progress: number
  chunk_count: number
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export type UploadResult = {
  document_id: number
  document_uuid: string
  name: string
  status: string
  job_id: string
}

export type JobListItem = IngestionJob & {
  document_name: string | null
  collection_name: string | null
  document_uuid: string | null
}

export type PaginatedJobs = {
  items: JobListItem[]
  total: number
  page: number
  page_size: number
}

// 외부 확장 서버(embedding/rerank/detection) 메트릭 — 백엔드 /embedding/server-stats 프록시.
export type ExtServerSnapshot = {
  server: string
  extra?: Record<string, string | number> | null // 서비스별 부가 지표(vlm 요청/KV 캐시, hwp 렌더 등)
  version?: string | null
  device?: string | null
  model?: string | null
  uptime_seconds?: number | null
  system?: {
    cpu_percent?: number
    mem_used_bytes?: number
    mem_total_bytes?: number
    mem_percent?: number
    process_rss_bytes?: number
    load1?: number
  }
  disk?: { used_bytes?: number; total_bytes?: number }
  gpu?: {
    index: number
    name?: string
    utilization_percent?: number
    mem_used_bytes?: number
    mem_total_bytes?: number
    mem_reserved_bytes?: number
    mem_allocated_bytes?: number
    temperature_c?: number | null
    power_w?: number | null
  }[]
  models?: { count?: number; loaded?: string[]; warmup_ready?: boolean }
  requests?: {
    total?: number
    inflight?: number
    errors?: number
    avg_latency_ms?: number
    domain?: Record<string, number>
  }
}

// 인제스천 워커(하트비트 기반 모니터링)
export type WorkerInfo = {
  id: string
  hostname?: string | null
  pid?: number | null
  mode?: string | null // in_process | standalone
  runtime?: string | null // 배포 방식: docker | systemd | k8s | null(직접 실행)
  version?: string | null
  status: string // starting | idle | busy | stopped
  current_job_id?: string | null
  processed_total: number
  started_at?: string | null
  last_heartbeat_at?: string | null
  heartbeat_age_seconds?: number | null
  alive: boolean
  metrics?: {
    cpu_percent?: number // 프로세스 CPU%
    rss_bytes?: number // 프로세스 RSS
    threads?: number
    host_cpu_percent?: number
    host_mem_used_bytes?: number
    host_mem_total_bytes?: number
    host_mem_percent?: number
    load1?: number
    gpu?: {
      index: number
      name?: string
      utilization_percent?: number
      mem_used_bytes?: number
      mem_total_bytes?: number
      temperature_c?: number | null
    }[]
  } | null
}

export type ExtServerStat = {
  kind: string
  url: string
  ok: boolean
  stats?: ExtServerSnapshot | null
  error?: string | null
}

export type JobsSummary = {
  queued: number
  running: number
  succeeded_24h: number
  failed_24h: number
  total: number
  running_by_stage: Record<string, number>
}

export type ParsePreview = {
  filename: string
  strategy: string      // 실제 적용된 파싱 전략(auto 해석 후)
  char_count: number    // 파싱 전문 길이(자르기 전)
  truncated: boolean    // max_chars 로 잘렸는지
  elapsed_ms: number
  text: string
}

export type ChunkPreviewItem = {
  seq: number
  text: string
  section_path: string | null
  char_start: number | null  // 전문 내 시작 위치(하이라이트용)
  char_end: number | null
  char_count: number | null
  token_count: number | null
}

export type ChunkPreview = {
  parse_strategy: string
  chunk_strategy: string
  chunk_size: number
  chunk_overlap: number
  chunk_unit: string
  char_count: number    // 청킹 전 전문 길이(자르기 전)
  truncated: boolean
  body: string          // 청킹 전 전문(잘릴 수 있음)
  chunk_total: number   // 전체 청크 수
  chunks: ChunkPreviewItem[]
}
