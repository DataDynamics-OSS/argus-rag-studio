"use client"

import { useEffect, useState, type ReactNode } from "react"
import Link from "next/link"
import {
  Library,
  FileText,
  Search,
  CheckCircle2,
  Timer,
  ThumbsUp,
  Inbox,
  Coins,
  type LucideIcon,
} from "lucide-react"
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip as RTooltip } from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@workspace/ui/components/card"
import { DashboardHeader } from "@/components/dashboard-header"
import { listCollections } from "@/features/collections/api"
import { getStats } from "@/features/observability/api"
import { getFeedbackStats } from "@/features/feedback/api"
import { listAllRuns } from "@/features/evaluation/api"
import { getJobsSummary } from "@/features/ingestion/api"
import { LatencyChart } from "@/features/observability/components/latency-chart"
import type { ObsStats } from "@/features/observability/data/schema"
import type { FeedbackStats } from "@/features/feedback/data/schema"
import type { EvalRun } from "@/features/evaluation/data/schema"
import type { JobsSummary } from "@/features/ingestion/data/schema"
import { relativeTime } from "@/lib/format"

const num = (n: number | null | undefined) => (n == null ? "—" : n.toLocaleString())
const ms = (n: number | null | undefined) =>
  n == null ? "—" : n >= 1000 ? `${(n / 1000).toFixed(1)}s` : `${Math.round(n)}ms`

function Metric({
  title,
  icon: Icon,
  value,
  sub,
  href,
  color = "text-foreground",
  iconColor = "text-muted-foreground",
}: {
  title: string
  icon: LucideIcon
  value: ReactNode
  sub?: ReactNode
  href?: string
  color?: string
  iconColor?: string
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <Icon className={`h-4 w-4 ${iconColor}`} />
      </CardHeader>
      <CardContent>
        <div className={`text-2xl font-bold ${color}`}>{value}</div>
        {href ? (
          <Link href={href} className="text-xs text-primary hover:underline">
            {sub ?? "보기 →"}
          </Link>
        ) : (
          <p className="text-xs text-muted-foreground">{sub}</p>
        )}
      </CardContent>
    </Card>
  )
}

// 도넛 툴팁 — 기본 recharts 툴팁은 슬라이스마다 배경(투명/흰색)이 들쭉날쭉해, 커스텀 박스로 통일.
function DonutTooltip({
  active,
  payload,
}: {
  active?: boolean
  payload?: Array<{ name?: string; value?: number }>
}) {
  if (!active || !payload?.length) return null
  const p = payload[0]
  return (
    <div className="rounded-md border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-md">
      <span className="font-medium">{p?.name}</span> {p?.value}건
    </div>
  )
}

// 피드백 만족도 도넛 — 👍 도움됨 / 👎 개선필요 비율.
function FeedbackDonut({ up, down }: { up: number; down: number }) {
  const data = [
    { name: "도움됨", value: up, fill: "#10b981" },
    { name: "개선필요", value: down, fill: "#f43f5e" },
  ]
  const total = up + down
  const pct = total > 0 ? Math.round((up / total) * 100) : null
  return (
    <div className="relative">
      <ResponsiveContainer width="100%" height={160}>
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius={48} outerRadius={70} paddingAngle={2} strokeWidth={0}>
            {data.map((d) => (
              <Cell key={d.name} fill={d.fill} />
            ))}
          </Pie>
          <RTooltip content={<DonutTooltip />} />
        </PieChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-bold">{pct == null ? "—" : `${pct}%`}</span>
        <span className="text-xs text-muted-foreground">만족도</span>
      </div>
    </div>
  )
}

