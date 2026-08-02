// 문서에 포함된 이미지 유형(도표/차트/사진 등)을 작은 뱃지로 표시.
// 검색 결과의 문서 그룹 헤더/청크 메타 행에서 공통으로 사용한다(백엔드 image_classification 결과).

import { ImageIcon, Link2 } from "lucide-react"

import { Badge } from "@workspace/ui/components/badge"

import type { ImageRef } from "@/features/search/data/schema"

// 백엔드 분류 카테고리 → 한글 라벨. 미지정 카테고리는 키를 그대로 노출.
export const IMAGE_TYPE_LABEL: Record<string, string> = {
  chart: "차트",
  table: "표",
  diagram: "도표",
  photo: "사진",
  screenshot: "스크린샷",
  formula: "수식",
  logo: "로고",
  other: "기타",
}
const TYPE_LABEL = IMAGE_TYPE_LABEL

export function ImageTypeBadges({
  types,
  className,
}: {
  types?: Record<string, number>
  className?: string
}) {
  const entries = Object.entries(types ?? {}).filter(([, n]) => n > 0)
  if (entries.length === 0) return null
  // 개수 많은 순으로 정렬해 핵심 유형을 앞에 둔다.
  entries.sort((a, b) => b[1] - a[1])
  return (
    <span className={`inline-flex flex-wrap items-center gap-1${className ? ` ${className}` : ""}`}>
      <ImageIcon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
      {entries.map(([type, n]) => (
        <Badge
          key={type}
          variant="secondary"
          className="h-5 shrink-0 font-normal"
          title={`이미지 추출 및 분류: ${TYPE_LABEL[type] ?? type} ${n}개`}
        >
          {TYPE_LABEL[type] ?? type} {n}
        </Badge>
      ))}
    </span>
  )
}

// 문서에서 식별된 이미지 1건(분류 메타데이터 items 형태).
export type DocImageItem = {
  index: number
  page: number | null // 비 PDF(슬라이드 매핑 안 된 zip 미디어 등)는 null
  type: string
  summary?: string
  confidence?: number
  unit?: string // page 단위 — pptx 슬라이드="slide", docx 문단="para"
}

// 위치 라벨 — unit="slide"(pptx) 면 "슬라이드 N", "para"(docx) 면 "문단 N", 그 외 "p.N".
// "img"(html — 본문 흐름 내 등장 순번)는 위치 라벨을 표시하지 않는다.
export function pageLabel(page: number | null | undefined, unit?: string) {
  if (typeof page !== "number") return null
  if (unit === "slide") return `슬라이드 ${page}`
  if (unit === "para") return `문단 ${page}`
  if (unit === "img") return null
  return `p.${page}`
}

// 문서 전체에서 식별된 이미지 목록을 페이지별로 묶어 표시(문서 전체 보기용).
export function DocumentImageList({ items }: { items?: DocImageItem[] }) {
  if (!items || items.length === 0) return null
  // 페이지 → 이미지들(페이지·index 오름차순, 페이지 없음(null)은 뒤로).
  const byPage = new Map<number | null, DocImageItem[]>()
  const sorted = [...items].sort(
    (a, b) => (a.page ?? Infinity) - (b.page ?? Infinity) || a.index - b.index
  )
  for (const it of sorted) {
    const key = it.page ?? null
    const arr = byPage.get(key)
    if (arr) arr.push(it)
    else byPage.set(key, [it])
  }
  return (
    <div className="space-y-1.5">
      {Array.from(byPage, ([page, its]) => (
        <div key={page ?? "none"} className="flex flex-wrap items-start gap-1.5 text-xs">
          <span className="mt-0.5 shrink-0 font-medium text-muted-foreground tabular-nums">
            {pageLabel(page, its[0]?.unit) ?? "본문"}
          </span>
          {its.map((it) => (
            <span
              key={`${it.page}-${it.index}`}
              className="inline-flex max-w-full items-center gap-1 rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-amber-900 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200"
              title={it.summary || undefined}
            >
              <span className="shrink-0 font-medium">{TYPE_LABEL[it.type] ?? it.type}</span>
              {it.summary && <span className="truncate">· {it.summary}</span>}
            </span>
          ))}
        </div>
      ))}
    </div>
  )
}

// 청크에 연결된 이미지(같은 페이지의 도표/차트 등)를 칩으로 표시 — 유형·페이지 + 요약.
export function ChunkImageRefs({ refs }: { refs?: ImageRef[] }) {
  if (!refs || refs.length === 0) return null
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1 text-xs">
      <span className="inline-flex items-center gap-1 text-muted-foreground">
        <Link2 className="size-3.5 shrink-0" aria-hidden />
        연결된 이미지
      </span>
      {refs.map((r, i) => (
        <span
          key={`${r.page}-${r.index}-${i}`}
          className="inline-flex max-w-full items-center gap-1 rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-amber-900 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200"
          title={r.summary || undefined}
        >
          <span className="shrink-0 font-medium">{TYPE_LABEL[r.type] ?? r.type}</span>
          <span className="shrink-0 text-amber-700/80 dark:text-amber-300/70">
            {pageLabel(r.page, r.unit)}
          </span>
          {r.summary && <span className="truncate">· {r.summary}</span>}
        </span>
      ))}
    </div>
  )
}
