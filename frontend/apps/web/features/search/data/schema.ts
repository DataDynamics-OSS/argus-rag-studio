// 검색·생성·챗 도메인 타입 — 백엔드 retrieval/generation 스키마와 매칭.

export type SearchMode = "hybrid" | "vector" | "lexical"

// 비-보안 메타데이터 필터 — 백엔드 retrieval.schemas.FilterCond 와 매칭.
// 보안등급/DRM 은 이 경로로 거르지 않는다(격리는 컬렉션 경계가 담당).
export type FilterOp = "eq" | "in" | "range"

export type FilterCond = {
  field: string
  op: FilterOp
  value?: string | string[] | null // eq: 단일, in: 목록
  gte?: string | null // range 하한
  lte?: string | null // range 상한
}

// 청크에 연결된 이미지 참조(같은 페이지의 도표/차트 등).
export type ImageRef = {
  index: number
  page: number
  type: string
  summary: string
  unit?: string // page 단위 — pptx 슬라이드="slide", docx 문단="para"(표기: 슬라이드/문단 N)
}

export type ChunkHit = {
  chunk_id: string
  document_id: number
  document_uuid: string // 문서 UUID — '문서 전체 보기' 용
  document_name: string
  collection_id: number
  seq: number
  text: string
  score: number
  section_path: string | null
  // 문서에 포함된 이미지 유형→개수(인제스천 이미지 분류 옵션이 켜져 있던 문서만). 예: { chart: 2, table: 1 }
  document_image_types?: Record<string, number>
  // 이 청크에 연결된 이미지(같은 페이지의 도표/차트 등). 페이지 매칭된 청크만 채워짐.
  image_refs?: ImageRef[]
}

export type Citation = {
  marker: number
  chunk_id: string
  document_id: number
  document_name: string
  seq: number
  text: string
}

export type SearchResult = {
  query: string
  mode: string
  reranked: boolean
  distance_metric: string
  hits: ChunkHit[]
  filters_applied?: FilterCond[] // 실제 적용된 필터 에코(없으면 빈 목록/생략)
}

export type QueryResult = {
  answer: string
  citations: Citation[]
  hits: ChunkHit[]
  trace_id: string | null
}

// 페더레이션(여러 컬렉션 통합) 검색·질의
export type CollectionContribution = {
  collection_id: number
  name: string
  embedding_model: string
  candidates: number
  in_final: number
  status: "ok" | "error"
  error: string | null
}

export type FederatedSearchResult = {
  query: string
  mode: string
  reranked: boolean
  top_k: number
  hits: ChunkHit[]
  contributions: CollectionContribution[]
}

export type FederatedQueryResult = {
  answer: string
  citations: Citation[]
  hits: ChunkHit[]
  contributions: CollectionContribution[]
  reranked: boolean
}

export type ChatTurn = { role: "user" | "assistant"; content: string }

// SSE 이벤트 (챗 스트리밍)
export type ChatEvent =
  | { type: "hits"; hits: ChunkHit[]; mode?: string; distance_metric?: string }
  | { type: "token"; text: string }
  | { type: "citations"; citations: Citation[] }
  | { type: "done"; trace_id?: string | null; query?: string }
  | { type: "error"; detail: string }
