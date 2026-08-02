// 문서(Document) 도메인 타입 — 백엔드 app/documents/schemas.py 와 1:1 매칭.

export type SourceType =
  | "upload"
  | "s3"
  | "web"
  | "confluence"
  | "notion"
  | "database"
  | "api"

export type DocumentStatus = "registered" | "processing" | "indexed" | "failed"

export type RagDocument = {
  id: number
  document_id: string
  collection_id: number
  name: string
  source_type: string
  source_uri: string | null
  content_hash: string | null
  size_bytes: number
  status: string
  chunk_count: number
  metadata_json: string | null
  indexed_at: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export type DocumentCreateInput = {
  name: string
  source_type?: SourceType
  source_uri?: string | null
  content_hash?: string | null
  size_bytes?: number
  metadata_json?: string | null
}

export type PaginatedDocuments = {
  items: RagDocument[]
  total: number
  page: number
  page_size: number
}

// 청크 인스펙터 — 문서별 인제스천 현황 + 청크 목록(백엔드 DocumentChunksResponse).
export type ChunkInspectItem = {
  chunk_id: string
  seq: number
  section_path: string | null
  char_count: number | null
  token_count: number | null
  has_embedding: boolean
  text: string
}

export type DocumentChunks = {
  items: ChunkInspectItem[]
  total: number
  page: number
  page_size: number
  embedded: number
  status: string
  last_stage: string | null
  last_error: string | null
}
