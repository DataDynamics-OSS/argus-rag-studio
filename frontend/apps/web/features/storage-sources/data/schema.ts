// 스토리지 소스 도메인 타입 — 백엔드 sources/schemas.py 와 매칭.
// 참조 인테이크(pull)가 원본을 읽어올 S3·NAS 소스. name 은 라우팅 path_rule 이 참조하는 논리명.

export type SourceKind = "s3" | "nas"

export type StorageSource = {
  id: number
  source_id: string
  name: string
  kind: SourceKind
  description: string | null
  config: Record<string, string>
  has_secret: boolean
  enabled: boolean
  created_by: string | null
  created_at: string
  updated_at: string
}

export type StorageSourceCreate = {
  name: string
  kind: SourceKind
  description?: string | null
  config: Record<string, string>
  secret?: Record<string, string> | null
  enabled: boolean
}

export type StorageSourceUpdate = {
  name?: string
  description?: string | null
  config?: Record<string, string>
  secret?: Record<string, string> | null
  clear_secret?: boolean
  enabled?: boolean
}

export type SourceTestResult = {
  ok: boolean
  message: string
  entry_count: number | null
  elapsed_ms: number | null
}

export type SourceEntry = {
  path: string
  name: string
  is_dir: boolean
  size: number
  mtime: string | null
}

export type SourceListResult = {
  prefix: string
  entries: SourceEntry[]
  truncated: boolean
}
