// 피드백(Feedback) 도메인 타입 — 백엔드 feedback/schemas.py 와 매칭.

export type FeedbackRating = "up" | "down"
export type FeedbackStatus = "new" | "promoted" | "dismissed"

export type Feedback = {
  id: number
  feedback_id: string
  trace_id: string | null
  collection_id: number | null
  query: string
  answer: string | null
  rating: FeedbackRating
  comment: string | null
  corrected_answer: string | null
  expected_sources: string[]
  status: FeedbackStatus
  promoted_item_id: number | null
  created_by: string | null
  created_at: string
}

export type FeedbackStats = {
  total: number
  up: number
  down: number
  new: number
  promoted: number
}

export type FeedbackCreateInput = {
  rating: FeedbackRating
  query: string
  answer?: string | null
  collection_id?: number | null
  trace_id?: string | null
  comment?: string | null
  corrected_answer?: string | null
  expected_sources?: string[]
}

export type PromoteInput = {
  dataset_id: number
  expected_answer?: string | null
  expected_sources?: string[] | null
}
