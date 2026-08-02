/**
 * API Keys (service account) API client.
 *
 * 외부 시스템이 RAG 백엔드(search/query/chat 등)를 프로그래밍 방식으로 호출할 때 쓰는
 * 장기 자격 증명을 관리한다. 모든 요청은 admin 권한이 필요하며 `/api/v1/api-keys/*`
 * 엔드포인트를 호출한다. 평문 키는 발급 응답에서만 1회 노출된다.
 */

import { authFetch } from "@/features/auth/auth-fetch"

const BASE = "/api/v1/api-keys"

/** 발급된 API 키 메타데이터(평문 미포함). */
export type ApiKey = {
  id: number
  name: string
  description: string | null
  key_prefix: string
  role_id: string
  enabled: boolean
  expires_at: string | null
  last_used_at: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

/** 발급 직후 응답 — 평문 키(`api_key`)를 1회만 포함. */
export type ApiKeyCreated = ApiKey & { api_key: string }

export type CreateApiKeyPayload = {
  name: string
  description?: string
  role: string
  expires_in_days?: number | null
}

/** 발급된 API 키 목록(최신순). */
export async function fetchApiKeys(): Promise<ApiKey[]> {
  const res = await authFetch(BASE)
  if (!res.ok) throw new Error(`API 키 조회 실패: ${res.status}`)
  return res.json()
}

/** API 키를 발급한다. 응답의 `api_key` 는 이때만 노출되니 즉시 안전하게 보관해야 한다. */
export async function createApiKey(payload: CreateApiKeyPayload): Promise<ApiKeyCreated> {
  const res = await authFetch(BASE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `API 키 발급 실패: ${res.status}`)
  }
  return res.json()
}

/** API 키 메타데이터/활성 상태를 수정한다. */
export async function updateApiKey(
  id: number,
  payload: { name?: string; description?: string; enabled?: boolean },
): Promise<ApiKey> {
  const res = await authFetch(`${BASE}/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `API 키 수정 실패: ${res.status}`)
  }
  return res.json()
}

/** API 키를 폐기(영구 삭제)한다. */
export async function deleteApiKey(id: number): Promise<void> {
  const res = await authFetch(`${BASE}/${id}`, { method: "DELETE" })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `API 키 폐기 실패: ${res.status}`)
  }
}
