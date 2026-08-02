// 평가(Evaluation) 도메인 타입 — 백엔드 evaluation/schemas.py 와 매칭.

export type EvalDataset = {
  id: number
  dataset_id: string
  name: string
  description: string | null
  collection_id: number | null
  item_count: number
  created_by: string | null
  created_at: string
  updated_at: string
}

export type EvalItem = {
  id: number
  item_id: string
  dataset_id: number
  question: string
  expected_answer: string | null
  expected_sources: string[]
  created_at: string
}

export type EvalRun = {
  id: number
  run_id: string
  dataset_id: number
  collection_id: number
  pipeline_id: number | null
  status: string
  mode: string
  distance_metric: string | null
  rerank: boolean
  judge: boolean
  top_k: number
  total_items: number
  completed_items: number
  hit_rate: number | null
  mrr: number | null
  faithfulness: number | null
  answer_relevance: number | null
  correctness: number | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export type EvalResult = {
  id: number
  item_id: number
  question: string
  answer: string | null
  retrieved_docs: string[]
  hit: boolean | null
  reciprocal_rank: number | null
  faithfulness: number | null
  answer_relevance: number | null
  correctness: number | null
}

// ── 설정 스윕 / 리더보드 ──────────────────────────────────────────────
export type EvalSweep = {
  id: number
  sweep_id: string
  name: string
  dataset_id: number
  base_collection_id: number
  primary_metric: string
  judge: boolean
  judge_top_n: number | null
  holdout_ratio: number
  max_runs: number
  status: string // queued|indexing|running|judging|succeeded|failed|canceled
  total_runs: number
  completed_runs: number
  best_run_id: number | null
  error: string | null
  created_by: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export type LeaderboardRow = {
  run_id: string
  rank: number
  status: string
  index_config: Record<string, unknown>
  query_config: Record<string, unknown>
  collection_id: number
  ephemeral: boolean
  hit_rate: number | null
  mrr: number | null
  faithfulness: number | null
  answer_relevance: number | null
  correctness: number | null
  score: number | null
  holdout_score: number | null
  overfit: boolean
  judged: boolean
  is_best: boolean
}

export type Leaderboard = {
  sweep: EvalSweep
  primary_metric: string
  holdout_ratio: number
  rows: LeaderboardRow[]
}

export type SweepApplyResult = {
  applied_fields: string[]
  reindexed: boolean
  recommended_runtime: Record<string, unknown>
  collection_id: number
}

export type SweepSearchSpace = {
  index_axis?: Record<string, (string | number | boolean)[]>
  query_axis?: Record<string, (string | number | boolean)[]>
}
