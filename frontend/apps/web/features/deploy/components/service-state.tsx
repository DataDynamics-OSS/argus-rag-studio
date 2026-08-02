"use client"

import { Badge } from "@workspace/ui/components/badge"

import { type ManagedService } from "../api"

// 시맨틱 상태색 규약 — 초록=정상 가동, 호박=주의(중지·부분 가동·기동 중·unhealthy), 빨강=실패.
function stateVariant(s: ManagedService): "success" | "warning" | "destructive" | "outline" {
  if (s.state === "failed" || s.state === "error") return "destructive"
  if (s.state === "running") {
    return s.health && s.health !== "healthy" ? "warning" : "success"
  }
  if (s.state === "stopped" || s.state === "partial" || s.state === "pending") return "warning"
  return "outline" // unknown — 중립
}

/** 상태 배지(시맨틱 색) + 에러(title) + 재시작 횟수 + health. 그리드 공용.

    종료코드는 배지에 표기하지 않는다(stopped (0) 노이즈) — 오류 상세는 message/title 로. */
export function ServiceState({ s }: { s: ManagedService }) {
  const label =
    `${s.state ?? "?"}` +
    (s.health && s.health !== "healthy" ? ` · ${s.health}` : "")
  return (
    <span className="inline-flex items-center gap-1">
      <Badge
        variant={stateVariant(s)}
        title={s.message ?? undefined}
        className={s.message ? "uppercase cursor-help" : "uppercase"}
      >
        {label}
      </Badge>
      {s.restart_count != null && s.restart_count > 0 ? (
        <span className="text-[10px] text-amber-600" title={`재시작 ${s.restart_count}회`}>
          ↻{s.restart_count}
        </span>
      ) : null}
    </span>
  )
}

/** CPU%/MEM% (docker stats). 미수집/중지면 '-'. */
export function ResourceCell({ s }: { s: ManagedService }) {
  if (s.cpu_percent == null && s.mem_percent == null) {
    return <span className="text-muted-foreground">-</span>
  }
  return (
    <span className="text-xs whitespace-nowrap">
      {s.cpu_percent != null ? `${s.cpu_percent.toFixed(0)}%` : "-"}
      <span className="text-muted-foreground"> / </span>
      {s.mem_percent != null ? `${s.mem_percent.toFixed(0)}%` : "-"}
    </span>
  )
}
