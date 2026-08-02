// 검색·생성·챗 REST/SSE 클라이언트.

import { authFetch, throwOnError } from "@/features/auth/auth-fetch"

export type ChunkEvidence = {
  document_uuid: string
  document_name: string
  available: boolean
  page?: number
  total_pages?: number
  reason?: string
}

/** 검색 결과(청크)의 근거 — 원본 HWP/HWPX 의 해당 페이지 번호(추정)와 총 페이지. */
export async function getChunkEvidence(chunkId: string): Promise<ChunkEvidence> {
  const res = await authFetch(`/api/v1/documents/by-chunk/${chunkId}/evidence`)
  if (!res.ok) await throwOnError(res, "근거 페이지 조회 실패")
  return res.json()
}

/** 원본 문서의 page(1-base) 페이지를 PNG Blob 으로(인증 헤더 필요 → authFetch). */
export async function getDocumentPageImage(documentUuid: string, page: number): Promise<Blob> {
  const res = await authFetch(`/api/v1/documents/${documentUuid}/page/${page}`)
  if (!res.ok) await throwOnError(res, "페이지 이미지 로드 실패")
  return res.blob()
}
import type {
  ChatEvent,
  ChatTurn,
  FederatedQueryResult,
  FederatedSearchResult,
  FilterCond,
  QueryResult,
  SearchMode,
  SearchResult,
} from "./data/schema"

type FederatedBody = {
  query: string
  collection_ids: number[]
  mode: SearchMode
  per_collection_k?: number
  top_k?: number
  rerank?: boolean
  filters?: FilterCond[]
  pipeline_id?: number // 지정 시 파이프라인 활성 버전 설정이 검색·리랭크·생성을 결정(요청 mode/rerank 무시)
}

export async function search(
  collectionId: number,
  body: { query: string; mode: SearchMode; top_k?: number; rerank?: boolean; filters?: FilterCond[]; pipeline_id?: number }
): Promise<SearchResult> {
  const res = await authFetch(`/api/v1/collections/${collectionId}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) await throwOnError(res, "검색 실패")
  return res.json()
}

export async function query(
  collectionId: number,
  body: { query: string; mode: SearchMode; top_k?: number; rerank?: boolean; filters?: FilterCond[]; pipeline_id?: number }
): Promise<QueryResult> {
  const res = await authFetch(`/api/v1/collections/${collectionId}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) await throwOnError(res, "답변 생성 실패")
  return res.json()
}

// 여러 컬렉션을 한 번에 검색(이종 임베딩 공간) → RRF 병합 → (선택) 글로벌 리랭크.
export async function searchFederated(body: FederatedBody): Promise<FederatedSearchResult> {
  const res = await authFetch(`/api/v1/search/federated`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) await throwOnError(res, "통합 검색 실패")
  return res.json()
}

// 페더레이션 검색 → 병합 결과로 인용 포함 답변 생성.
export async function queryFederated(body: FederatedBody): Promise<FederatedQueryResult> {
  const res = await authFetch(`/api/v1/query/federated`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) await throwOnError(res, "통합 답변 생성 실패")
  return res.json()
}

/**
 * 멀티턴 챗 SSE 스트리밍. POST 바디로 history 를 보내므로 EventSource 대신
 * fetch + ReadableStream 으로 직접 SSE 를 파싱한다. onEvent 로 이벤트를 전달한다.
 */
export async function chatStream(
  collectionId: number,
  body: { messages: ChatTurn[]; mode: SearchMode; top_k?: number; rerank?: boolean; pipeline_id?: number },
  onEvent: (e: ChatEvent) => void
): Promise<void> {
  const res = await authFetch(`/api/v1/collections/${collectionId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok || !res.body) {
    await throwOnError(res, "챗 스트리밍 실패")
  }
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split("\n\n")
    buffer = frames.pop() ?? ""
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data:"))
      if (!line) continue
      try {
        onEvent(JSON.parse(line.slice(5).trim()) as ChatEvent)
      } catch {
        // 부분 프레임 무시
      }
    }
  }
}
