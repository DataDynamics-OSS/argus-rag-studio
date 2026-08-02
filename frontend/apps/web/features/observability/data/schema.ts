// 관측(Observability) 도메인 타입 — 백엔드 observability/schemas.py 와 매칭.

export type LatencyStat = { avg: number | null; p50: number | null; p95: number | null }
export type TopQuery = { query: string; count: number }

export type ObsStats = {
  total: number
  ok: number
  error: number
  success_rate: number | null
  total_ms: LatencyStat
  embedding_ms: LatencyStat
  search_ms: LatencyStat
  retrieval_ms: LatencyStat
  rerank_ms: LatencyStat
  generation_ms: LatencyStat
  prompt_tokens: number
  completion_tokens: number
  top_queries: TopQuery[]
}

export type Trace = {
  id: number
  trace_id: string
  kind: string
  collection_id: number | null
  query: string | null
  mode: string | null
  distance_metric: string | null
  rerank: boolean
  status: string
  error: string | null
  hit_count: number
  retrieval_ms: number | null
  rerank_ms: number | null
  generation_ms: number | null
  total_ms: number | null
  prompt_tokens: number | null
  completion_tokens: number | null
  answer: string | null
  created_by: string | null
  created_at: string
}
