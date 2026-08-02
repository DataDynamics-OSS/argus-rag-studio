// 설정 REST 클라이언트 — GET/PUT /api/v1/settings (admin).

import { authFetch, throwOnError } from "@/features/auth/auth-fetch"

export type EffectiveSettings = {
  platform: {
    base: string
    databricks_host: string
    databricks_token: string
    databricks_token_set: boolean
  }
  embedding: {
    provider: string
    server_url: string
    model: string
    query_instruction: string
    batch_size: number
    default_dim: number
    default_model: string
    default_metric: string
    timeout: number
    auth_header: string
    auth_scheme: string
    api_key: string
    api_key_set: boolean
  }
  ingestion: {
    chunk_size: number
    chunk_overlap: number
    local_worker_enabled: boolean
    worker_interval: number
    service_token: string
    service_token_set: boolean
    max_kss_chars: number
    min_chunk_ratio: number
    semantic_percentile: number
  }
  storage: {
    backend: string
    databricks_catalog: string
    databricks_schema: string
    databricks_volume: string
    endpoint: string
    access_key: string
    region: string
    use_ssl: boolean
    bucket: string
    annotation_bucket: string
    classification_bucket: string
    models_bucket?: string
    presign_expiry: number
    secret_key: string
    secret_key_set: boolean
  }
  auth: {
    type: string
    keycloak_server_url: string
    keycloak_realm: string
    keycloak_client_id: string
    keycloak_admin_role: string
    keycloak_superuser_role: string
    keycloak_user_role: string
    keycloak_client_secret: string
    keycloak_client_secret_set: boolean
    local_jwt_expire_minutes: number
  }
  cors: { origins: string[] }
  llm: {
    provider: string
    server_url: string
    model: string
    max_tokens: number
    temperature: number
    timeout: number
    auth_header: string
    auth_scheme: string
    api_key: string
    api_key_set: boolean
  }
  rerank: {
    provider: string
    server_url: string
    top_n: number
    auth_header: string
    auth_scheme: string
    api_key: string
    api_key_set: boolean
  }
  retrieval: {
    top_k: number
    vector_k: number
    lexical_k: number
    rrf_k: number
    vector_store: string
    vector_store_url: string
    vector_store_api_key: string
    vector_store_api_key_set: boolean
    vector_store_collection_prefix: string
    vector_store_databricks_endpoint: string
    vector_store_databricks_catalog: string
    vector_store_databricks_schema: string
  }
  detection: {
    enabled: boolean
    server_url: string
    lang: string
    min_score: number
    timeout: number
    auth_header: string
    auth_scheme: string
    api_key: string
    api_key_set: boolean
  }
  image_classification: {
    enabled: boolean
    server_url: string
    model: string
    categories: string
    min_pixels: number
    max_images: number
    timeout: number
    small_image_min_kb: number
    auth_header: string
    auth_scheme: string
    api_key: string
    api_key_set: boolean
  }
  image_conversion: {
    hwp_engine: string
    dpi: number
    thumbnail_max: number
    hwp_scale: number
    office_concurrency: number
    office_timeout: number
  }
  preview: { max_rows: number }
  observability: { answer_limit: number }
}

export type ReindexResult = { provider: string; collections: number; vectors: number }

export async function getSettings(): Promise<EffectiveSettings> {
  const res = await authFetch("/api/v1/settings")
  if (!res.ok) await throwOnError(res, "설정 조회 실패")
  return res.json()
}

export async function updateSettings(payload: Record<string, unknown>): Promise<void> {
  const res = await authFetch("/api/v1/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!res.ok) await throwOnError(res, "설정 저장 실패")
}

export async function reindexVectorStore(): Promise<ReindexResult> {
  const res = await authFetch("/api/v1/settings/vector-store/reindex", { method: "POST" })
  if (!res.ok) await throwOnError(res, "벡터 재색인 실패")
  return res.json()
}

export type ConnTestResult = { ok: boolean; message: string }

async function postJson(path: string, body: Record<string, unknown>): Promise<ConnTestResult> {
  const res = await authFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) await throwOnError(res, "요청 실패")
  return res.json()
}

export function testObjectStorage(body: Record<string, unknown>) {
  return postJson("/api/v1/settings/object-storage/test", body)
}
export function initializeObjectStorage(body: Record<string, unknown>) {
  return postJson("/api/v1/settings/object-storage/initialize", body)
}
export function testAuth(body: Record<string, unknown>) {
  return postJson("/api/v1/settings/auth/test", body)
}
export function testDatabricks(body: Record<string, unknown>) {
  return postJson("/api/v1/settings/databricks/test", body)
}
export function testImageClassification(body: Record<string, unknown>) {
  return postJson("/api/v1/settings/image-classification/test", body)
}
