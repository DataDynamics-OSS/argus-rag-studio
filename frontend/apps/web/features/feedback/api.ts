// 피드백 REST 클라이언트.

import { authFetch, throwOnError } from "@/features/auth/auth-fetch"
import type {
  Feedback,
  FeedbackCreateInput,
  FeedbackStats,
  PromoteInput,
} from "./data/schema"

const BASE = "/api/v1/feedback"

export async function submitFeedback(input: FeedbackCreateInput): Promise<Feedback> {
  const res = await authFetch(BASE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "피드백 전송 실패")
  return res.json()
}

export async function listFeedback(params?: {
  rating?: string
  status?: string
  collection_id?: number
}): Promise<Feedback[]> {
  const qs = new URLSearchParams()
  if (params?.rating) qs.set("rating", params.rating)
  if (params?.status) qs.set("status", params.status)
  if (params?.collection_id != null) qs.set("collection_id", String(params.collection_id))
  const url = qs.toString() ? `${BASE}?${qs}` : BASE
  const res = await authFetch(url)
  if (!res.ok) await throwOnError(res, "피드백 조회 실패")
  return res.json()
}

export async function getFeedbackStats(): Promise<FeedbackStats> {
  const res = await authFetch(`${BASE}/stats`)
  if (!res.ok) await throwOnError(res, "피드백 통계 조회 실패")
  return res.json()
}

// 외부 노출 식별자는 피드백 UUID(feedback_id).
export async function promoteFeedback(feedbackUuid: string, input: PromoteInput): Promise<Feedback> {
  const res = await authFetch(`${BASE}/${feedbackUuid}/promote`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "피드백 승격 실패")
  return res.json()
}

export async function dismissFeedback(feedbackUuid: string): Promise<Feedback> {
  const res = await authFetch(`${BASE}/${feedbackUuid}/dismiss`, { method: "POST" })
  if (!res.ok) await throwOnError(res, "피드백 무시 처리 실패")
  return res.json()
}

export async function deleteFeedback(feedbackUuid: string): Promise<void> {
  const res = await authFetch(`${BASE}/${feedbackUuid}`, { method: "DELETE" })
  if (!res.ok) await throwOnError(res, "피드백 삭제 실패")
}
