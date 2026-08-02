// 파인튜닝(Fine-tuning) 도메인 타입 — 백엔드 finetune/schemas.py 와 매칭.

export type FtTask = "embedding" | "reranker"
export type FtSplit = "train" | "valid" | "test"
export type FtExampleSource = "manual" | "goldenset" | "feedback" | "mined"

export type FtDataset = {
  id: number
  dataset_id: string
  name: string
  description: string | null
  base_collection_id: number | null
  base_model: string | null
  task: string
  prompt_format: string
  split_strategy: string
  status: string
  counts: Record<string, number>
  created_by: string | null
  created_at: string
  updated_at: string
}

export type FtExample = {
  id: number
  example_id: string
  dataset_id: number
  split: string
  query: string
  positive: string
  negatives: string[]
  positive_chunk_id: number | null
  source: string
  meta: Record<string, unknown> | null
  created_at: string
}

export type FtManifest = {
  dataset_id: string
  name: string
  base_model: string | null
  task: string
  prompt_format: string
  split_strategy: string
  counts: Record<string, number>
  created_at: string | null
}

export type FtJobStatus = "queued" | "running" | "succeeded" | "failed" | "canceled"

export type FtJob = {
  id: number
  job_id: string
  dataset_id: number
  dataset_name: string | null
  task: string
  base_model: string | null
  config: Record<string, number>
  status: string
  stage: string | null
  progress: number
  metrics: Record<string, number> | null
  artifact_uri: string | null
  error: string | null
  callback_token: string | null
  created_by: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export type FtGlossaryTerm = {
  id: number
  term_id: string
  term: string
  definition: string | null
  synonyms: string[]
  domain: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export type FtBuilderResult = {
  built: number
  updated: number
  skipped: number
  message: string | null
}

export type FtModelStatus = "registered" | "serving" | "archived"

export type FtModel = {
  id: number
  model_id: string
  name: string
  task: string
  base_model: string | null
  embedding_dim: number | null
  format: string | null
  prompt_format: string
  dataset_id: number | null
  job_id: number | null
  artifact_uri: string | null
  metrics: Record<string, number> | null
  serving_url: string | null
  status: string
  published_uri: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}
