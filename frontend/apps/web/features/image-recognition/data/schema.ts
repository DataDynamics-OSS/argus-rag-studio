// 이미지 추출 및 분석 도메인 타입 — 백엔드 imagerecog 스키마와 매칭.

export type RecognizedImage = {
  index: number
  page: number | null // PDF/변환 기반일 때만
  locator: string // 출처 표기(예: "page 3", "word/media/image2.png")
  type: string // chart | table | diagram | photo | ...
  confidence: number
  summary: string // 내용 상세 설명
  ocr_text: string // 이미지 내 텍스트 원문(OCR)
  details: string // 표/차트=마크다운 표, 수식=LaTeX
  width: number
  height: number
  thumbnail: string // data:image/png;base64,… (목록 표시용 축소)
  original: string // data:image/png;base64,… 원본(확대 보기용)
}

export type AnalyzeResult = {
  filename: string
  source_kind: string // PDF | 이미지 | Word | Excel | HWP | HTML ...
  count: number
  extracted: number
  truncated: boolean
  counts_by_type: Record<string, number>
  items: RecognizedImage[]
}

// ── 스트리밍(추출 먼저 표시 → 한 장씩 분석) ───────────────────────────────────

// 카드 분석 상태 — 추출 직후 대기, 분석 시작 시 분석중, 완료/실패.
export type RecognitionStatus = "pending" | "analyzing" | "done" | "error"

// 추출만 끝난 이미지(분석 전) — 썸네일·메타만.
export type ExtractedImage = {
  index: number
  page: number | null
  locator: string
  width: number
  height: number
  thumbnail: string // 목록 표시용 축소
  original: string // 확대 보기용 원본
}

// VLM 분석 결과 본문(item 이벤트의 result).
export type RecognitionResult = {
  type: string
  confidence: number
  summary: string
  ocr_text: string
  details: string
}

// 화면 상태 단위 — 추출 메타 + 상태 + (완료 시) 분석 결과.
export type RecognitionItem = ExtractedImage & {
  status: RecognitionStatus
  result?: RecognitionResult
  error?: string
}

// 추출(extract-stream)·분석(runs/{id}/analyze-stream) SSE 이벤트(백엔드 imagerecog 라우터와 매칭).
export type RecognitionStreamEvent =
  // 추출 단계
  | { type: "start"; run_id: string; filename: string; source_kind: string; total: number }
  | {
      type: "image"
      run_id: string
      index: number
      page: number | null
      locator: string
      width: number
      height: number
      thumbnail: string
      original: string
    }
  // 분석 단계
  | { type: "analyzing"; index: number }
  | { type: "item"; index: number; ok: boolean; result?: RecognitionResult; error?: string }
  // 공통 종료/오류 (추출 done: total·truncated / 분석 done: count·counts_by_type)
  | {
      type: "done"
      run_id?: string
      total?: number
      truncated?: boolean
      count?: number
      counts_by_type?: Record<string, number>
    }
  | { type: "error"; detail: string }

// ── 실행 이력(분류 버킷에 저장된 과거 실행) ──────────────────────────────────

// 이력 목록 항목(메타만). 백엔드 RunListItem 과 매칭.
export type RunListItem = {
  run_id: string
  batch_id: string | null
  filename: string
  source_kind: string | null
  status: string // running | succeeded | failed
  extracted_count: number
  analyzed_count: number
  counts_by_type: Record<string, number>
  size_bytes: number // 실행 폴더(prefix) 전체 저장 크기(byte)
  source_url: string | null // URL 가져오기면 원본 페이지 URL(파일명은 HTML 타이틀)
  error: string | null
  created_by: string | null
  created_at: string | null
  finished_at: string | null
}

export type PaginatedRuns = {
  items: RunListItem[]
  total: number
  page: number
  page_size: number
}

// 이력 상세의 이미지 1장 — presigned URL + 분석 결과(플랫).
export type RunImageItem = {
  index: number
  page: number | null
  locator: string
  width: number
  height: number
  original_url: string
  thumb_url: string
  type: string
  confidence: number
  summary: string
  ocr_text: string
  details: string
}

export type RunDetail = RunListItem & {
  truncated: boolean
  source_download_url: string // 업로드 원본 파일 presigned 다운로드 URL(없으면 빈 값)
  source_filename: string // 업로드 원본 파일명
  items: RunImageItem[]
  // source_url 은 RunListItem 에서 상속 — URL 가져오기의 원본 페이지 URL
}
// (RunDetail: 백엔드 imagerecog 스키마와 매칭)
