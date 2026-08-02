// 관측(Observability) — 질의 통계(건수·성공률·지연·토큰) + 트레이스 목록/상세.
"use client"

import { Fragment, useCallback, useEffect, useState } from "react"
import { Activity, RefreshCw } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Badge } from "@workspace/ui/components/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@workspace/ui/components/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard-header"
import { DataTablePagination, useClientPagination } from "@/components/data-table"
import { formatDateTime } from "@/lib/format"
import { getStats, listTraces } from "@/features/observability/api"
import { LatencyChart } from "@/features/observability/components/latency-chart"
import type { LatencyStat, ObsStats, Trace } from "@/features/observability/data/schema"

const ms = (v: number | null) => (v == null ? "—" : `${v.toFixed(0)}ms`)
const STATUS: Record<string, "secondary" | "destructive"> = { ok: "secondary", error: "destructive" }

// 인기 질의 워드클라우드 — 빈도에 따라 글자 크기를 키우고 색을 순환(의존성 없는 CSS 구현).
function QueryWordCloud({ items }: { items: { query: string; count: number }[] }) {
  if (items.length === 0) return <span className="text-sm text-muted-foreground">데이터 없음</span>
  const counts = items.map((i) => i.count)
  const max = Math.max(...counts)
  const min = Math.min(...counts)
  const fontSize = (c: number) => (max === min ? 18 : 13 + Math.round(((c - min) / (max - min)) * 17)) // 13~30px
  const PALETTE = [
    "text-indigo-600 dark:text-indigo-400",
    "text-sky-600 dark:text-sky-400",
    "text-emerald-600 dark:text-emerald-400",
    "text-amber-600 dark:text-amber-400",
    "text-rose-600 dark:text-rose-400",
    "text-violet-600 dark:text-violet-400",
  ]
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 py-2">
      {items.map((it, i) => (
        <span
          key={it.query}
          title={`${it.query} · ${it.count}회`}
          className={`max-w-full truncate font-semibold leading-tight ${PALETTE[i % PALETTE.length]}`}
          style={{ fontSize: fontSize(it.count) }}
        >
          {it.query}
        </span>
      ))}
    </div>
  )
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
      </CardContent>
    </Card>
  )
}

function lat(l: LatencyStat): string {
  return `p50 ${ms(l.p50)} · p95 ${ms(l.p95)}`
}

export default function ObservabilityPage() {
  const [stats, setStats] = useState<ObsStats | null>(null)
  const [traces, setTraces] = useState<Trace[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [s, t] = await Promise.all([getStats(), listTraces({ limit: 200 })])
      setStats(s)
      setTraces(t)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const { table, pageItems } = useClientPagination(traces)

  return (
    <>
      <DashboardHeader title="운영 (Observability)" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">질의 트레이스 · 지연 · 토큰 · 인기 질의</p>
          <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
            <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
            새로고침
          </Button>
        </div>

        {stats && (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard label="질의 수" value={String(stats.total)} sub={`성공 ${stats.ok} · 실패 ${stats.error}`} />
              <StatCard
                label="성공률"
                value={stats.success_rate == null ? "—" : `${(stats.success_rate * 100).toFixed(1)}%`}
              />
              <StatCard label="총 지연" value={ms(stats.total_ms.p50)} sub={lat(stats.total_ms)} />
              <StatCard
                label="토큰 사용량"
                value={String(stats.prompt_tokens + stats.completion_tokens)}
                sub={`입력 ${stats.prompt_tokens} · 출력 ${stats.completion_tokens}`}
              />
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm font-medium">단계별 지연</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-2">
                  <LatencyChart obs={stats} />
                  <p className="text-xs text-muted-foreground">
                    단계별 p50/p95(ms). 각 단계는 독립 분포라 합산되지 않습니다(검색 합계 retrieval{" "}
                    {lat(stats.retrieval_ms)}).
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm font-medium">인기 질의</CardTitle>
                </CardHeader>
                <CardContent>
                  <QueryWordCloud items={stats.top_queries} />
                </CardContent>
              </Card>
            </div>
          </>
        )}

        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">최근 트레이스</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>시각</TableHead>
                  <TableHead>유형</TableHead>
                  <TableHead>상태</TableHead>
                  <TableHead>질의</TableHead>
                  <TableHead className="text-center">청크</TableHead>
                  <TableHead className="text-right">검색</TableHead>
                  <TableHead className="text-right">생성</TableHead>
                  <TableHead className="text-right">총</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {traces.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="py-8 text-center text-muted-foreground">
                      <Activity className="mx-auto mb-2 size-6 opacity-50" />
                      아직 질의 트레이스가 없습니다. Playground/Chat 에서 질의해 보세요.
                    </TableCell>
                  </TableRow>
                ) : (
                  pageItems.map((t) => (
                    <Fragment key={t.trace_id}>
                      <TableRow
                        className="cursor-pointer"
                        onClick={() => setExpanded(expanded === t.trace_id ? null : t.trace_id)}
                      >
                        <TableCell className="whitespace-nowrap text-sm tabular-nums">
                          {formatDateTime(t.created_at)}
                        </TableCell>
                        <TableCell className="text-sm">{t.kind}</TableCell>
                        <TableCell>
                          <Badge variant={STATUS[t.status] ?? "outline"}>{t.status}</Badge>
                        </TableCell>
                        <TableCell className="max-w-[260px] truncate">{t.query}</TableCell>
                        <TableCell className="text-center">{t.hit_count}</TableCell>
                        <TableCell className="text-right">{ms(t.retrieval_ms)}</TableCell>
                        <TableCell className="text-right">{ms(t.generation_ms)}</TableCell>
                        <TableCell className="text-right font-medium">{ms(t.total_ms)}</TableCell>
                      </TableRow>
                      {expanded === t.trace_id && (
                        <TableRow>
                          <TableCell colSpan={8} className="bg-muted/30 text-xs">
                            <div className="flex flex-col gap-1 p-2">
                              <div className="flex flex-wrap gap-4 text-muted-foreground">
                                <span>retrieval: {ms(t.retrieval_ms)}</span>
                                <span>rerank: {ms(t.rerank_ms)}</span>
                                <span>generation: {ms(t.generation_ms)}</span>
                                <span>tokens: {(t.prompt_tokens ?? 0)}+{(t.completion_tokens ?? 0)}</span>
                                <span>mode: {t.mode}{t.rerank ? " +rerank" : ""}</span>
                                {t.mode !== "lexical" && t.distance_metric && (
                                  <span>거리: {t.distance_metric}</span>
                                )}
                                <span>user: {t.created_by}</span>
                              </div>
                              {t.error && <p className="text-destructive">오류: {t.error}</p>}
                              {t.answer && <p className="whitespace-pre-wrap">{t.answer}</p>}
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </Fragment>
                  ))
                )}
              </TableBody>
            </Table>
            {traces.length > 0 && <DataTablePagination table={table} className="mt-3" />}
          </CardContent>
        </Card>
      </div>
    </>
  )
}
