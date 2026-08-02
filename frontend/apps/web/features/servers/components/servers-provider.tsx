"use client"

import React, { useCallback, useEffect, useRef, useState } from "react"

import useDialogState from "@/hooks/use-dialog-state"
import { fetchServers, type PaginatedServers } from "../api"
import { type Server } from "../data/schema"

type ServersDialogType = "delete" | "register" | "unregister" | "terminal" | "terminal-warning" | "inspect" | "top" | "processes" | "services"

type SearchParams = {
  status: string[]
  search: string
}

type ServersContextType = {
  open: ServersDialogType | null
  setOpen: (str: ServersDialogType | null) => void
  currentRow: Server | null
  setCurrentRow: React.Dispatch<React.SetStateAction<Server | null>>
  selectedServers: Server[]
  setSelectedServers: React.Dispatch<React.SetStateAction<Server[]>>
  servers: Server[]
  total: number
  page: number
  pageSize: number
  isLoading: boolean
  setPage: (page: number) => void
  setPageSize: (size: number) => void
  searchServers: (params: SearchParams) => void
  refreshServers: (silent?: boolean) => Promise<void>
}

const ServersContext = React.createContext<ServersContextType | null>(null)

export function ServersProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useDialogState<ServersDialogType>(null)
  const [currentRow, setCurrentRow] = useState<Server | null>(null)
  const [selectedServers, setSelectedServers] = useState<Server[]>([])
  const [servers, setServers] = useState<Server[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [isLoading, setIsLoading] = useState(true)

  // Applied filters (last searched values)
  const appliedFiltersRef = useRef<SearchParams>({ status: [], search: "" })

  const loadServers = useCallback(async (params: {
    page: number
    pageSize: number
    status: string[]
    search: string
    silent?: boolean
  }) => {
    try {
      if (!params.silent) setIsLoading(true)
      const data: PaginatedServers = await fetchServers({
        page: params.page,
        pageSize: params.pageSize,
        status: params.status.length > 0 ? params.status : undefined,
        search: params.search || undefined,
      })
      setServers(data.items)
      setTotal(data.total)
    } catch (err) {
      console.error("Failed to fetch servers:", err)
    } finally {
      if (!params.silent) setIsLoading(false)
    }
  }, [])

  // Initial load
  useEffect(() => {
    loadServers({ page: 1, pageSize, status: [], search: "" })
  }, [loadServers, pageSize])

  // Reload when pagination changes (using last applied filters)
  const handleSetPage = useCallback((newPage: number) => {
    setPage(newPage)
    const f = appliedFiltersRef.current
    loadServers({ page: newPage, pageSize, status: f.status, search: f.search })
  }, [loadServers, pageSize])

  const handleSetPageSize = useCallback((size: number) => {
    setPageSize(size)
    setPage(1)
    const f = appliedFiltersRef.current
    loadServers({ page: 1, pageSize: size, status: f.status, search: f.search })
  }, [loadServers])

  // Manual search triggered by Search button
  const searchServers = useCallback((params: SearchParams) => {
    appliedFiltersRef.current = params
    setPage(1)
    loadServers({ page: 1, pageSize, status: params.status, search: params.search })
  }, [loadServers, pageSize])

  const refreshServers = useCallback(async (silent = false) => {
    const f = appliedFiltersRef.current
    await loadServers({ page, pageSize, status: f.status, search: f.search, silent })
  }, [loadServers, page, pageSize])

  // 자동 갱신 — 5초마다 조용히(silent) 재조회해 메트릭/상태(DISCONNECTED 포함)를 최신화.
  useEffect(() => {
    const id = setInterval(() => {
      void refreshServers(true)
    }, 5000)
    return () => clearInterval(id)
  }, [refreshServers])

  return (
    <ServersContext value={{
      open, setOpen,
      currentRow, setCurrentRow,
      selectedServers, setSelectedServers,
      servers, total, page, pageSize, isLoading,
      setPage: handleSetPage, setPageSize: handleSetPageSize,
      searchServers,
      refreshServers,
    }}>
      {children}
    </ServersContext>
  )
}

export const useServers = () => {
  const serversContext = React.useContext(ServersContext)

  if (!serversContext) {
    throw new Error("useServers has to be used within <ServersProvider>")
  }

  return serversContext
}
