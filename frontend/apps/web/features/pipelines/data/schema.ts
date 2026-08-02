// 파이프라인 도메인 타입 — 백엔드 pipelines/schemas.py 와 매칭.

import type { ChunkHit } from "@/features/search/data/schema"

export type RetrievalConfig = {
  mode: "hybrid" | "vector" | "lexical"
  top_k: number
  vector_k: number
  lexical_k: number
  rrf_k: number
  distance_metric: string // "" 이면 컬렉션 메트릭 상속
}
export type RerankConfig = { enabled: boolean; provider: string; top_n: number }
export type GenerationConfig = { model: string; max_tokens: number; temperature: number }

export type PipelineConfig = {
  retrieval: RetrievalConfig
  rerank: RerankConfig
  generation: GenerationConfig
}

export type Pipeline = {
  id: number
  pipeline_id: string
  name: string
  description: string | null
  stage: string
  active_version: number
  version_count: number
  config: PipelineConfig
  created_by: string | null
  created_at: string
  updated_at: string
}

export type PipelineVersion = {
  version: number
  config: PipelineConfig
  note: string | null
  created_by: string | null
  created_at: string
}

export type DiffEntry = { path: string; from_value: string | null; to_value: string | null }
export type Diff = { from_version: number; to_version: number; changes: DiffEntry[] }

export type CompareResult = {
  query: string
  a: { version: number; hits: ChunkHit[] }
  b: { version: number; hits: ChunkHit[] }
}
