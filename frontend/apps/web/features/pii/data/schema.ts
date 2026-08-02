// PII 규칙 도메인 타입 — 백엔드 app/pii/schemas.py 와 매칭.

export type PiiRule = {
  id: number
  rule_id: string
  name: string
  category: string
  pattern: string
  flags: string
  mask: string
  enabled: boolean
  description: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export type PiiRuleInput = {
  name: string
  category: string
  pattern: string
  flags: string
  mask: string
  enabled: boolean
  description?: string | null
}

export type PiiTestMatch = { rule_id: string; name: string; category: string; count: number }
export type PiiTestResult = { masked: string; matches: PiiTestMatch[]; invalid: string[] }

// 사용자 정의 함수(샌드박스)
export type PiiFunction = {
  id: number
  function_id: string
  name: string
  code: string
  timeout_ms: number
  enabled: boolean
  description: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export type PiiFunctionInput = {
  name: string
  code: string
  timeout_ms: number
  enabled: boolean
  description?: string | null
}

export type PiiFunctionTestResult = { result: string | null; error: string | null }
