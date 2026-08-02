"use client"

import { Check, CircleDashed, Loader2, X } from "lucide-react"

import { cn } from "@workspace/ui/lib/utils"

import { type DeployEvent, type DeployPhase } from "../api"

/** 단계별 진행 상태(이벤트 누적). */
export type PhaseState = {
  status?: "running" | "done" | "error"
  detail?: string
  layers_done?: number
  layers_total?: number
}
export type ProgressState = Partial<Record<DeployPhase, PhaseState>> & { _error?: string }

const PHASES: { key: DeployPhase; label: string; weight: number }[] = [
  { key: "agent", label: "에이전트 확인", weight: 5 },
  { key: "pull", label: "이미지 준비", weight: 70 },
  { key: "run", label: "컨테이너 시작", weight: 10 },
  { key: "settings", label: "설정 주입", weight: 10 },
  { key: "verify", label: "확인", weight: 5 },
]

/** 이벤트를 진행 상태에 누적. */
export function reduceEvent(state: ProgressState, e: DeployEvent): ProgressState {
  if (e.phase === "error") return { ...state, _error: e.detail || "배포 실패" }
  if (e.phase === "done") {
    // 모든 단계 완료 처리
    const next: ProgressState = { ...state }
    for (const p of PHASES) next[p.key] = { ...next[p.key], status: "done" }
    return next
  }
  return {
    ...state,
    [e.phase]: {
      status: e.status,
      detail: e.detail ?? state[e.phase]?.detail,
      layers_done: e.layers_done ?? state[e.phase]?.layers_done,
      layers_total: e.layers_total ?? state[e.phase]?.layers_total,
    },
  }
}

function overallPercent(state: ProgressState): number {
  let pct = 0
  for (const p of PHASES) {
    const s = state[p.key]
    if (!s) continue
    if (s.status === "done") pct += p.weight
    else if (s.status === "running") {
      if (p.key === "pull" && s.layers_total) pct += p.weight * (s.layers_done! / s.layers_total)
      else pct += p.weight * 0.4
    }
  }
  return Math.min(100, Math.round(pct))
}

export function DeployProgress({ state }: { state: ProgressState }) {
  const pct = state._error ? 100 : overallPercent(state)
  return (
    <div className="space-y-3 text-black">
      {/* 전체 progress bar */}
      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full transition-all", state._error ? "bg-red-500" : "bg-primary")}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="text-right text-xs text-muted-foreground">{pct}%</div>

      {/* 단계 체크리스트 */}
      <ul className="space-y-2">
        {PHASES.map((p) => {
          const s = state[p.key]
          const st = state._error && s?.status === "running" ? "error" : s?.status
          const detail =
            p.key === "pull" && s?.status === "running" && s.layers_total
              ? `레이어 ${s.layers_done}/${s.layers_total}`
              : s?.detail
          return (
            <li key={p.key} className="flex items-center gap-2 text-sm">
              {st === "done" ? (
                <Check className="size-4 text-green-600" />
              ) : st === "error" ? (
                <X className="size-4 text-red-600" />
              ) : st === "running" ? (
                <Loader2 className="size-4 animate-spin text-primary" />
              ) : (
                <CircleDashed className="size-4 text-muted-foreground" />
              )}
              <span className={cn(st === "running" && "font-medium")}>{p.label}</span>
              {detail && <span className="text-xs text-muted-foreground">— {detail}</span>}
            </li>
          )
        })}
      </ul>

      {state._error && <p className="text-xs text-red-600">{state._error}</p>}
    </div>
  )
}
