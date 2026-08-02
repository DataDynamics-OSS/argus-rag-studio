"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Activity, Loader2, X } from "lucide-react"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@workspace/ui/components/dialog"
import { fetchTop } from "../api"
import { type Server as ServerType } from "../data/schema"

/* eslint-disable @typescript-eslint/no-explicit-any */

type ServersTopDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  currentRow: ServerType
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0B"
  const k = 1024
  const sizes = ["B", "KB", "MB", "GB", "TB"]
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)}${sizes[i]}`
}

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  if (days > 0) return `${days} days, ${hours}:${String(mins).padStart(2, "0")}`
  return `${hours}:${String(mins).padStart(2, "0")}`
}

function Bar({ percent, width = 20, color = "green" }: { percent: number; width?: number; color?: string }) {
  const filled = Math.round((percent / 100) * width)
  const empty = width - filled
  const colorClass = color === "green" ? "text-green-400" : color === "blue" ? "text-blue-400" : color === "red" ? "text-red-400" : "text-yellow-400"
  return (
    <span>
      [<span className={colorClass}>{"#".repeat(filled)}</span>
      <span className="text-zinc-600">{"-".repeat(empty)}</span>]
    </span>
  )
}

export function ServersTopDialog({
  open,
  onOpenChange,
  currentRow,
}: ServersTopDialogProps) {
  const [data, setData] = useState<Record<string, any> | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadTop = useCallback(async () => {
    try {
      const result = await fetchTop(currentRow.hostname)
      setData(result)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "top 데이터를 불러오지 못했습니다")
    } finally {
      setLoading(false)
    }
  }, [currentRow.hostname])

  useEffect(() => {
    if (open) {
      setLoading(true)
      setData(null)
      loadTop()
      intervalRef.current = setInterval(loadTop, 2000)
    } else {
      setData(null)
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
  }, [open, loadTop])

  const cpu = data?.cpu as any
  const cores = (data?.cores ?? []) as any[]
  const memory = data?.memory as any
  const processes = (data?.processes ?? []) as any[]

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Dark scrollbar styles for terminal look */}
      <style>{`
        .top-scrollbar::-webkit-scrollbar { width: 8px; height: 8px; }
        .top-scrollbar::-webkit-scrollbar-track { background: #09090b; }
        .top-scrollbar::-webkit-scrollbar-thumb { background: #3f3f46; border-radius: 4px; }
        .top-scrollbar::-webkit-scrollbar-thumb:hover { background: #52525b; }
        .top-scrollbar::-webkit-scrollbar-corner { background: #09090b; }
        .top-scrollbar { scrollbar-color: #3f3f46 #09090b; }
      `}</style>
      <DialogContent
        className="max-w-5xl p-0 overflow-hidden flex flex-col"
        style={{ maxHeight: "85vh" }}
        showCloseButton={false}
      >
        <div className="bg-zinc-950 text-zinc-100 font-mono text-xs leading-relaxed flex flex-col min-h-0 h-full">
          {/* Header */}
          <div className="flex items-center justify-between px-4 pt-3 pb-1 shrink-0">
            <DialogHeader className="p-0 space-y-0">
              <DialogTitle className="text-sm font-bold text-green-400 flex items-center gap-2">
                <Activity className="h-4 w-4" />
                top - {currentRow.hostname}
              </DialogTitle>
              <DialogDescription className="text-zinc-500 text-xs">
                {currentRow.ipAddress} · 2초마다 갱신
              </DialogDescription>
            </DialogHeader>
            <DialogClose className="text-zinc-400 hover:text-white transition-colors p-1 rounded hover:bg-zinc-800">
              <X className="h-4 w-4" />
              <span className="sr-only">닫기</span>
            </DialogClose>
          </div>

          {loading && !data && (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />
              <span className="ml-2 text-zinc-500">불러오는 중...</span>
            </div>
          )}

          {error && !data && (
            <div className="px-4 py-8 text-red-400 text-center">{error}</div>
          )}

          {data && (
            <div className="px-4 pb-3 space-y-1 flex flex-col min-h-0 flex-1">
              {/* Uptime & Tasks */}
              <div className="text-zinc-300">
                <span className="text-white">up {formatUptime(data.uptime_seconds as number)}</span>
                {cpu && (
                  <span className="ml-4">
                    load average: <span className="text-yellow-300">{cpu.load_avg_1m?.toFixed(2)}</span>,{" "}
                    <span className="text-yellow-300">{cpu.load_avg_5m?.toFixed(2)}</span>,{" "}
                    <span className="text-yellow-300">{cpu.load_avg_15m?.toFixed(2)}</span>
                  </span>
                )}
              </div>
              <div className="text-zinc-300">
                Tasks: <span className="text-white">{data.tasks_total}</span> total,{" "}
                <span className="text-green-400">{data.tasks_running}</span> running,{" "}
                <span className="text-zinc-400">{data.tasks_sleeping}</span> sleeping,{" "}
                <span className="text-yellow-400">{data.tasks_stopped}</span> stopped,{" "}
                <span className="text-red-400">{data.tasks_zombie}</span> zombie
              </div>

              {/* CPU */}
              {cpu && (
                <div className="text-zinc-300">
                  %Cpu(s): <span className="text-green-400">{cpu.user_percent?.toFixed(1)} us</span>,{" "}
                  <span className="text-red-400">{cpu.system_percent?.toFixed(1)} sy</span>,{" "}
                  <span className="text-zinc-400">{cpu.nice_percent?.toFixed(1)} ni</span>,{" "}
                  <span className="text-blue-400">{cpu.idle_percent?.toFixed(1)} id</span>,{" "}
                  <span className="text-yellow-400">{cpu.iowait_percent?.toFixed(1)} wa</span>,{" "}
                  <span className="text-zinc-500">{cpu.irq_percent?.toFixed(1)} hi</span>,{" "}
                  <span className="text-zinc-500">{cpu.softirq_percent?.toFixed(1)} si</span>,{" "}
                  <span className="text-zinc-500">{cpu.steal_percent?.toFixed(1)} st</span>
                </div>
              )}

              {/* Core bars */}
              {cores.length > 0 && (
                <div className="grid gap-0" style={{ gridTemplateColumns: `repeat(${Math.min(cores.length, 4)}, 1fr)` }}>
                  {cores.map((core: any) => (
                    <div key={core.core_id} className="text-zinc-400 whitespace-nowrap overflow-hidden">
                      <span className="text-zinc-500">{String(core.core_id).padStart(2)}</span>{" "}
                      <Bar percent={core.total_percent} width={12} color={core.total_percent > 80 ? "red" : core.total_percent > 50 ? "yellow" : "green"} />{" "}
                      <span className="text-white">{core.total_percent.toFixed(0)}%</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Memory & Swap */}
              {memory && (
                <>
                  <div className="text-zinc-300">
                    Mem: {formatBytes(memory.total_bytes)} total,{" "}
                    <span className="text-green-400">{formatBytes(memory.used_bytes)} used</span>,{" "}
                    <span className="text-blue-400">{formatBytes(memory.free_bytes)} free</span>,{" "}
                    <span className="text-yellow-300">{formatBytes(memory.available_bytes)} avail</span>{" "}
                    <Bar percent={memory.usage_percent} width={20} color={memory.usage_percent > 80 ? "red" : memory.usage_percent > 60 ? "yellow" : "green"} />{" "}
                    <span className="text-white">{memory.usage_percent.toFixed(1)}%</span>
                  </div>
                  <div className="text-zinc-300">
                    Swap: {formatBytes(memory.swap_total_bytes)} total,{" "}
                    <span className="text-green-400">{formatBytes(memory.swap_used_bytes)} used</span>,{" "}
                    <span className="text-blue-400">{formatBytes(memory.swap_free_bytes)} free</span>{" "}
                    <Bar percent={memory.swap_usage_percent} width={20} color={memory.swap_usage_percent > 50 ? "red" : "green"} />{" "}
                    <span className="text-white">{memory.swap_usage_percent.toFixed(1)}%</span>
                  </div>
                </>
              )}

              {/* Process table */}
              <div className="border-t border-zinc-700 mt-1 pt-1 flex-1 min-h-0 flex flex-col">
                <div className="overflow-auto flex-1 min-h-0 pb-1 top-scrollbar">
                  <table className="w-full text-left">
                    <thead>
                      <tr className="text-zinc-400 bg-zinc-900 sticky top-0">
                        <th className="px-2 py-0.5 text-right w-16">PID</th>
                        <th className="px-2 py-0.5 w-20">USER</th>
                        <th className="px-2 py-0.5 text-right w-14">CPU%</th>
                        <th className="px-2 py-0.5 text-right w-14">MEM%</th>
                        <th className="px-2 py-0.5 text-right w-16">RSS</th>
                        <th className="px-2 py-0.5 text-right w-16">VIRT</th>
                        <th className="px-2 py-0.5 w-10 text-center">S</th>
                        <th className="px-2 py-0.5 text-right w-10">THR</th>
                        <th className="px-2 py-0.5">COMMAND</th>
                      </tr>
                    </thead>
                    <tbody>
                      {processes.map((p: any) => {
                        const cpuHigh = p.cpu_percent > 50
                        const cpuMed = p.cpu_percent > 10
                        return (
                          <tr
                            key={p.pid}
                            className={`hover:bg-zinc-800/50 ${cpuHigh ? "text-red-400" : cpuMed ? "text-yellow-300" : "text-zinc-300"}`}
                          >
                            <td className="px-2 py-0 text-right text-cyan-400">{p.pid}</td>
                            <td className="px-2 py-0 truncate max-w-20">{p.username}</td>
                            <td className="px-2 py-0 text-right font-bold">{p.cpu_percent.toFixed(1)}</td>
                            <td className="px-2 py-0 text-right">{p.memory_percent.toFixed(1)}</td>
                            <td className="px-2 py-0 text-right">{formatBytes(p.rss_bytes)}</td>
                            <td className="px-2 py-0 text-right">{formatBytes(p.vms_bytes)}</td>
                            <td className="px-2 py-0 text-center">
                              <span className={p.status === "running" ? "text-green-400" : p.status === "zombie" ? "text-red-400" : "text-zinc-500"}>
                                {p.status?.[0]?.toUpperCase() ?? "?"}
                              </span>
                            </td>
                            <td className="px-2 py-0 text-right">{p.num_threads}</td>
                            <td className="px-2 py-0 truncate max-w-xs">{p.cmdline || p.name || "-"}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