export default function DashboardPage() {
  const [collections, setCollections] = useState(0)
  const [documents, setDocuments] = useState(0)
  const [obs, setObs] = useState<ObsStats | null>(null)
  const [fb, setFb] = useState<FeedbackStats | null>(null)
  const [evalRun, setEvalRun] = useState<EvalRun | null>(null) // 최신 succeeded 평가 Run(점수 표시용)
  const [jobs, setJobs] = useState<JobsSummary | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.allSettled([
      listCollections({ page_size: 200 }),
      getStats(),
      getFeedbackStats(),
      listAllRuns(),
      getJobsSummary(),
    ])
      .then(([c, o, f, r, j]) => {
        if (c.status === "fulfilled") {
          setCollections(c.value.total)
          setDocuments(c.value.items.reduce((s, x) => s + x.document_count, 0))
        }
        if (o.status === "fulfilled") setObs(o.value)
        if (f.status === "fulfilled") setFb(f.value)
        if (r.status === "fulfilled") {
          // listAllRuns 는 최신순 — 첫 succeeded(지표 있음)가 최근 점수.
          setEvalRun(r.value.find((x) => x.status === "succeeded" && x.hit_rate != null) ?? null)
        }
        if (j.status === "fulfilled") setJobs(j.value)
      })
      .finally(() => setLoading(false))
  }, [])

  const v = (x: ReactNode) => (loading ? "—" : x)
  const satisfaction =
    fb && fb.up + fb.down > 0 ? Math.round((fb.up / (fb.up + fb.down)) * 100) : null

  return (
    <>
      <DashboardHeader title="대시보드" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        {/* 데이터 규모 */}
        <p className="text-xs font-medium text-muted-foreground">데이터</p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Metric
            title="지식베이스"
            icon={Library}
            value={v(num(collections))}
            href="/dashboard/collections"
            sub="관리하기 →"
          />
          <Metric
            title="문서"
            icon={FileText}
            value={v(num(documents))}
            iconColor="text-blue-500"
            sub={`컬렉션 ${collections}개 합계`}
          />
          <Metric
            title="누적 질의"
            icon={Search}
            value={v(num(obs?.total))}
            href="/dashboard/observability"
            sub="검색·생성 호출 →"
          />
          <Metric
            title="검색 성공률"
            icon={CheckCircle2}
            value={v(obs?.success_rate == null ? "—" : `${(obs.success_rate * 100).toFixed(1)}%`)}
            iconColor="text-emerald-500"
            color={obs && obs.success_rate != null && obs.success_rate < 0.9 ? "text-amber-600" : "text-emerald-600"}
            sub={obs ? `오류 ${obs.error}건 / 총 ${obs.total}건` : undefined}
          />
        </div>

        {/* 운영·품질 */}
        <p className="mt-2 text-xs font-medium text-muted-foreground">운영 · 품질</p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Metric
            title="응답시간 (p50)"
            icon={Timer}
            value={v(ms(obs?.total_ms.p50))}
            sub={obs ? `p95 ${ms(obs.total_ms.p95)}` : undefined}
          />
          <Metric
            title="피드백 만족도"
            icon={ThumbsUp}
            value={v(satisfaction == null ? "—" : `${satisfaction}%`)}
            iconColor="text-emerald-500"
            sub={fb ? `👍 ${fb.up} · 👎 ${fb.down}` : undefined}
          />
          <Metric
            title="미처리 피드백"
            icon={Inbox}
            value={v(num(fb?.new))}
            href="/dashboard/feedback"
            sub="골든셋 승격 대기 →"
            color={fb && fb.new > 0 ? "text-amber-600" : "text-foreground"}
          />
          <Metric
            title="토큰 사용량"
            icon={Coins}
            value={v(num((obs?.prompt_tokens ?? 0) + (obs?.completion_tokens ?? 0)))}
            sub={obs ? `프롬프트 ${num(obs.prompt_tokens)} · 완성 ${num(obs.completion_tokens)}` : undefined}
          />
        </div>

        {/* 지연 분해 차트 + 최근 평가 점수 */}
        <div className="mt-2 grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">응답 지연 분해 (검색 vs 생성)</CardTitle>
              <Link href="/dashboard/observability" className="text-xs text-primary hover:underline">
                관측성 →
              </Link>
            </CardHeader>
            <CardContent>
              {obs && (obs.retrieval_ms.p50 != null || obs.generation_ms.p50 != null) ? (
                <LatencyChart obs={obs} />
              ) : (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  아직 질의 기록이 없습니다. 플레이그라운드·채팅에서 검색을 실행하면 집계됩니다.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">최근 평가 점수</CardTitle>
              <Link href="/dashboard/evaluation" className="text-xs text-primary hover:underline">
                평가 →
              </Link>
            </CardHeader>
            <CardContent>
              {evalRun ? (
                <>
                  <div className="flex gap-6">
                    <div>
                      <div className="text-2xl font-bold">{evalRun.hit_rate?.toFixed(3) ?? "—"}</div>
                      <p className="text-xs text-muted-foreground">Hit Rate</p>
                    </div>
                    <div>
                      <div className="text-2xl font-bold">{evalRun.mrr?.toFixed(3) ?? "—"}</div>
                      <p className="text-xs text-muted-foreground">MRR</p>
                    </div>
                  </div>
                  <p className="mt-2 truncate text-xs text-muted-foreground">
                    최근 실행 · {relativeTime(evalRun.finished_at ?? evalRun.created_at)}
                  </p>
                </>
              ) : (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  아직 평가 실행이 없습니다. 평가에서 골든셋을 실행해 보세요.
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* 인제스천 잡 상태 + 피드백 도넛 */}
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">인제스천 잡 상태</CardTitle>
              <Link href="/dashboard/jobs" className="text-xs text-primary hover:underline">
                잡 모니터링 →
              </Link>
            </CardHeader>
            <CardContent>
              {jobs ? (
                <>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                    {[
                      { label: "대기", value: jobs.queued, color: "text-foreground" },
                      { label: "진행 중", value: jobs.running, color: jobs.running > 0 ? "text-blue-600" : "text-foreground" },
                      { label: "완료 (24h)", value: jobs.succeeded_24h, color: "text-emerald-600" },
                      { label: "실패 (24h)", value: jobs.failed_24h, color: jobs.failed_24h > 0 ? "text-rose-600" : "text-foreground" },
                    ].map((s) => (
                      <div key={s.label} className="rounded-lg border p-3">
                        <div className={`text-2xl font-bold ${s.color}`}>{num(s.value)}</div>
                        <p className="text-xs text-muted-foreground">{s.label}</p>
                      </div>
                    ))}
                  </div>
                  {Object.keys(jobs.running_by_stage).length > 0 && (
                    <p className="mt-2 text-xs text-muted-foreground">
                      진행 단계 ·{" "}
                      {Object.entries(jobs.running_by_stage)
                        .map(([stage, n]) => `${stage} ${n}`)
                        .join(" · ")}
                    </p>
                  )}
                </>
              ) : (
                <p className="py-8 text-center text-sm text-muted-foreground">잡 정보를 불러올 수 없습니다.</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">피드백 만족도</CardTitle>
              <Link href="/dashboard/feedback" className="text-xs text-primary hover:underline">
                피드백 →
              </Link>
            </CardHeader>
            <CardContent>
              {fb && fb.up + fb.down > 0 ? (
                <>
                  <FeedbackDonut up={fb.up} down={fb.down} />
                  <div className="mt-1 flex justify-center gap-4 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-1">
                      <span className="size-2 rounded-full bg-emerald-500" /> 도움됨 {fb.up}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <span className="size-2 rounded-full bg-rose-500" /> 개선필요 {fb.down}
                    </span>
                  </div>
                </>
              ) : (
                <p className="py-8 text-center text-sm text-muted-foreground">아직 피드백이 없습니다.</p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  )
}
