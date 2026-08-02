// 안내 탭 공용 빌딩 블록 — RAG 개요·파이프라인 등 사용법 화면이 같은 룩앤필을 공유한다.
// 설명 문구는 격식체(~하십시오)로 통일한다.

import type { ReactNode } from "react"
import { ChevronRight, Lightbulb, Lock, RotateCw, type LucideIcon } from "lucide-react"

// 설정 변경 비용 — index: 재인덱싱 필요, query: 질의 시점 실시간 변경.
export type Cost = "index" | "query" | null

export function CostBadge({ cost }: { cost: Cost }) {
  if (cost === "index") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400">
        <Lock className="h-2.5 w-2.5" /> 재인덱싱 필요
      </span>
    )
  }
  if (cost === "query") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
        <RotateCw className="h-2.5 w-2.5" /> 실시간 변경
      </span>
    )
  }
  return null
}

export function Heading({ icon: Icon, children }: { icon: LucideIcon; children: ReactNode }) {
  return (
    <div className="mb-1 flex items-center gap-2">
      <Icon className="h-4 w-4 text-primary" />
      <h2 className="text-base font-semibold">{children}</h2>
    </div>
  )
}

export function Sub({ icon: Icon, color = "text-primary", children }: { icon: LucideIcon; color?: string; children: ReactNode }) {
  return (
    <div className="mb-2 flex items-center gap-2">
      <Icon className={`h-4 w-4 ${color}`} />
      <h3 className="text-sm font-semibold">{children}</h3>
    </div>
  )
}

export function Bullets({ items, icon: Icon = ChevronRight, color = "text-muted-foreground/60" }: { items: ReactNode[]; icon?: LucideIcon; color?: string }) {
  return (
    <ul className="flex flex-col gap-1.5">
      {items.map((it, i) => (
        <li key={i} className="flex gap-2 text-sm text-muted-foreground">
          <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${color}`} />
          <span>{it}</span>
        </li>
      ))}
    </ul>
  )
}

export function Callout({ icon: Icon = Lightbulb, children }: { icon?: LucideIcon; children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-dashed bg-muted/30 p-3 text-sm text-muted-foreground">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
      <span>{children}</span>
    </div>
  )
}

export interface StrategyRow {
  name: string
  desc: string
  cost: Cost
}

export function StrategyTable({ rows, col1 = "전략" }: { rows: StrategyRow[]; col1?: string }) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <table className="w-full text-left text-sm">
        <thead className="bg-muted/50 text-muted-foreground">
          <tr>
            <th className="w-32 p-2">{col1}</th>
            <th className="p-2">설명 · 언제 쓰나</th>
            <th className="w-28 p-2">비용</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name} className="border-t align-top">
              <td className="p-2 font-mono text-foreground">{r.name}</td>
              <td className="p-2 text-muted-foreground">{r.desc}</td>
              <td className="p-2">{r.cost ? <CostBadge cost={r.cost} /> : <span className="text-muted-foreground">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export const TabShell = ({ children }: { children: ReactNode }) => (
  <div className="flex max-w-3xl flex-col gap-6 text-sm leading-relaxed">{children}</div>
)
