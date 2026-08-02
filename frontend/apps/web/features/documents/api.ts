// 문서 REST 클라이언트 — 컬렉션 종속 경로 + 단건 평면 경로.

import { authFetch, throwOnError } from "@/features/auth/auth-fetch"
import type {
  DocumentChunks,
  DocumentCreateInput,
  PaginatedDocuments,
  RagDocument,
} from "./data/schema"

export async function listDocuments(
  collectionId: number,
  params?: { status?: string; search?: string; page?: number; page_size?: number }
): Promise<PaginatedDocuments> {
  const q = new URLSearchParams()
  if (params?.status) q.set("status", params.status)
  if (params?.search) q.set("search", params.search)
  if (params?.page) q.set("page", String(params.page))
  if (params?.page_size != null) q.set("page_size", String(params.page_size))
  const res = await authFetch(
    `/api/v1/collections/${collectionId}/documents?${q.toString()}`
  )
  if (!res.ok) await throwOnError(res, "문서 목록 조회 실패")
  return res.json()
}

export async function createDocument(
  collectionId: number,
  input: DocumentCreateInput
): Promise<RagDocument> {
  const res = await authFetch(`/api/v1/collections/${collectionId}/documents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
  if (!res.ok) await throwOnError(res, "문서 등록 실패")
  return res.json()
}

// 외부 노출 식별자는 문서 UUID(document_id). 컬렉션 종속 목록만 collection.id(정수) 사용.

/** 문서 단건 조회(메타데이터 포함 — 이미지 분류 결과 등). */
export async function getDocument(documentUuid: string): Promise<RagDocument> {
  const res = await authFetch(`/api/v1/documents/${documentUuid}`)
  if (!res.ok) await throwOnError(res, "문서 조회 실패")
  return res.json()
}

export async function deleteDocument(documentUuid: string): Promise<void> {
  const res = await authFetch(`/api/v1/documents/${documentUuid}`, { method: "DELETE" })
  if (!res.ok) await throwOnError(res, "문서 삭제 실패")
}

/** 문서 원본 파일 바이트(동일출처 인증 fetch). 파일 보기 — pdf/이미지/HWP/텍스트 등. */
export async function getDocumentFileBytes(documentUuid: string): Promise<ArrayBuffer> {
  const res = await authFetch(`/api/v1/documents/${documentUuid}/file`)
  if (!res.ok) await throwOnError(res, "원본 로드 실패")
  return res.arrayBuffer()
}

/** 오피스 원본 → PDF 변환 바이트. 변환 불가/미설치(비 200)면 null 반환(프런트가 폴백). */
export async function getDocumentOfficePdf(documentUuid: string): Promise<ArrayBuffer | null> {
  const res = await authFetch(`/api/v1/documents/${documentUuid}/office-pdf`)
  if (!res.ok) return null
  return res.arrayBuffer()
}

/** 문서별 인제스천 현황 + 청크 목록(임베딩 유무 포함). */
export async function getDocumentChunks(
  documentUuid: string,
  params?: { page?: number; page_size?: number }
): Promise<DocumentChunks> {
  const q = new URLSearchParams()
  if (params?.page) q.set("page", String(params.page))
  if (params?.page_size != null) q.set("page_size", String(params.page_size))
  const res = await authFetch(`/api/v1/documents/${documentUuid}/chunks?${q.toString()}`)
  if (!res.ok) await throwOnError(res, "청크 조회 실패")
  return res.json()
}
