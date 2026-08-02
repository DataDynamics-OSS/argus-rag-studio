"use client"

// 응답 지연 분해 차트 — 임베딩·검색·리랭크·생성 단계의 p50/p95(ms)를 가로 막대로 비교.
// 대시보드와 운영 페이지가 공유한다. (백분위는 단계별 독립 분포라 합산 아님)

import { Bar, BarChart, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from "recharts"
import type { ObsStats } from "@/features/observability/data/schema"

export function LatencyChart({ obs, height = 220 }: { obs: ObsStats; height?: number }) {
  const data = [
    { stage: "임베딩", p50: obs.embedding_ms.p50 ?? 0, p95: obs.embedding_ms.p95 ?? 0 },
    { stage: "검색", p50: obs.search_ms.p50 ?? 0, p95: obs.search_ms.p95 ?? 0 },
    { stage: "리랭크", p50: obs.rerank_ms.p50 ?? 0, p95: obs.rerank_ms.p95 ?? 0 },
    { stage: "생성", p50: obs.generation_ms.p50 ?? 0, p95: obs.generation_ms.p95 ?? 0 },
  ]
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16, top: 4, bottom: 4 }} barGap={2}>
        <XAxis type="number" tickFormatter={(v) => `${Math.round(v as number)}ms`} fontSize={11} stroke="currentColor" className="text-muted-foreground" />
        <YAxis type="category" dataKey="stage" width={36} fontSize={12} stroke="currentColor" className="text-muted-foreground" />
        <RTooltip
          cursor={{ fill: "rgba(99,102,241,0.08)" }}
          formatter={(value) => `${Math.round(Number(value))}ms`}
        />
        <Bar dataKey="p50" name="p50" fill="#6366f1" radius={[0, 4, 4, 0]} />
        <Bar dataKey="p95" name="p95" fill="#c7d2fe" radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}
