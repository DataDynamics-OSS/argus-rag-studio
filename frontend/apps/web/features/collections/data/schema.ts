// 컬렉션(지식베이스) 도메인 타입 — 백엔드 app/collections/schemas.py 와 1:1 매칭.

export type DistanceMetric = "cosine" | "l2" | "inner_product"
export type EmbeddingProviderKind = "openai_compatible" | "local" | "hash"

export type LocalEmbeddingModel = {
  model: string
  dim: number
  size_gb: number | null
  description: string
}
export type ParseStrategy = "auto" | "text" | "layout" | "docai" | "vlm" | "rhwp"
export type ParseStrategyInfo = {
  strategy: ParseStrategy
  label: string
  description: string
  available: boolean
}
export type ChunkStrategy =
  | "auto"
  | "recursive"
  | "sentence"
  | "paragraph"
  | "section"
  | "fixed"
  | "markdown"
  | "semantic"
export type ChunkUnit = "char" | "token"
export type RerankProviderKind = "none" | "llm" | "local" | "cross_encoder"
export type CollectionStatus = "active" | "archived"

export type Collection = {
  id: number
  collection_id: string
  name: string
  description: string | null
  embedding_provider: string
  embedding_model: string
  embedding_dim: number
  embedding_server_url: string | null
  distance_metric: string
  rerank_provider: string
  rerank_model: string | null
  parse_strategy: string
  chunk_strategy: string
  chunk_unit: string
  chunk_size: number
  chunk_overlap: number
  ingestion_pipeline: IngestionPipeline | null
  status: string
  document_count: number
  created_by: string | null
  created_at: string
  updated_at: string
}

// 인제스천 보강 파이프라인 — 레지스트리 transform 을 순서대로 끼운 구성
export type TransformPhase = "post_parse" | "post_chunk"
export type TransformInfo = {
  id: string
  label: string
  description: string
  phase: TransformPhase
  config_schema: Record<string, unknown>
  available: boolean
}
export type PipelineStage = { id: string; config?: Record<string, unknown> }
export type IngestionPipeline = { post_parse: PipelineStage[]; post_chunk: PipelineStage[] }

export type CollectionCreateInput = {
  name: string
  description?: string | null
  embedding_provider?: EmbeddingProviderKind | null
  embedding_model?: string | null
  embedding_dim?: number | null
  embedding_server_url?: string | null
  distance_metric?: DistanceMetric | null
  rerank_provider?: RerankProviderKind | null
  rerank_model?: string | null
  parse_strategy?: ParseStrategy | null
  chunk_strategy?: ChunkStrategy | null
  chunk_unit?: ChunkUnit | null
  chunk_size?: number | null
  chunk_overlap?: number | null
}

export type CollectionUpdateInput = {
  description?: string | null
  status?: CollectionStatus | null
  rerank_provider?: RerankProviderKind | null
  rerank_model?: string | null
}

export type CollectionReindexInput = {
  embedding_provider?: EmbeddingProviderKind | null
  embedding_model?: string | null
  embedding_server_url?: string | null
  distance_metric?: DistanceMetric | null
  parse_strategy?: ParseStrategy | null
  chunk_strategy?: ChunkStrategy | null
  chunk_unit?: ChunkUnit | null
  chunk_size?: number | null
  chunk_overlap?: number | null
  post_parse?: PipelineStage[] | null
  post_chunk?: PipelineStage[] | null
  clear_server_url?: boolean
}

export type CollectionReindexResult = {
  collection: Collection
  document_count: number
  job_ids: string[]
}

export type PaginatedCollections = {
  items: Collection[]
  total: number
  page: number
  page_size: number
}
