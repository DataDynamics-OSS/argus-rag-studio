/**
 * 검색 메타데이터 필터 입력 바.
 *
 * 비-보안 메타데이터(문서유형·부서·기간 등)로 검색을 좁히는 필터 행을 편집한다.
 * 행 UI(FilterRow) → 백엔드 FilterCond[] 변환은 `rowsToFilters` 가 담당한다.
 * 보안등급/DRM 은 의도적으로 필드 목록에 없다(격리는 컬렉션 경계 — knowledge-base-design.md §5).
 */
"use client"

import { Plus, X } from "lucide-react"

import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import type { FilterCond, FilterOp } from "@/features/search/data/schema"

// 편집용 행 상태(항상 문자열) — 검색 실행 시 rowsToFilters 로 FilterCond[] 변환.
export type FilterRow = {
  field: string
  op: FilterOp
  value: string // eq: 단일 / in: "값1, 값2"
  gte: string
  lte: string
}

// 백엔드 FILTERABLE_FIELDS 화이트리스트와 일치. label 은 표시용.
// "✓ 지금 적용" = metadata.py 가 자동 추출하는 필드 / 나머지는 P2(분류) 또는 출처 제공 필요.
const FIELDS: { value: string; label: string }[] = [
  { value: "format", label: "파일형식 ✓" },
  { value: "created", label: "작성일 ✓" },
  { value: "modified", label: "수정일 ✓" },
  { value: "language", label: "언어" },
  { value: "doc_type", label: "문서유형" },
  { value: "dept", label: "부서" },
  { value: "source_system", label: "출처시스템" },
]

const OPS: { value: FilterOp; label: string }[] = [
  { value: "eq", label: "일치" },
  { value: "in", label: "포함" },
  { value: "range", label: "범위" },
]

export function emptyRow(): FilterRow {
  return { field: "doc_type", op: "eq", value: "", gte: "", lte: "" }
}

/** 편집 행 → 백엔드 필터 조건. 값이 비어 의미 없는 행은 제외한다. */
export function rowsToFilters(rows: FilterRow[]): FilterCond[] {
  const out: FilterCond[] = []
  for (const r of rows) {
    if (!r.field) continue
    if (r.op === "eq") {
      const v = r.value.trim()
      if (v) out.push({ field: r.field, op: "eq", value: v })
    } else if (r.op === "in") {
      const vals = r.value
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
      if (vals.length) out.push({ field: r.field, op: "in", value: vals })
    } else if (r.op === "range") {
      const cond: FilterCond = { field: r.field, op: "range" }
      if (r.gte.trim()) cond.gte = r.gte.trim()
      if (r.lte.trim()) cond.lte = r.lte.trim()
      if (cond.gte || cond.lte) out.push(cond)
    }
  }
  return out
}

export function MetadataFilterBar({
  rows,
  onChange,
}: {
  rows: FilterRow[]
  onChange: (rows: FilterRow[]) => void
}) {
  function update(i: number, patch: Partial<FilterRow>) {
    onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  }
  function remove(i: number) {
    onChange(rows.filter((_, idx) => idx !== i))
  }

  return (
    <div className="space-y-1.5">
      {rows.map((r, i) => (
        <div key={i} className="flex items-center gap-1.5">
          <Select value={r.field} onValueChange={(v) => update(i, { field: v })}>
            <SelectTrigger className="h-8 w-36 shrink-0 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {FIELDS.map((f) => (
                <SelectItem key={f.value} value={f.value} className="text-xs">
                  {f.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={r.op} onValueChange={(v) => update(i, { op: v as FilterOp })}>
            <SelectTrigger className="h-8 w-20 shrink-0 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {OPS.map((o) => (
                <SelectItem key={o.value} value={o.value} className="text-xs">
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {r.op === "range" ? (
            <>
              <Input
                value={r.gte}
                onChange={(e) => update(i, { gte: e.target.value })}
                placeholder="이상(gte)"
                className="h-8 text-xs text-black"
              />
              <Input
                value={r.lte}
                onChange={(e) => update(i, { lte: e.target.value })}
                placeholder="이하(lte)"
                className="h-8 text-xs text-black"
              />
            </>
          ) : (
            <Input
              value={r.value}
              onChange={(e) => update(i, { value: e.target.value })}
              placeholder={r.op === "in" ? "값1, 값2, ..." : "값"}
              className="h-8 text-xs text-black"
            />
          )}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-8 shrink-0"
            onClick={() => remove(i)}
            aria-label="필터 제거"
          >
            <X className="size-3.5" />
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-7 text-xs"
        onClick={() => onChange([...rows, emptyRow()])}
      >
        <Plus className="size-3.5" /> 메타데이터 필터 추가
      </Button>
    </div>
  )
}
