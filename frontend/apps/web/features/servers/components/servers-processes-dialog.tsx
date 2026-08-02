"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Download,
  FileText,
  Filter,
  Globe,
  List,
  Loader2,
  Skull,
  X,
} from "lucide-react"

import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@workspace/ui/components/dropdown-menu"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@workspace/ui/components/alert-dialog"
import { fetchProcesses, killProcess } from "../api"
import { type Server as ServerType } from "../data/schema"

/* eslint-disable @typescript-eslint/no-explicit-any */

type ServersProcessesDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  currentRow: ServerType
}

type SortField =
  | "pid"
  | "username"
  | "cpu_percent"
  | "memory_rss"
  | "memory_vms"
  | "status"
  | "num_threads"
  | "memory_percent"

type SortDir = "asc" | "desc"

type ProcessRow = {
  pid: number
  ppid: number
  name: string
  username: string
  status: string
  cpu_percent: number
  memory_rss: number
  memory_vms: number
  memory_percent?: number
  create_time: number
  cmdline: string
  num_threads: number
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0B"
  const k = 1024
  const sizes = ["B", "KB", "MB", "GB", "TB"]
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)}${sizes[i]}`
}

const COLUMNS: {
  key: SortField
  label: string
  align: "left" | "right" | "center"
  width: string
}[] = [
  { key: "pid", label: "PID", align: "right", width: "w-20" },
  { key: "username", label: "USER", align: "left", width: "w-24" },
  { key: "cpu_percent", label: "CPU%", align: "right", width: "w-16" },
  { key: "memory_percent" as SortField, label: "MEM%", align: "right", width: "w-16" },
  { key: "memory_rss", label: "RSS", align: "right", width: "w-20" },
  { key: "memory_vms", label: "VIRT", align: "right", width: "w-20" },
  { key: "status", label: "S", align: "center", width: "w-14" },
  { key: "num_threads", label: "THR", align: "right", width: "w-14" },
]

export function ServersProcessesDialog({
  open,
  onOpenChange,
  currentRow,
}: ServersProcessesDialogProps) {
  const [processes, setProcesses] = useState<ProcessRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sortField, setSortField] = useState<SortField>("pid")
  const [sortDir, setSortDir] = useState<SortDir>("asc")
  const [filter, setFilter] = useState("")
  const [userFilter, setUserFilter] = useState<string>("__all__")
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [killConfirm, setKillConfirm] = useState(false)
  const [killing, setKilling] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadProcesses = useCallback(async () => {
    try {
      const result = await fetchProcesses(currentRow.hostname)
      const procs = (result.processes ?? []) as ProcessRow[]
      setProcesses(procs)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "프로세스를 불러오지 못했습니다")
    } finally {
      setLoading(false)
    }
  }, [currentRow.hostname])

  useEffect(() => {
    if (open) {
      setLoading(true)
      setProcesses([])
      setSelected(new Set())
      setFilter("")
      setUserFilter("__all__")
      setSortField("pid")
      setSortDir("asc")
      loadProcesses()
      intervalRef.current = setInterval(loadProcesses, 5000)
    } else {
      setProcesses([])
      setError(null)
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [open, loadProcesses])

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortField(field)
      setSortDir(field === "pid" || field === "username" || field === "status" ? "asc" : "desc")
    }
  }

  const userList = useMemo(() => {
    const users = new Set(processes.map((p) => p.username))
    return Array.from(users).sort((a, b) => a.localeCompare(b))
  }, [processes])

  const filtered = useMemo(() => {
    let list = processes
    if (userFilter !== "__all__") {
      list = list.filter((p) => p.username === userFilter)
    }
    if (filter.trim()) {
      const q = filter.toLowerCase()
      list = list.filter(
        (p) =>
          p.cmdline.toLowerCase().includes(q) ||
          p.name.toLowerCase().includes(q)
      )
    }
    const sorted = [...list].sort((a, b) => {
      const fa = sortField
      const va = a[fa] ?? 0
      const vb = b[fa] ?? 0
      if (typeof va === "string" && typeof vb === "string") {
        return sortDir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va)
      }
      const na = Number(va)
      const nb = Number(vb)
      return sortDir === "asc" ? na - nb : nb - na
    })
    return sorted
  }, [processes, filter, sortField, sortDir])

  const toggleSelect = (pid: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(pid)) next.delete(pid)
      else next.add(pid)
      return next
    })
  }

  const toggleSelectAll = () => {
    if (selected.size === filtered.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(filtered.map((p) => p.pid)))
    }
  }

  const handleKill = async () => {
    setKilling(true)
    try {
      const pids = Array.from(selected)
      await Promise.all(
        pids.map((pid) => killProcess(currentRow.hostname, pid, "SIGKILL"))
      )
      setSelected(new Set())
      await loadProcesses()
    } catch (err) {
      console.error("Kill failed:", err)
    } finally {
      setKilling(false)
      setKillConfirm(false)
    }
  }

  const buildHtml = useCallback(() => {
    const now = new Date().toLocaleString()
    const rows = filtered
      .map(
        (p) => `<tr>
      <td class="r">${p.pid}</td>
      <td>${p.username}</td>
      <td class="r">${p.cpu_percent.toFixed(1)}</td>
      <td class="r">${(p.memory_percent ?? 0).toFixed(1)}</td>
      <td class="r">${formatBytes(p.memory_rss)}</td>
      <td class="r">${formatBytes(p.memory_vms)}</td>
      <td class="c">${p.status?.[0]?.toUpperCase() ?? "?"}</td>
      <td class="r">${p.num_threads}</td>
      <td class="cmd">${(p.cmdline || p.name || "-").replace(/</g, "&lt;").replace(/>/g, "&gt;")}</td>
    </tr>`
      )
      .join("\n")

    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Processes - ${currentRow.hostname}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 20px; color: #1a1a1a; }
  h1 { font-size: 18px; margin-bottom: 4px; }
  .meta { font-size: 13px; color: #666; margin-bottom: 16px; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { border: 1px solid #ddd; padding: 6px 10px; white-space: nowrap; }
  th { background: #f5f5f5; font-weight: 600; text-align: left; }
  th.r, td.r { text-align: right; }
  th.c, td.c { text-align: center; }
  td.cmd { white-space: normal; word-break: break-all; font-family: monospace; font-size: 12px; color: #555; max-width: 500px; }
  tr:nth-child(even) { background: #fafafa; }
  @media print { body { margin: 10px; } h1 { font-size: 15px; } table { font-size: 11px; } }
</style>
</head>
<body>
<h1>Processes - ${currentRow.hostname}</h1>
<div class="meta">${currentRow.ipAddress} &middot; ${filtered.length} processes &middot; ${now}</div>
<table>
<thead>
  <tr>
    <th class="r">PID</th><th>USER</th><th class="r">CPU%</th><th class="r">MEM%</th>
    <th class="r">RSS</th><th class="r">VIRT</th><th class="c">S</th><th class="r">THR</th><th>COMMAND</th>
  </tr>
</thead>
<tbody>
${rows}
</tbody>
</table>
</body>
</html>`
  }, [filtered, currentRow])

  const downloadHtml = useCallback(() => {
    const html = buildHtml()
    const blob = new Blob([html], { type: "text/html;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `processes-${currentRow.hostname}-${new Date().toISOString().slice(0, 19).replace(/:/g, "")}.html`
    a.click()
    URL.revokeObjectURL(url)
  }, [buildHtml, currentRow])

  const downloadPdf = useCallback(() => {
    const html = buildHtml()
    const win = window.open("", "_blank")
    if (!win) return
    win.document.write(html)
    win.document.close()
    win.onload = () => {
      win.onafterprint = () => win.close()
      win.print()
    }
  }, [buildHtml])

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) return <ArrowUpDown className="h-3 w-3 opacity-30" />
    return sortDir === "asc" ? (
      <ArrowUp className="h-3 w-3" />
    ) : (
      <ArrowDown className="h-3 w-3" />
    )
  }

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange} modal>
        <DialogContent
          className="max-w-6xl p-0 overflow-hidden flex flex-col"
          style={{ maxHeight: "85vh" }}
          showCloseButton={false}
          onPointerDownOutside={(e) => e.preventDefault()}
          onInteractOutside={(e) => e.preventDefault()}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 pt-4 pb-2 border-b shrink-0">
            <DialogHeader className="p-0 space-y-0">
              <DialogTitle className="text-sm font-semibold flex items-center gap-2">
                <List className="h-4 w-4" />
                프로세스 - {currentRow.hostname}
              </DialogTitle>
              <DialogDescription className="text-sm text-muted-foreground">
                {currentRow.ipAddress} · 프로세스 {filtered.length}개
                {filter && ` (필터됨)`} · 5초마다 갱신
              </DialogDescription>
            </DialogHeader>
            <DialogClose className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded hover:bg-muted">
              <X className="h-4 w-4" />
              <span className="sr-only">닫기</span>
            </DialogClose>
          </div>

          {/* Toolbar */}
          <div className="flex items-center gap-2 px-4 py-2 border-b shrink-0">
            <Select value={userFilter} onValueChange={setUserFilter}>
              <SelectTrigger className="h-8 w-40 text-sm">
                <SelectValue placeholder="전체 사용자" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">전체 사용자</SelectItem>
                {userList.map((user) => (
                  <SelectItem key={user} value={user}>
                    {user}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="relative flex-1 max-w-sm">
              <Filter className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                placeholder="명령으로 필터..."
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="pl-8 h-8 text-sm"
              />
              {filter && (
                <button
                  onClick={() => setFilter("")}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className="ml-auto h-8 text-sm font-normal gap-1.5"
                  disabled={filtered.length === 0}
                >
                  <Download className="h-3.5 w-3.5" />
                  내보내기
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={downloadHtml}>
                  <Globe className="h-4 w-4 mr-2" />
                  HTML 다운로드
                </DropdownMenuItem>
                <DropdownMenuItem onClick={downloadPdf}>
                  <FileText className="h-4 w-4 mr-2" />
                  PDF 다운로드
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button
              variant="destructive"
              size="sm"
              className="h-8 text-sm gap-1.5"
              disabled={selected.size === 0 || killing}
              onClick={() => setKillConfirm(true)}
            >
              {killing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Skull className="h-3.5 w-3.5" />
              )}
              종료 ({selected.size})
            </Button>
          </div>

          {/* Loading */}
          {loading && processes.length === 0 && (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              <span className="ml-2 text-muted-foreground text-sm">불러오는 중...</span>
            </div>
          )}

          {/* Error */}
          {error && processes.length === 0 && (
            <div className="px-4 py-8 text-destructive text-center text-sm">{error}</div>
          )}

          {/* Process grid */}
          {processes.length > 0 && (
            <div className="flex-1 min-h-0 overflow-auto px-4 pb-3">
              {/* Grid header */}
              <div className="grid grid-cols-[32px_80px_96px_64px_64px_80px_80px_56px_56px_1fr] gap-0 sticky top-0 bg-background z-10 border-b text-sm font-medium text-muted-foreground">
                <div className="px-1 py-2 flex items-center justify-center">
                  <input
                    type="checkbox"
                    checked={filtered.length > 0 && selected.size === filtered.length}
                    onChange={toggleSelectAll}
                    className="h-3.5 w-3.5 rounded border-muted-foreground/50 cursor-pointer"
                  />
                </div>
                {COLUMNS.map((col) => (
                  <button
                    key={col.key}
                    onClick={() => handleSort(col.key)}
                    className={`px-2 py-2 flex items-center gap-1 hover:text-foreground transition-colors cursor-pointer select-none ${
                      col.align === "right"
                        ? "justify-end"
                        : col.align === "center"
                          ? "justify-center"
                          : "justify-start"
                    }`}
                  >
                    {col.label}
                    <SortIcon field={col.key} />
                  </button>
                ))}
                <div className="px-2 py-2">COMMAND</div>
              </div>

              {/* Grid rows */}
              <div className="text-sm">
                {filtered.map((p) => {
                  const isSelected = selected.has(p.pid)
                  return (
                    <div
                      key={p.pid}
                      className={`grid grid-cols-[32px_80px_96px_64px_64px_80px_80px_56px_56px_1fr] gap-0 border-b border-border/50 hover:bg-muted/50 transition-colors ${
                        isSelected ? "bg-muted/80" : ""
                      }`}
                    >
                      <div className="px-1 py-1.5 flex items-center justify-center">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelect(p.pid)}
                          className="h-3.5 w-3.5 rounded border-muted-foreground/50 cursor-pointer"
                        />
                      </div>
                      <div className="px-2 py-1.5 text-right font-mono tabular-nums">
                        {p.pid}
                      </div>
                      <div className="px-2 py-1.5 truncate">{p.username}</div>
                      <div className="px-2 py-1.5 text-right font-mono tabular-nums">
                        <span
                          className={
                            p.cpu_percent > 50
                              ? "text-destructive font-bold"
                              : p.cpu_percent > 10
                                ? "text-yellow-600 dark:text-yellow-400 font-semibold"
                                : ""
                          }
                        >
                          {p.cpu_percent.toFixed(1)}
                        </span>
                      </div>
                      <div className="px-2 py-1.5 text-right font-mono tabular-nums">
                        {(p.memory_percent ?? 0).toFixed(1)}
                      </div>
                      <div className="px-2 py-1.5 text-right font-mono tabular-nums">
                        {formatBytes(p.memory_rss)}
                      </div>
                      <div className="px-2 py-1.5 text-right font-mono tabular-nums">
                        {formatBytes(p.memory_vms)}
                      </div>
                      <div className="px-2 py-1.5 text-center">
                        <span
                          className={
                            p.status === "running"
                              ? "text-green-600 dark:text-green-400"
                              : p.status === "zombie"
                                ? "text-destructive"
                                : "text-muted-foreground"
                          }
                        >
                          {p.status?.[0]?.toUpperCase() ?? "?"}
                        </span>
                      </div>
                      <div className="px-2 py-1.5 text-right font-mono tabular-nums">
                        {p.num_threads}
                      </div>
                      <div className="px-2 py-1.5 truncate font-mono text-muted-foreground" title={p.cmdline || p.name}>
                        {p.cmdline || p.name || "-"}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Kill confirmation */}
      <AlertDialog open={killConfirm} onOpenChange={setKillConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>프로세스 {selected.size}개를 종료할까요?</AlertDialogTitle>
            <AlertDialogDescription>
              선택한 프로세스에 SIGKILL 시그널을 보냅니다. 대상:{" "}
              <strong>{currentRow.hostname}</strong>. 이 작업은 되돌릴 수 없습니다.
              <br />
              <span className="font-mono text-xs mt-1 block">
                PIDs: {Array.from(selected).sort((a, b) => a - b).join(", ")}
              </span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={killing}>취소</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleKill}
              disabled={killing}
              className="bg-destructive text-white hover:bg-destructive/90"
            >
              {killing ? (
                <Loader2 className="h-4 w-4 animate-spin mr-1" />
              ) : (
                <Skull className="h-4 w-4 mr-1" />
              )}
              종료
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
