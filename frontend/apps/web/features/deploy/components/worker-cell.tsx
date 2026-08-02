"use client"

import { AlertTriangle } from "lucide-react"

import { Badge } from "@workspace/ui/components/badge"

import { type ManagedService } from "../api"

/** worker 서비스의 레지스트리 교차참조 표시(alive·상태·현재 잡·처리량). 비-worker 는 '-'. */
export function WorkerCell({ s }: { s: ManagedService }) {
  if (s.kind !== "worker") return null
  if (s.worker_alive == null) {
    return (
      <span className="inline-flex items-center gap-1 text-sm text-amber-600 dark:text-amber-500">
        <AlertTriangle className="size-3.5" /> 미등록
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-sm">
      <span
        className={`size-2 rounded-full ${s.worker_alive ? "bg-green-500" : "bg-gray-400"}`}
        title={s.worker_alive ? "alive" : "끊김"}
      />
      <span>{s.worker_status ?? "?"}</span>
      {s.worker_current_job ? (
        <Badge variant="outline" className="px-1 py-0 text-[10px]" title={`잡 ${s.worker_current_job}`}>
          잡 처리중
        </Badge>
      ) : null}
      <span className="text-muted-foreground">· {s.worker_processed_total ?? 0}건</span>
    </span>
  )
}
