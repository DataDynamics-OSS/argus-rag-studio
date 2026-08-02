// 문서 메타데이터 뷰어 — metadata_json(백엔드 extract_metadata 산출)을 파싱해 표로 표시.
// 목록 행의 ℹ️ 아이콘 → Popover. catalog 데이터셋 상세의 메타데이터 표시와 동일한
// 테이블 구조(항목 / 값 / 설명)를 따른다.
"use client"

import { Info } from "lucide-react"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@workspace/ui/components/popover"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@workspace/ui/components/tooltip"
import { formatDateTime } from "@/lib/format"

// 정규화 키 → 한글 라벨 (백엔드 app/ingestion/metadata.py 와 일치)
const LABELS: Record<string, string> = {
  format: "형식",
  title: "제목",
  author: "작성자",
  last_saved_by: "최종 저장자",
  subject: "주제",
  keywords: "키워드",
  comments: "메모",
  created: "생성",
  modified: "수정",
  app: "앱",
  language: "언어",
  pages: "페이지",
  sections: "섹션",
  sheets: "시트",
  flags: "플래그",
}
// 정규화 키 → 설명 (catalog 메타데이터 표의 '설명' 열에 대응)
const KEY_DESC: Record<string, string> = {
  format: "원본 파일 형식",
  title: "문서 속성에 기록된 제목(파일명과 별개)",
  author: "문서를 작성한 사람",
  last_saved_by: "마지막으로 저장한 사람",
  subject: "문서 주제",
  keywords: "문서 키워드",
  comments: "문서 메모",
  created: "문서 생성 일시",
  modified: "문서 최종 수정 일시",
  app: "문서를 만든 응용프로그램",
  language: "문서 언어",
  pages: "페이지 수",
  sections: "구역(섹션) 수",
  sheets: "시트 수",
  flags: "포맷 플래그(압축·암호화 등)",
}
// 날짜로 표시할 키 (yyyy-MM-dd HH:mm:ss 포맷)
const DATE_KEYS = new Set(["created", "modified"])
// 형식(format) 값 → 친숙한 표시명. hwp/hwpx 는 아래아 한글 네이티브 포맷.
const FORMAT_LABEL: Record<string, string> = {
  hwp: "아래아 한글 (HWP)",
  hwpx: "아래아 한글 (HWPX)",
  pdf: "PDF",
  docx: "Word (DOCX)",
  xlsx: "Excel (XLSX)",
}
// 앱(app) 내부 코드 → 친숙한 표시명. 기존 데이터(재처리 전)까지 표시 시점에 보정.
// 제품명 코드("WORDPROCESSOR"/"HWP")만 "아래아 한글"로 치환하고 버전은 유지한다.
// 예: "WORDPROCESSOR 5.1.1.0" → "아래아 한글 5.1.1.0"
function normalizeApp(v: string): string {
  const m = v.match(/^\s*(?:WORDPROCESSOR|HWP)\b\s*(.*)$/i)
  if (m) return `아래아 한글${m[1] ? ` ${m[1].trim()}` : ""}`
  return v
}

// 무의미한 기본 제목(앱이 자동으로 박는 placeholder) — 부제로 표시하지 않는다.
const GENERIC_TITLE_PATTERNS = [
  /^powerpoint\s*(presentation|프레젠테이션)$/i,
  /^microsoft\s+word\s*-/i, // "Microsoft Word - 문서1.doc"
  /^(제목\s*없음|무제|untitled)$/i,
  /^(문서|document)\s*\d*$/i, // 문서1 / Document1
  /^(프레젠테이션|presentation)\s*\d*$/i,
  /^슬라이드\s*\d*$/i,
  /^(통합\s*문서|workbook|book)\s*\d*$/i, // Excel 기본 "통합 문서1" / "Book1"
]
function isGenericTitle(t: string): boolean {
  const s = t.trim()
  return GENERIC_TITLE_PATTERNS.some((re) => re.test(s))
}
// 표시 순서(나머지 키는 뒤에 그대로)
const ORDER = [
  "format", "title", "author", "last_saved_by", "created", "modified",
  "app", "language", "pages", "sections", "sheets", "subject", "keywords", "comments", "flags",
]

export function parseMetadata(json: string | null): Record<string, unknown> | null {
  if (!json) return null
  try {
    const obj = JSON.parse(json)
    return obj && typeof obj === "object" && Object.keys(obj).length > 0 ? obj : null
  } catch {
    return null
  }
}

/** 문서 내부 제목(파일명과 별개). 없거나 무의미한 기본 제목이면 null. */
export function metadataTitle(json: string | null): string | null {
  const m = parseMetadata(json)
  const t = m?.["title"]
  if (typeof t !== "string" || !t.trim()) return null
  return isGenericTitle(t) ? null : t
}

/** 페이지 수(없으면 null). PDF 는 pages, 그 외 포맷엔 보통 없음. */
export function metadataPages(json: string | null): number | null {
  const m = parseMetadata(json)
  const p = m?.["pages"]
  return typeof p === "number" ? p : null
}

function fmt(k: string, v: unknown): string {
  if (DATE_KEYS.has(k)) return formatDateTime(v as string)
  if (k === "format") return FORMAT_LABEL[String(v).toLowerCase()] ?? String(v)
  if (k === "app") return normalizeApp(String(v))
  if (Array.isArray(v)) return v.join(", ")
  return String(v)
}

export function DocumentMetadata({ json }: { json: string | null }) {
  const meta = parseMetadata(json)
  if (!meta) return null
  const ordered = ORDER.filter((k) => k in meta)
  const rest = Object.keys(meta).filter((k) => !ORDER.includes(k))
  const keys = [...ordered, ...rest]

  return (
    <Popover>
      <TooltipProvider delayDuration={150}>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <button
                type="button"
                aria-label="문서 메타데이터"
                className="shrink-0 text-muted-foreground/60 transition-colors hover:text-foreground"
              >
                <Info className="size-3.5" />
              </button>
            </PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent>클릭시 상세 정보를 볼 수 있습니다.</TooltipContent>
        </Tooltip>
      </TooltipProvider>
      <PopoverContent align="start" className="w-[40.8rem] overflow-hidden p-0">
        <div className="border-b bg-muted/40 px-3 py-2 text-sm font-medium text-black">
          문서 메타데이터
        </div>
        <div className="max-h-80 overflow-y-auto p-3">
          <div className="overflow-hidden rounded-md border">
            <table className="w-full table-fixed border-collapse text-sm text-black">
              <colgroup>
                <col className="w-28" />
                <col className="w-[40%]" />
                <col />
              </colgroup>
              <tbody>
                {keys.map((k) => (
                  <tr key={k}>
                    <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">
                      {LABELS[k] ?? k}
                    </th>
                    <td className="break-words border px-3 py-2 align-middle text-black">
                      {fmt(k, meta[k])}
                    </td>
                    <td className="border px-3 py-2 align-middle text-sm text-black">
                      {KEY_DESC[k] ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}
