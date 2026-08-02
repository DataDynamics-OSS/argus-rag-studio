// 잡 모니터링 — 인제스천 / 평가 / 스윕 / 파인튜닝 잡 상태를 탭별 실시간(폴링)으로 본다.
// 탭은 활성일 때만 마운트되어 폴링하므로(비활성 탭은 자동 중지), 보고 있는 잡만 갱신된다.
"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { getCoreRowModel, useReactTable } from "@tanstack/react-table"
import { Cpu, Loader2, RefreshCw } from "lucide-react"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import { Card, CardContent, CardHeader, CardTitle } from "@workspace/ui/components/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
import { TabsContent, TabsList, TabsTrigger } from "@workspace/ui/components/tabs"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@workspace/ui/components/tooltip"
import { toast } from "sonner"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { DashboardHeader } from "@/components/dashboard-header"
import { DataTablePagination, useClientPagination } from "@/components/data-table"
import { formatDateTime } from "@/lib/format"
import { useAuth } from "@/features/auth"
import { listCollections } from "@/features/collections/api"
import type { Collection } from "@/features/collections/data/schema"
import { listAllRuns, listAllSweeps } from "@/features/evaluation/api"
import type { EvalRun, EvalSweep } from "@/features/evaluation/data/schema"
import { listJobs as listFtJobs } from "@/features/finetune/api"
import type { FtJob } from "@/features/finetune/data/schema"
import { getExtServerStats, getJobsSummary, getRegisteredExtServers, getWorkers, listJobs, reindexDocument } from "@/features/ingestion/api"
import type { ExtServerStat, JobListItem, JobsSummary, WorkerInfo } from "@/features/ingestion/data/schema"
import { DeviceBadge } from "@/features/deploy/components/device-badge"
import { UrlTabs } from "@/components/url-tabs"

const REFRESH_MS = 3000
const POLL_MS = 5000

const STAGE_LABEL: Record<string, string> = { parse: "파싱", chunk: "청킹", embed: "임베딩", index: "색인" }
const STATUS_LABEL: Record<string, string> = {
  queued: "대기",
  running: "진행중",
  indexing: "색인중",
  judging: "채점중",
  succeeded: "완료",
  failed: "실패",
  canceled: "취소",
}

function statusVariant(s: string): "default" | "secondary" | "outline" | "destructive" {
  if (s === "succeeded") return "default"
  if (s === "failed") return "destructive"
  if (s === "running" || s === "indexing" || s === "judging") return "secondary"
  return "outline" // queued | canceled
}

function StatusBadge({ status }: { status: string }) {
  return <Badge variant={statusVariant(status)}>{STATUS_LABEL[status] ?? status}</Badge>
}

/** 시작~종료(또는 현재)까지의 소요. */
function duration(startedAt: string | null, finishedAt: string | null, now: number): string {
  if (!startedAt) return "—"
  const start = new Date(startedAt).getTime()
  const end = finishedAt ? new Date(finishedAt).getTime() : now
  const sec = Math.max(0, Math.round((end - start) / 1000))
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  return m < 60 ? `${m}m ${sec % 60}s` : `${Math.floor(m / 60)}h ${m % 60}m`
}

