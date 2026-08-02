"use client"

import { type Column } from "@tanstack/react-table"
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react"

import { cn } from "@workspace/ui/lib/utils"

type SortableHeaderProps<TData, TValue> = {
  column: Column<TData, TValue>
  title: string
  className?: string
}

/** 표준 그리드 헤더용 클릭-정렬 헤더(드롭다운 없이 화살표 표시). 정렬 불가 컬럼은 평문 렌더. */
export function SortableHeader<TData, TValue>({
  column,
  title,
  className,
}: SortableHeaderProps<TData, TValue>) {
  if (!column.getCanSort()) {
    return <div className={cn("flex items-center justify-center", className)}>{title}</div>
  }

  const sorted = column.getIsSorted()
  return (
    <button
      type="button"
      onClick={() => column.toggleSorting(sorted === "asc")}
      className={cn(
        "inline-flex select-none items-center justify-center gap-1 hover:text-primary",
        className
      )}
    >
      <span>{title}</span>
      {sorted === "asc" ? (
        <ArrowUp className="size-3.5" />
      ) : sorted === "desc" ? (
        <ArrowDown className="size-3.5" />
      ) : (
        <ChevronsUpDown className="size-3.5 opacity-40" />
      )}
    </button>
  )
}
