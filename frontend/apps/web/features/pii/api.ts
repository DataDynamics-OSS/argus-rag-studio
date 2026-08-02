// PII 규칙 REST 클라이언트.

import { authFetch, throwOnError } from "@/features/auth/auth-fetch"
import type {
  PiiFunction,
  PiiFunctionInput,
  PiiFunctionTestResult,
  PiiRule,
  PiiRuleInput,
  PiiTestResult,
} from "./data/schema"

const BASE = "/api/v1/pii"

export async function listPiiRules(): Promise<PiiRule[]> {
  const res = await authFetch(`${BASE}/rules`)
  if (!res.ok) await throwOnError(res, "PII 규칙 조회 실패")
  return res.json()
}

export async function createPiiRule(input: PiiRuleInput): Promise<PiiRule> {
  const res = await authFetch(`${BASE}/rules`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "PII 규칙 생성 실패")
  return res.json()
}

export async function updatePiiRule(ruleId: string, input: Partial<PiiRuleInput>): Promise<PiiRule> {
  const res = await authFetch(`${BASE}/rules/${ruleId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "PII 규칙 수정 실패")
  return res.json()
}

export async function deletePiiRule(ruleId: string): Promise<void> {
  const res = await authFetch(`${BASE}/rules/${ruleId}`, { method: "DELETE" })
  if (!res.ok) await throwOnError(res, "PII 규칙 삭제 실패")
}

export async function testPiiRules(text: string, categories?: string[]): Promise<PiiTestResult> {
  const res = await authFetch(`${BASE}/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, categories: categories ?? null }),
  })
  if (!res.ok) await throwOnError(res, "PII 테스트 실패")
  return res.json()
}

// ── 사용자 정의 함수 ──────────────────────────────────────────────────────────

export async function listPiiFunctions(): Promise<PiiFunction[]> {
  const res = await authFetch(`${BASE}/functions`)
  if (!res.ok) await throwOnError(res, "PII 함수 조회 실패")
  return res.json()
}

export async function createPiiFunction(input: PiiFunctionInput): Promise<PiiFunction> {
  const res = await authFetch(`${BASE}/functions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "PII 함수 생성 실패")
  return res.json()
}

export async function updatePiiFunction(functionId: string, input: Partial<PiiFunctionInput>): Promise<PiiFunction> {
  const res = await authFetch(`${BASE}/functions/${functionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "PII 함수 수정 실패")
  return res.json()
}

export async function deletePiiFunction(functionId: string): Promise<void> {
  const res = await authFetch(`${BASE}/functions/${functionId}`, { method: "DELETE" })
  if (!res.ok) await throwOnError(res, "PII 함수 삭제 실패")
}

export async function testPiiFunction(code: string, text: string, timeoutMs: number): Promise<PiiFunctionTestResult> {
  const res = await authFetch(`${BASE}/functions/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, text, timeout_ms: timeoutMs }),
  })
  if (!res.ok) await throwOnError(res, "PII 함수 테스트 실패")
  return res.json()
}