/** 활성 탭에서만 마운트되어 주기 폴링하는 목록 훅(비활성 시 cleanup 으로 중지). */
function usePolledList<T>(fetcher: () => Promise<T[]>, intervalMs = POLL_MS) {
  const [data, setData] = useState<T[]>([])
  const [loading, setLoading] = useState(true)
  const fRef = useRef(fetcher)
  fRef.current = fetcher
  const refresh = useCallback(async () => {
    try {
      setData(await fRef.current())
    } catch {
      /* 폴링 중 일시 오류는 조용히 */
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => {
    void refresh()
    const t = setInterval(() => void refresh(), intervalMs)
    return () => clearInterval(t)
  }, [refresh, intervalMs])
  return { data, loading, refresh }
}

function ProgressBar({ pct, failed }: { pct: number; failed?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full rounded-full ${failed ? "bg-destructive" : "bg-primary"}`}
          style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
        />
      </div>
      <span className="w-9 text-right text-[11px] tabular-nums text-muted-foreground">{Math.round(pct)}%</span>
    </div>
  )
}

function EmptyRow({ cols, loading, text }: { cols: number; loading: boolean; text: string }) {
  return (
    <TableRow>
      <TableCell colSpan={cols} className="h-24 text-center text-sm text-muted-foreground">
        {loading ? <Loader2 className="mx-auto h-5 w-5 animate-spin" /> : text}
      </TableCell>
    </TableRow>
  )
}

// ── 인제스천 탭 ──────────────────────────────────────────────────────────────
function IngestionTab() {
  const { user } = useAuth()
  const canManage = !!(user?.is_admin || user?.is_superuser)

  const [summary, setSummary] = useState<JobsSummary | null>(null)
  const [jobs, setJobs] = useState<JobListItem[]>([])
  const [total, setTotal] = useState(0)
  const [status, setStatus] = useState("all")
  const [collectionId, setCollectionId] = useState("all")
  const [collections, setCollections] = useState<Collection[]>([])
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [loading, setLoading] = useState(true)
  const [now, setNow] = useState(() => Date.now())
  const [reindexing, setReindexing] = useState<string | null>(null)
  const [confirmJob, setConfirmJob] = useState<JobListItem | null>(null)

  const filterRef = useRef({ status, collectionId, page, pageSize })
  filterRef.current = { status, collectionId, page, pageSize }
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  // 페이지 이동 전용 TanStack 인스턴스(컬렉션 목록과 동일한 DataTablePagination 사용).
  const pager = useReactTable({
    data: jobs,
    columns: [],
    pageCount: totalPages,
    state: { pagination: { pageIndex: page - 1, pageSize } },
    manualPagination: true,
    getCoreRowModel: getCoreRowModel(),
    onPaginationChange: (updater) => {
      const next =
        typeof updater === "function" ? updater({ pageIndex: page - 1, pageSize }) : updater
      if (next.pageSize !== pageSize) {
        setPageSize(next.pageSize)
        setPage(1)
      } else {
        setPage(next.pageIndex + 1)
      }
    },
  })

  useEffect(() => {
    listCollections({ page_size: 200 }).then((r) => setCollections(r.items)).catch(() => {})
  }, [])

  const loadSummary = useCallback(async () => setSummary(await getJobsSummary()), [])
  const loadJobs = useCallback(async () => {
    const f = filterRef.current
    const j = await listJobs({
      status: f.status === "all" ? undefined : f.status,
      collection_id: f.collectionId === "all" ? undefined : Number(f.collectionId),
      page: f.page,
      page_size: f.pageSize,
    })
    setJobs(j.items)
    setTotal(j.total)
    setNow(Date.now())
  }, [])
  const refresh = useCallback(async () => {
    try {
      await Promise.all([loadSummary(), loadJobs()])
    } catch (e) {
      if (loading) toast.error(e instanceof Error ? e.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [loadSummary, loadJobs, loading])

  useEffect(() => {
    setLoading(true)
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, collectionId, page, pageSize])

  useEffect(() => {
    const t = setInterval(() => {
      void loadSummary()
      if (filterRef.current.page === 1) void loadJobs()
    }, REFRESH_MS)
    return () => clearInterval(t)
  }, [loadSummary, loadJobs])

  const doReindex = async () => {
    const job = confirmJob
    if (!job?.document_uuid) return
    setReindexing(job.document_uuid)
    try {
      await reindexDocument(job.document_uuid)
      toast.success("재처리를 시작했습니다.")
      setConfirmJob(null)
      void refresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "재처리 실패")
    } finally {
      setReindexing(null)
    }
  }

  const cards = [
    { label: "대기(queued)", value: summary?.queued ?? 0, accent: "text-muted-foreground" },
    { label: "진행중(running)", value: summary?.running ?? 0, accent: "text-sky-600" },
    { label: "24시간 완료", value: summary?.succeeded_24h ?? 0, accent: "text-emerald-600" },
    { label: "24시간 실패", value: summary?.failed_24h ?? 0, accent: "text-destructive" },
  ]

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((c) => (
          <Card key={c.label}>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">{c.label}</CardTitle>
            </CardHeader>
            <CardContent>
              <span className={`text-2xl font-bold tabular-nums ${c.accent}`}>{c.value.toLocaleString()}</span>
            </CardContent>
          </Card>
        ))}
      </div>

      {summary && summary.running > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          진행중 단계:
          {Object.entries(summary.running_by_stage).map(([st, n]) => (
            <Badge key={st} variant="secondary" className="px-1.5 py-0">
              {STAGE_LABEL[st] ?? st} {n}
            </Badge>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Select value={status} onValueChange={(v) => { setStatus(v); setPage(1) }}>
          <SelectTrigger className="h-9 w-36"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">전체 상태</SelectItem>
            <SelectItem value="queued">대기</SelectItem>
            <SelectItem value="running">진행중</SelectItem>
            <SelectItem value="succeeded">완료</SelectItem>
            <SelectItem value="failed">실패</SelectItem>
          </SelectContent>
        </Select>
        <Select value={collectionId} onValueChange={(v) => { setCollectionId(v); setPage(1) }}>
          <SelectTrigger className="h-9 w-56"><SelectValue placeholder="전체 컬렉션" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">전체 컬렉션</SelectItem>
            {collections.map((c) => (
              <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground tabular-nums">총 {total.toLocaleString()} 잡</span>
        <Button variant="outline" size="sm" className="ml-auto" onClick={() => void refresh()}>
          <RefreshCw className="mr-1 h-4 w-4" /> 새로고침
        </Button>
      </div>

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-20">상태</TableHead>
              <TableHead>문서</TableHead>
              <TableHead className="w-40">컬렉션</TableHead>
              <TableHead className="w-16 text-center">단계</TableHead>
              <TableHead className="w-40">진행</TableHead>
              <TableHead className="w-16 text-right">청크</TableHead>
              <TableHead className="w-20 text-right">소요</TableHead>
              <TableHead className="w-16" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading || jobs.length === 0 ? (
              <EmptyRow cols={8} loading={loading} text="표시할 잡이 없습니다." />
            ) : (
              jobs.map((job) => (
                <TableRow key={job.job_id}>
                  <TableCell><StatusBadge status={job.status} /></TableCell>
                  <TableCell className="max-w-0">
                    <span className="block truncate" title={job.document_name ?? undefined}>
                      {job.document_name ?? `#${job.document_id}`}
                    </span>
                    {job.status === "failed" && job.error && (
                      <span className="block truncate text-xs text-destructive" title={job.error}>{job.error}</span>
                    )}
                  </TableCell>
                  <TableCell className="truncate text-sm" title={job.collection_name ?? undefined}>
                    {job.collection_name ?? `#${job.collection_id}`}
                  </TableCell>
                  <TableCell className="text-center text-sm">
                    {job.stage ? STAGE_LABEL[job.stage] ?? job.stage : "—"}
                  </TableCell>
                  <TableCell>
                    <ProgressBar pct={job.status === "succeeded" ? 100 : job.progress} failed={job.status === "failed"} />
                  </TableCell>
                  <TableCell className="text-right text-sm tabular-nums">{job.chunk_count}</TableCell>
                  <TableCell className="text-right text-sm tabular-nums">
                    {duration(job.started_at, job.finished_at, now)}
                  </TableCell>
                  <TableCell className="text-right">
                    {canManage && job.status === "failed" && job.document_uuid && (
                      <TooltipProvider delayDuration={150}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button variant="ghost" size="sm" className="h-7"
                              disabled={reindexing === job.document_uuid}
                              onClick={() => setConfirmJob(job)}>
                              {reindexing === job.document_uuid
                                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                : <RefreshCw className="h-3.5 w-3.5" />}
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>재처리 — 기존 청크를 지우고 파싱·청킹·임베딩·색인을 다시 수행</TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-xs text-muted-foreground">
          {page > 1
            ? "다른 페이지를 보는 동안 목록 자동 갱신이 멈춥니다(요약은 계속 갱신)."
            : `${REFRESH_MS / 1000}초마다 자동 갱신`}
        </span>
        <DataTablePagination table={pager} />
      </div>

      <ConfirmDialog
        open={confirmJob !== null}
        onOpenChange={(o) => { if (!o) setConfirmJob(null) }}
        title="문서 재처리"
        desc={confirmJob
          ? `'${confirmJob.document_name ?? `#${confirmJob.document_id}`}' 을(를) 다시 처리할까요? 기존 청크를 삭제하고 파싱·청킹·임베딩·색인을 처음부터 다시 수행합니다(임베딩 재계산).`
          : ""}
        confirmText="재처리"
        isLoading={reindexing !== null}
        handleConfirm={() => void doReindex()}
      />
    </div>
  )
}

// ── 평가 탭 ──────────────────────────────────────────────────────────────────
function EvalTab() {
  const { data: runs, loading, refresh } = usePolledList<EvalRun>(listAllRuns)
  const now = Date.now()
  const { table, pageItems } = useClientPagination(runs, 50)
  return (
    <TabFrame onRefresh={refresh} count={runs.length} unit="런" pagination={runs.length > 0 && <DataTablePagination table={table} />}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-20">상태</TableHead>
            <TableHead className="w-24">컬렉션</TableHead>
            <TableHead className="w-24">모드</TableHead>
            <TableHead className="w-28">진행</TableHead>
            <TableHead className="w-20 text-right">Hit</TableHead>
            <TableHead className="w-20 text-right">MRR</TableHead>
            <TableHead className="w-20 text-right">소요</TableHead>
            <TableHead className="w-40">생성</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading || runs.length === 0 ? (
            <EmptyRow cols={8} loading={loading} text="평가 런이 없습니다." />
          ) : (
            pageItems.map((r) => (
              <TableRow key={r.run_id}>
                <TableCell><StatusBadge status={r.status} /></TableCell>
                <TableCell className="text-sm">#{r.collection_id}</TableCell>
                <TableCell className="text-sm">{r.mode}{r.rerank ? " +rerank" : ""}</TableCell>
                <TableCell className="text-sm tabular-nums">
                  {r.completed_items}/{r.total_items}
                </TableCell>
                <TableCell className="text-right text-sm tabular-nums">{r.hit_rate != null ? r.hit_rate.toFixed(3) : "—"}</TableCell>
                <TableCell className="text-right text-sm tabular-nums">{r.mrr != null ? r.mrr.toFixed(3) : "—"}</TableCell>
                <TableCell className="text-right text-sm tabular-nums">{duration(r.started_at, r.finished_at, now)}</TableCell>
                <TableCell className="text-sm tabular-nums">{formatDateTime(r.created_at)}</TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </TabFrame>
  )
}

// ── 스윕 탭 ──────────────────────────────────────────────────────────────────
function SweepTab() {
  const { data: sweeps, loading, refresh } = usePolledList<EvalSweep>(listAllSweeps)
  const now = Date.now()
  const { table, pageItems } = useClientPagination(sweeps, 50)
  return (
    <TabFrame onRefresh={refresh} count={sweeps.length} unit="스윕" pagination={sweeps.length > 0 && <DataTablePagination table={table} />}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-20">상태</TableHead>
            <TableHead>이름</TableHead>
            <TableHead className="w-28">진행(런)</TableHead>
            <TableHead className="w-28">주요 지표</TableHead>
            <TableHead className="w-20 text-right">소요</TableHead>
            <TableHead className="w-40">생성</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading || sweeps.length === 0 ? (
            <EmptyRow cols={6} loading={loading} text="스윕이 없습니다." />
          ) : (
            pageItems.map((s) => (
              <TableRow key={s.sweep_id}>
                <TableCell><StatusBadge status={s.status} /></TableCell>
                <TableCell className="max-w-0">
                  <span className="block truncate" title={s.name}>{s.name}</span>
                  {s.status === "failed" && s.error && (
                    <span className="block truncate text-xs text-destructive" title={s.error}>{s.error}</span>
                  )}
                </TableCell>
                <TableCell className="text-sm tabular-nums">{s.completed_runs}/{s.total_runs}</TableCell>
                <TableCell className="text-sm">{s.primary_metric}</TableCell>
                <TableCell className="text-right text-sm tabular-nums">{duration(s.started_at, s.finished_at, now)}</TableCell>
                <TableCell className="text-sm tabular-nums">{formatDateTime(s.created_at)}</TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </TabFrame>
  )
}

// ── 파인튜닝 탭 ───────────────────────────────────────────────────────────────
function FinetuneTab() {
  const { data: jobs, loading, refresh } = usePolledList<FtJob>(() => listFtJobs())
  const now = Date.now()
  const { table, pageItems } = useClientPagination(jobs, 50)
  return (
    <TabFrame onRefresh={refresh} count={jobs.length} unit="잡" pagination={jobs.length > 0 && <DataTablePagination table={table} />}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-20">상태</TableHead>
            <TableHead>데이터셋</TableHead>
            <TableHead className="w-24">작업</TableHead>
            <TableHead>베이스 모델</TableHead>
            <TableHead className="w-16 text-center">단계</TableHead>
            <TableHead className="w-36">진행</TableHead>
            <TableHead className="w-40">생성</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading || jobs.length === 0 ? (
            <EmptyRow cols={7} loading={loading} text="파인튜닝 잡이 없습니다." />
          ) : (
            pageItems.map((j) => (
              <TableRow key={j.job_id}>
                <TableCell><StatusBadge status={j.status} /></TableCell>
                <TableCell className="truncate text-sm" title={j.dataset_name ?? undefined}>{j.dataset_name ?? `#${j.dataset_id}`}</TableCell>
                <TableCell className="text-sm">{j.task}</TableCell>
                <TableCell className="truncate font-mono text-sm" title={j.base_model ?? undefined}>{j.base_model ?? "—"}</TableCell>
                <TableCell className="text-center text-sm">{j.stage ?? "—"}</TableCell>
                <TableCell><ProgressBar pct={j.status === "succeeded" ? 100 : j.progress} failed={j.status === "failed"} /></TableCell>
                <TableCell className="text-sm tabular-nums">{formatDateTime(j.created_at)}</TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </TabFrame>
  )
}

// 평가/스윕/파인튜닝 탭 공통 프레임(새로고침 + 카운트 + 테이블 보더).
function TabFrame({
  children, onRefresh, count, unit, pagination,
}: {
  children: React.ReactNode
  onRefresh: () => void
  count: number
  unit: string
  pagination?: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground tabular-nums">{count.toLocaleString()} {unit}</span>
        <Button variant="outline" size="sm" className="ml-auto" onClick={onRefresh}>
          <RefreshCw className="mr-1 h-4 w-4" /> 새로고침
        </Button>
      </div>
      <div className="rounded-lg border">{children}</div>
      {pagination}
    </div>
  )
}

// ── 외부 서버 탭 ─────────────────────────────────────────────────────────────
const SERVER_LABEL: Record<string, string> = {
  embedding: "임베딩", rerank: "리랭커", reranker: "리랭커", detection: "검출",
  vlm: "VLM", hwp_render: "HWP 렌더",
}

function gb(bytes?: number): string {
  if (bytes == null) return "—"
  return `${(bytes / 1024 ** 3).toFixed(1)}GB`
}
function uptime(sec?: number): string {
  if (!sec) return "—"
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}
function MetricRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 py-0.5 text-sm">
      <span>{label}</span>
      <span className="tabular-nums">{children}</span>
    </div>
  )
}

function ServerCard({ s }: { s: ExtServerStat }) {
  const label = SERVER_LABEL[s.kind] ?? s.kind
  const st = s.stats
  return (
    <Card className="w-[500px]">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          {label}
          {s.url && <span className="font-mono text-sm font-normal">{s.url}</span>}
          {st && <DeviceBadge device={st.device} />}
          <Badge variant={s.ok ? "default" : "destructive"} className="ml-auto px-1.5 py-0 text-sm">
            {s.ok ? "연결됨" : "연결 안 됨"}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="text-sm">
        {!s.ok || !st ? (
          <p>{s.error ?? "응답 없음"} {s.url && <span className="font-mono">· {s.url}</span>}</p>
        ) : (
          <div className="space-y-0.5">
            <MetricRow label="모델 · 버전">
              <span className="font-mono">{st.model || "—"}</span>
              {st.version ? ` · v${st.version}` : ""}
              {(st.models?.count ?? 0) > 1 ? ` · 로딩 ${st.models!.count}` : ""}
            </MetricRow>
            {st.uptime_seconds != null && <MetricRow label="가동시간">{uptime(st.uptime_seconds)}</MetricRow>}
            {st.system && (
              <>
                <ResourceBar label="CPU" pct={st.system?.cpu_percent} />
                <ResourceBar
                  label="RAM"
                  pct={st.system?.mem_percent}
                  detail={`${gb(st.system?.mem_used_bytes)}/${gb(st.system?.mem_total_bytes)}`}
                />
              </>
            )}
            {(st.gpu ?? []).map((g) => (
              <div key={g.index} className="space-y-0.5">
                <ResourceBar label={`GPU${g.index} 사용률`} pct={g.utilization_percent} detail={g.name ?? undefined} />
                {g.mem_total_bytes ? (
                  <ResourceBar
                    label={`GPU${g.index} 메모리`}
                    pct={Math.round(((g.mem_used_bytes ?? 0) / g.mem_total_bytes) * 100)}
                    detail={`${gb(g.mem_used_bytes)}/${gb(g.mem_total_bytes)}${
                      g.mem_reserved_bytes != null ? ` · 프로세스 ${gb(g.mem_reserved_bytes)}` : ""
                    }${g.temperature_c != null ? ` · ${g.temperature_c}°C` : ""}`}
                  />
                ) : null}
              </div>
            ))}
            {st.requests && (
              <MetricRow label="요청">
                총 {st.requests.total ?? 0} · 진행 {st.requests.inflight ?? 0} · 오류 {st.requests.errors ?? 0} · {st.requests.avg_latency_ms ?? 0}ms
              </MetricRow>
            )}
            {st.extra &&
              Object.entries(st.extra).map(([k, v]) => (
                <MetricRow key={k} label={k}>{v}</MetricRow>
              ))}
            {st.requests?.domain && Object.keys(st.requests.domain).length > 0 && (
              <MetricRow label="처리량">
                {Object.entries(st.requests.domain).map(([k, v]) => `${k}=${v}`).join(" · ")}
              </MetricRow>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/** URL 의 host:port — 파싱 불가/빈값이면 null. */
function hostOfUrl(u?: string | null): string | null {
  if (!u) return null
  try {
    return new URL(u).host || null
  } catch {
    return null
  }
}

function ServersTab() {
  const { data: servers, loading, refresh } = usePolledList<ExtServerStat>(getExtServerStats)
  const { data: replicas, refresh: refreshReplicas } = usePolledList<ExtServerStat>(getRegisteredExtServers)
  // 중복 제거 — 프로브 대상이 heartbeat 레플리카와 같은 host:port 면 같은 서버를 두 번
  // 보여주는 것이라 숨긴다. 단 프로브 실패는 "백엔드가 접근 불가"라는 독립 신호라 유지.
  const replicaHosts = new Set(replicas.map((r) => hostOfUrl(r.url)).filter(Boolean))
  const probes = servers.filter((s) => {
    if (!s.ok) return true
    const h = hostOfUrl(s.url)
    return !h || !replicaHosts.has(h)
  })
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-sm">
          서비스(임베딩·리랭커·검출·VLM·HWP 렌더) 상태·메트릭. 등록 레플리카는 하트비트, 설정 URL은 프로브(/stats·/models·/health).
        </span>
        <Button variant="outline" size="sm" className="ml-auto" onClick={() => { refresh(); refreshReplicas() }}>
          <RefreshCw className="mr-1 h-4 w-4" /> 새로고침
        </Button>
      </div>

      {loading && servers.length === 0 && replicas.length === 0 ? (
        <div className="flex h-24 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="flex flex-wrap gap-4">
          {replicas.map((s, i) => (
            <ServerCard key={`rep-${s.url ?? i}`} s={s} />
          ))}
          {probes.map((s) => (
            <ServerCard key={s.kind} s={s} />
          ))}
        </div>
      )}
    </div>
  )
}

// ── 워커 탭 ───────────────────────────────────────────────────────────────────
const WORKER_STATUS: Record<string, string> = {
  starting: "기동중", idle: "대기", busy: "처리중", stopped: "중지",
}

// 리소스 사용률 막대 — pct(0~100) 기준, 임계에 따라 색이 바뀐다.
function ResourceBar({ label, pct, detail }: { label: string; pct?: number | null; detail?: string }) {
  const p = pct == null ? 0 : Math.max(0, Math.min(100, pct))
  const color = p >= 90 ? "bg-red-500" : p >= 70 ? "bg-amber-500" : "bg-primary"
  return (
    <div className="space-y-0.5 py-0.5">
      <div className="flex items-center justify-between text-sm">
        <span>{label}</span>
        <span className="tabular-nums">
          {pct == null ? "—" : `${pct}%`}
          {detail ? <span> · {detail}</span> : null}
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${p}%` }} />
      </div>
    </div>
  )
}

function WorkerCard({ w }: { w: WorkerInfo }) {
  return (
    <Card className="w-[500px]">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Cpu className="h-4 w-4" />
          <span className="font-mono text-sm">{w.hostname ?? "?"}·{w.pid ?? "?"}</span>
          <Badge variant="outline" className="px-1.5 py-0 text-sm uppercase" title={`mode: ${w.mode ?? "?"}`}>
            {w.runtime ?? w.mode ?? "?"}
          </Badge>
          <DeviceBadge device="cpu" />
          <Badge variant={w.alive ? "default" : "destructive"} className="ml-auto px-1.5 py-0 text-sm">
            {w.alive ? "연결됨" : "연결 안 됨"}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="text-sm">
        <div className="space-y-0.5">
          <MetricRow label="상태">
            {WORKER_STATUS[w.status] ?? w.status}
            {w.status === "busy" && w.current_job_id && (
              <span className="ml-1 font-mono">{w.current_job_id.slice(0, 8)}…</span>
            )}
          </MetricRow>
          <MetricRow label="처리량">{w.processed_total}건</MetricRow>
          <ResourceBar
            label="CPU (호스트)"
            pct={w.metrics?.host_cpu_percent}
            detail={w.metrics?.cpu_percent != null ? `프로세스 ${w.metrics.cpu_percent}%` : undefined}
          />
          <ResourceBar
            label="RAM (호스트)"
            pct={w.metrics?.host_mem_percent}
            detail={`${gb(w.metrics?.host_mem_used_bytes)}/${gb(w.metrics?.host_mem_total_bytes)} · 프로세스 ${gb(w.metrics?.rss_bytes)}`}
          />
          {(w.metrics?.gpu ?? []).map((g) => (
            <div key={g.index} className="space-y-0.5">
              <ResourceBar label={`GPU${g.index} 사용률`} pct={g.utilization_percent} detail={g.name ?? undefined} />
              {g.mem_total_bytes ? (
                <ResourceBar
                  label={`GPU${g.index} 메모리`}
                  pct={Math.round(((g.mem_used_bytes ?? 0) / g.mem_total_bytes) * 100)}
                  detail={`${gb(g.mem_used_bytes)}/${gb(g.mem_total_bytes)}${g.temperature_c != null ? ` · ${g.temperature_c}°C` : ""}`}
                />
              ) : null}
            </div>
          ))}
          <MetricRow label="하트비트">
            {w.heartbeat_age_seconds != null ? `${w.heartbeat_age_seconds}s 전` : "—"}
            {w.metrics?.load1 != null ? ` · load ${w.metrics.load1}` : ""}
          </MetricRow>
          <MetricRow label="버전">v{w.version ?? "—"}</MetricRow>
        </div>
      </CardContent>
    </Card>
  )
}

function WorkersTab() {
  const { data: workers, loading, refresh } = usePolledList<WorkerInfo>(getWorkers)
  const live = workers.filter((w) => w.alive).length
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-sm">
          인제스천 워커 — 하트비트 기반 생존 판정. 살아있는 워커 {live}/{workers.length}.
          워커는 별도 프로세스(<span className="font-mono">app.worker_main</span>)로 분리·확장 가능.
        </span>
        <Button variant="outline" size="sm" className="ml-auto" onClick={refresh}>
          <RefreshCw className="mr-1 h-4 w-4" /> 새로고침
        </Button>
      </div>
      {loading && workers.length === 0 ? (
        <div className="flex h-24 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : workers.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">등록된 워커가 없습니다.</p>
      ) : (
        <div className="flex flex-wrap gap-4">
          {workers.map((w) => (
            <WorkerCard key={w.id} w={w} />
          ))}
        </div>
      )}
    </div>
  )
}

export default function JobsMonitorPage() {
  return (
    <>
      <DashboardHeader title="잡 모니터링" />
      <div className="flex flex-1 flex-col p-4">
        <UrlTabs defaultValue="ingestion">
          <TabsList>
            <TabsTrigger value="ingestion">인제스천</TabsTrigger>
            <TabsTrigger value="eval">평가</TabsTrigger>
            <TabsTrigger value="sweep">스윕</TabsTrigger>
            <TabsTrigger value="finetune">파인튜닝</TabsTrigger>
            <TabsTrigger value="workers">워커</TabsTrigger>
            <TabsTrigger value="servers">서비스</TabsTrigger>
          </TabsList>
          <TabsContent value="ingestion" className="mt-4">
            <IngestionTab />
          </TabsContent>
          <TabsContent value="eval" className="mt-4">
            <EvalTab />
          </TabsContent>
          <TabsContent value="sweep" className="mt-4">
            <SweepTab />
          </TabsContent>
          <TabsContent value="finetune" className="mt-4">
            <FinetuneTab />
          </TabsContent>
          <TabsContent value="workers" className="mt-4">
            <WorkersTab />
          </TabsContent>
          <TabsContent value="servers" className="mt-4">
            <ServersTab />
          </TabsContent>
        </UrlTabs>
      </div>
    </>
  )
}
