"use client"

// 클라이언트 페이징 훅 — 전체를 한 번에 받아오는 목록을 컬렉션 목록과 동일한 UX(페이지당 행 수 +
// 페이지 이동)로 페이징한다. DataTablePagination 에 넘길 table 인스턴스와 현재 페이지 슬라이스를 돌려준다.

import { useEffect, useState } from "react"
import { getCoreRowModel, useReactTable } from "@tanstack/react-table"

export function useClientPagination<T>(items: T[], initialPageSize = 10) {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(initialPageSize)

  const total = items.length
  const pageCount = Math.max(1, Math.ceil(total / pageSize))

  // 데이터가 줄어 현재 페이지가 범위를 벗어나면 마지막 페이지로 보정.
  useEffect(() => {
    if (page > pageCount) setPage(pageCount)
  }, [page, pageCount])

  const table = useReactTable<T>({
    data: items,
    columns: [],
    pageCount,
    state: { pagination: { pageIndex: page - 1, pageSize } },
    manualPagination: true,
    getCoreRowModel: getCoreRowModel(),
    onPaginationChange: (updater) => {
      const next =
        typeof updater === "function" ? updater({ pageIndex: page - 1, pageSize }) : updater
      if (next.pageSize !== pageSize) {
        setPageSize(next.pageSize)
        setPage(1)
      } else {
        setPage(next.pageIndex + 1)
      }
    },
  })

  const pageItems = items.slice((page - 1) * pageSize, page * pageSize)
  return { table, pageItems, total, page, pageSize }
}
