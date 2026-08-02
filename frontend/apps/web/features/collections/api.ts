// 컬렉션 REST 클라이언트 — authFetch 로 JWT 를 실어 백엔드 /api/v1/collections 호출.

import { authFetch, throwOnError } from "@/features/auth/auth-fetch"
import type {
  Collection,
  CollectionCreateInput,
  CollectionReindexInput,
  CollectionReindexResult,
  CollectionUpdateInput,
  LocalEmbeddingModel,
  PaginatedCollections,
  ParseStrategyInfo,
  TransformInfo,
} from "./data/schema"

const BASE = "/api/v1/collections"

/** 인제스천 파이프라인에 끼울 수 있는 보강 transform 레지스트리(파이프라인 빌더용). */
export async function getIngestionTransforms(): Promise<{ transforms: TransformInfo[] }> {
  const res = await authFetch(`/api/v1/ingestion/transforms`)
  if (!res.ok) await throwOnError(res, "보강 transform 목록 조회 실패")
  return res.json()
}

export async function listCollections(params?: {
  status?: string
  search?: string
  page?: number
  page_size?: number
}): Promise<PaginatedCollections> {
  const q = new URLSearchParams()
  if (params?.status) q.set("status", params.status)
  if (params?.search) q.set("search", params.search)
  if (params?.page) q.set("page", String(params.page))
  if (params?.page_size != null) q.set("page_size", String(params.page_size))
  const res = await authFetch(`${BASE}?${q.toString()}`)
  if (!res.ok) await throwOnError(res, "컬렉션 목록 조회 실패")
  return res.json()
}

// 외부 노출 식별자는 컬렉션 UUID(collection_id). 내부 PK(id)는 응답에 함께 온다.
export async function getCollection(collectionUuid: string): Promise<Collection> {
  const res = await authFetch(`${BASE}/${collectionUuid}`)
  if (!res.ok) await throwOnError(res, "컬렉션 조회 실패")
  return res.json()
}

export async function createCollection(input: CollectionCreateInput): Promise<Collection> {
  const res = await authFetch(BASE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "컬렉션 생성 실패")
  return res.json()
}

export async function updateCollection(
  id: number,
  input: CollectionUpdateInput
): Promise<Collection> {
  const res = await authFetch(`${BASE}/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "컬렉션 수정 실패")
  return res.json()
}

export async function reindexCollection(
  id: number,
  input: CollectionReindexInput
): Promise<CollectionReindexResult> {
  const res = await authFetch(`${BASE}/${id}/reindex`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "재인덱싱 실패")
  return res.json()
}

export async function deleteCollection(id: number): Promise<void> {
  const res = await authFetch(`${BASE}/${id}`, { method: "DELETE" })
  if (!res.ok) await throwOnError(res, "컬렉션 삭제 실패")
}

/** FastEmbed 로컬 임베딩 지원 모델 목록(벡터 컬럼 차원에 맞는 것). */
export async function listLocalEmbeddingModels(
  dim?: number
): Promise<{ dim: number; models: LocalEmbeddingModel[] }> {
  const q = dim != null ? `?dim=${dim}` : ""
  const res = await authFetch(`/api/v1/embedding/local-models${q}`)
  if (!res.ok) await throwOnError(res, "로컬 임베딩 모델 목록 조회 실패")
  return res.json()
}

/** 임베딩 서버 접속 테스트(health 체크). 실패 시 throwOnError. */
export async function checkEmbeddingServer(serverUrl: string): Promise<{ ok: boolean; url: string }> {
  const res = await authFetch(`/api/v1/embedding/health`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ server_url: serverUrl }),
  })
  if (!res.ok) await throwOnError(res, "서버 연결 실패")
  return res.json()
}

/** 리랭커 서버 접속 테스트 — 입력 URL 의 /v1/models 로 연결·모델 목록을 확인한다. */
export async function checkRerankServer(
  serverUrl: string
): Promise<{ ok: boolean; models: string[] }> {
  const res = await authFetch(`/api/v1/embedding/rerank-health`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ server_url: serverUrl }),
  })
  if (!res.ok) await throwOnError(res, "리랭커 서버 연결 실패")
  return res.json()
}

/** 리랭커 서버(rerank.server_url)가 제공하는 cross-encoder 모델 목록을 가져온다. */
export async function listRerankModels(): Promise<{ models: string[] }> {
  const res = await authFetch(`/api/v1/embedding/rerank-models`)
  if (!res.ok) await throwOnError(res, "리랭커 모델 목록 조회 실패")
  return res.json()
}

/** 문서 파싱 전략 목록 + 가용성(의존성 설치 여부). */
export async function listParseStrategies(): Promise<{ strategies: ParseStrategyInfo[] }> {
  const res = await authFetch(`/api/v1/embedding/parse-strategies`)
  if (!res.ok) await throwOnError(res, "파싱 전략 목록 조회 실패")
  return res.json()
}

/** 로컬(in-process) FastEmbed cross-encoder 리랭커 모델 목록(서버 불필요). */
export async function listLocalRerankModels(): Promise<{
  models: { model: string; size_gb: number | null }[]
}> {
  const res = await authFetch(`/api/v1/embedding/local-rerank-models`)
  if (!res.ok) await throwOnError(res, "로컬 리랭커 모델 목록 조회 실패")
  return res.json()
}

/** OpenAI 호환 서버가 제공하는 모델 ID 목록을 가져온다. */
export async function listServerEmbeddingModels(
  serverUrl?: string | null
): Promise<{ models: string[] }> {
  const res = await authFetch(`/api/v1/embedding/server-models`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ server_url: serverUrl || null }),
  })
  if (!res.ok) await throwOnError(res, "모델 목록 조회 실패")
  return res.json()
}

/** OpenAI 호환 서버에 샘플을 보내 임베딩 차원을 자동 감지한다. */
export async function probeEmbeddingDimension(
  model: string,
  serverUrl?: string | null
): Promise<{ dim: number; column_dim: number; matches: boolean }> {
  const res = await authFetch(`/api/v1/embedding/probe`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, server_url: serverUrl || null }),
  })
  if (!res.ok) await throwOnError(res, "차원 감지 실패")
  return res.json()
}
