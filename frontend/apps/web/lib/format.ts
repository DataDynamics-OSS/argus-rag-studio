// 표시용 포맷 유틸 — 화면의 모든 날짜는 yyyy-MM-dd HH:mm:ss 로 통일한다.

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

/** Date 를 `yyyy-MM-dd HH:mm:ss`(로컬) 로 포맷. */
function fromDate(d: Date): string {
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  )
}

/**
 * 임의의 날짜 값을 `yyyy-MM-dd HH:mm:ss` 로 표시.
 * - ISO 8601(백엔드 created_at/indexed_at), `yyyy-MM-dd HH:mm:ss`(OLE),
 *   PDF `D:YYYYMMDDHHmmSS` 형식을 처리한다.
 * - 파싱 불가하면 원본 문자열을 그대로 반환(메타데이터의 비정형 값 보호).
 */
export function formatDateTime(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—"
  if (typeof value === "number") return fromDate(new Date(value))

  const s = String(value).trim()

  // PDF: "D:20230101120000+09'00'"
  const pdf = s.match(/^D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?/)
  if (pdf) {
    const [, y, mo, d, h = "00", mi = "00", se = "00"] = pdf
    return `${y}-${mo}-${d} ${h}:${mi}:${se}`
  }

  const t = Date.parse(s)
  if (!Number.isNaN(t)) return fromDate(new Date(t))

  return s
}

/**
 * 상대 시각 표시 — 방금/N분/N시간/N일/N주 전, 4주 이상은 절대 날짜(formatDateTime)로 폴백.
 * 목록에서 "최근에 뭐 바뀌었나"를 빠르게 파악할 때 쓴다.
 */
export function relativeTime(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—"
  const t = typeof value === "number" ? value : Date.parse(String(value))
  if (Number.isNaN(t)) return formatDateTime(value)
  const min = Math.floor((Date.now() - t) / 60000)
  if (min < 0) return formatDateTime(value)
  if (min < 1) return "방금 전"
  if (min < 60) return `${min}분 전`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}시간 전`
  const day = Math.floor(hr / 24)
  if (day < 7) return `${day}일 전`
  if (day < 28) return `${Math.floor(day / 7)}주 전`
  return formatDateTime(value)
}

/**
 * 경과 시간(초)을 한국어 기간 문자열로 — 최대 2단위로 압축.
 * 예: 45초 / 12분 / 3시간 20분 / 9일 6시간. (마지막 하트비트 등 "N 전" 표기에 사용)
 */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || seconds < 0) return "—"
  const s = Math.floor(seconds)
  if (s < 60) return `${s}초`
  const min = Math.floor(s / 60)
  if (min < 60) return `${min}분`
  const hr = Math.floor(min / 60)
  if (hr < 24) {
    const m = min % 60
    return m ? `${hr}시간 ${m}분` : `${hr}시간`
  }
  const day = Math.floor(hr / 24)
  const h = hr % 24
  return h ? `${day}일 ${h}시간` : `${day}일`
}

/** 바이트 크기를 사람이 읽기 쉬운 단위로 표시(B/KB/MB/GB/TB). */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return "—"
  if (bytes < 1024) return `${bytes} B`
  const units = ["KB", "MB", "GB", "TB", "PB"]
  let v = bytes / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}`
}

// 확장자 → 파일 유형(앱) 표시명 매핑표. hwp/hwpx 는 아래아 한글 네이티브 포맷.
const FILE_TYPE_LABELS: Record<string, string> = {
  hwp: "아래아 한글",
  hwpx: "아래아 한글",
  pdf: "PDF",
  doc: "Word",
  docx: "Word",
  xls: "Excel",
  xlsx: "Excel",
  ppt: "PowerPoint",
  pptx: "PowerPoint",
  txt: "텍스트",
  md: "Markdown",
  markdown: "Markdown",
  csv: "CSV",
  tsv: "TSV",
  json: "JSON",
  xml: "XML",
  html: "HTML",
  htm: "HTML",
  yaml: "YAML",
  yml: "YAML",
  toml: "TOML",
  ini: "INI",
  cfg: "설정",
  conf: "설정",
  log: "로그",
  rst: "reStructuredText",
  tex: "LaTeX",
  // 소스코드
  py: "Python",
  js: "JavaScript",
  jsx: "JavaScript",
  ts: "TypeScript",
  tsx: "TypeScript",
  java: "Java",
  go: "Go",
  rs: "Rust",
  c: "C",
  cc: "C++",
  cpp: "C++",
  h: "C/C++ 헤더",
  hpp: "C++ 헤더",
  cs: "C#",
  rb: "Ruby",
  php: "PHP",
  sh: "셸 스크립트",
  bash: "셸 스크립트",
  sql: "SQL",
  kt: "Kotlin",
  swift: "Swift",
  scala: "Scala",
}

/** 파일명(확장자) → 파일 유형 표시명. 매핑 없으면 확장자 대문자, 확장자 없으면 "—". */
export function fileTypeLabel(filename: string): string {
  const dot = (filename || "").lastIndexOf(".")
  const ext = dot >= 0 ? filename.slice(dot + 1).toLowerCase() : ""
  return FILE_TYPE_LABELS[ext] ?? (ext ? ext.toUpperCase() : "—")
}
