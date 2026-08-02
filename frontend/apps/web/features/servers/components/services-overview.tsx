// 서비스 관리 탭 — 전 서버(docker/systemd)·클러스터(k8s)·외부(수동) 배포 서비스의 통합 그리드.
// 서비스당 3행 — 컬럼별 값 길이 프로필을 맞춰 배치(C1=긴 값, C2=중간, C3·C4=짧음):
//   1행: 서비스명 | 배포 위치 | 배포 유형 | 상태     | 동작
//   2행: 엔드포인트 | 모델     | 디바이스  | 가동시간  | 재시작 횟수
//   3행: 이미지    | GPU     | CPU      | MEM     | 상세(워커·오류)
// 유형은 rowSpan=3 단독 셀. 백엔드 GET /api/v1/deploy/overview, 설계 agent-services-overview.md §4 Step 5.
"use client"

import Link from "next/link"
import { useCallback, useEffect, useMemo, useState } from "react"
import { AlertTriangle, Copy, RefreshCw, RotateCw } from "lucide-react"
import { toast } from "sonner"

import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@workspace/ui/components/alert-dialog"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import { Switch } from "@workspace/ui/components/switch"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@workspace/ui/components/tooltip"

import {
  fetchOverview,
  formatUptime,
  serviceAction,
  type DeployTarget,
  type ExternalService,
  type ManagedService,
  type Overview,
} from "@/features/deploy/api"
import { DeviceBadge } from "@/features/deploy/components/device-badge"
import { ServiceState } from "@/features/deploy/components/service-state"
import { WorkerCell } from "@/features/deploy/components/worker-cell"
import { useAuth } from "@/features/auth"

// 유형 표시 순서·라벨 — 배포 다이얼로그 KINDS 와 일치("" = kind 없는 인프라 컨테이너).
const KIND_ORDER = ["worker", "embedding", "reranker", "detection", "hwp_render", "vlm", ""] as const
const KIND_LABELS: Record<string, string> = {
  worker: "워커",
  embedding: "임베딩",
  reranker: "리랭커",
  detection: "검출",
  hwp_render: "HWP 렌더",
  vlm: "VLM",
  "": "기타",
}

const RUNTIME_LABELS: Record<string, string> = {
  docker: "DOCKER",
  systemd: "SYSTEMD",
  k8s: "K8S",
}

// 배포 유형별 배지 색 — DOCKER=하늘, SYSTEMD=보라, K8S=남색, MANUAL=호박.
const RUNTIME_BADGE_CLS: Record<string, string> = {
  docker: "border-sky-500/40 bg-sky-500/10 text-sky-600 dark:text-sky-400",
  systemd: "border-violet-500/40 bg-violet-500/10 text-violet-600 dark:text-violet-400",
  k8s: "border-indigo-500/40 bg-indigo-500/10 text-indigo-600 dark:text-indigo-400",
  manual: "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400",
}

const EXTERNAL_SOURCE_LABELS: Record<string, string> = {
  heartbeat: "자기 등록(heartbeat)",
  settings: "전역 설정 URL 폴링",
  worker: "워커 레지스트리(자기 등록)",
}

const POLL_MS = 30_000

// 통합 그리드의 논리 행 — 관리형 또는 외부(수동).
type UnifiedRow =
  | { type: "managed"; key: string; kind: string; svc: ManagedService; target: DeployTarget }
  | { type: "external"; key: string; kind: string; x: ExternalService }

function kindKey(k: string): string {
  return KIND_LABELS[k] != null ? k : ""
}

function kindRank(k: string): number {
  const i = KIND_ORDER.indexOf(k as (typeof KIND_ORDER)[number])
  return i < 0 ? KIND_ORDER.length : i
}

/** 초 단위 업타임 → "2일 3시간" 형식(외부/stats 용). */
function formatUptimeSeconds(s?: number | null): string {
  if (s == null || s < 0) return ""
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d > 0) return `${d}일 ${h}시간`
  if (h > 0) return `${h}시간 ${m}분`
  return m > 0 ? `${m}분` : `${Math.floor(s)}초`
}

function gib(bytes?: number | null): string | null {
  return bytes == null ? null : `${(bytes / 1024 ** 3).toFixed(1)}G`
}

function pct(v?: number | null): string {
  return v == null ? "" : `${v.toFixed(0)}%`
}

/** 사용률 미니 바(0~100) — 70%/90% 임계 색상(charts.UsageBar 와 동일 규약, recharts 비의존). */
function MiniBar({ percent }: { percent: number }) {
  const c = percent > 90 ? "bg-red-500" : percent > 70 ? "bg-yellow-500" : "bg-green-500"
  return (
    <span className="inline-block h-1.5 w-12 rounded-full bg-muted align-middle">
      <span
        className={`block h-full rounded-full ${c}`}
        style={{ width: `${Math.min(Math.max(percent, 0), 100)}%` }}
      />
    </span>
  )
}

/** % 값 셀 — 미니 바 + 숫자. 값 없으면 빈칸. */
function PctCell({ value }: { value?: number | null }) {
  if (value == null) return null
  return (
    <span className="inline-flex items-center gap-1.5">
      <MiniBar percent={value} />
      <span>{pct(value)}</span>
    </span>
  )
}

function targetLabel(t: DeployTarget): string {
  if (t.type === "k8s") return `k8s: ${t.cluster_id}/${t.namespace ?? "default"}`
  return t.hostname ?? "-"
}

function hostOf(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

/** 배포 위치 셀 — 에이전트 호스트는 상세(서비스 탭) 딥링크, k8s 는 텍스트. */
function TargetCell({ t }: { t: DeployTarget }) {
  if (t.type === "agent_host" && t.hostname) {
    return (
      <Link
        href={`/dashboard/server-management/${encodeURIComponent(t.hostname)}?tab=services`}
        className="text-sm underline-offset-4 hover:underline"
      >
        {t.hostname}
      </Link>
    )
  }
  return <span className="text-sm">{targetLabel(t)}</span>
}

const Dash = () => null  // 빈값은 표시하지 않는다

export function ServicesOverview() {
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser
  const [data, setData] = useState<Overview | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [kindFilter, setKindFilter] = useState<string | null>(null)
  // 재시작 확인 다이얼로그 대상(관리형 행) — 아이콘 클릭 시 바로 실행하지 않는다.
  const [restartTarget, setRestartTarget] = useState<Extract<UnifiedRow, { type: "managed" }> | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setData(await fetchOverview())
      setFetchError(null)
    } catch (e) {
      setFetchError(e instanceof Error ? e.message : "서비스 집계 조회 실패")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!autoRefresh) return
    const id = setInterval(() => void load(), POLL_MS)
    return () => clearInterval(id)
  }, [autoRefresh, load])

  const targets = useMemo(() => data?.targets ?? [], [data])
  const failures = useMemo(() => targets.filter((t) => t.error), [targets])

  // 관리형 + 외부(수동)를 단일 목록으로 — 유형 순서 → 이름 정렬.
  const rows: UnifiedRow[] = useMemo(() => {
    const out: UnifiedRow[] = []
    for (const t of targets)
      for (const svc of t.services)
        out.push({
          type: "managed",
          key: `m-${targetLabel(t.target)}-${svc.name}`,
          kind: kindKey(svc.kind),
          svc,
          target: t.target,
        })
    for (const x of data?.external ?? [])
      out.push({ type: "external", key: `x-${x.source}-${x.url}`, kind: kindKey(x.kind), x })
    return out.sort((a, b) => {
      const k = kindRank(a.kind) - kindRank(b.kind)
      if (k !== 0) return k
      const an = a.type === "managed" ? a.svc.name : a.x.url
      const bn = b.type === "managed" ? b.svc.name : b.x.url
      return an.localeCompare(bn)
    })
  }, [targets, data])

  const kindCounts = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of rows) m.set(r.kind, (m.get(r.kind) ?? 0) + 1)
    return m
  }, [rows])

  const visible = useMemo(
    () => (kindFilter == null ? rows : rows.filter((r) => r.kind === kindFilter)),
    [rows, kindFilter]
  )

  const runningCount = rows.filter(
    (r) => (r.type === "managed" ? r.svc.state === "running" : r.x.ok)
  ).length
  const troubleCount = rows.filter((r) =>
    r.type === "managed" ? ["failed", "error", "partial"].includes(r.svc.state) : !r.x.ok
  ).length
  const externalCount = rows.filter((r) => r.type === "external").length

  async function restart(r: Extract<UnifiedRow, { type: "managed" }>) {
    setRestartTarget(null)
    setBusy(r.key)
    try {
      await serviceAction(r.target, r.svc.name, "restart")
      toast.success(`${r.svc.name} 재시작`)
      await load()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "재시작 실패")
    } finally {
      setBusy(null)
    }
  }

  async function copyEndpoint(v: string) {
    await navigator.clipboard.writeText(v)
    toast.success("엔드포인트 복사됨")
  }

  return (
    <div className="flex flex-col gap-4">
      {/* 요약 + 새로고침/폴링 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span>
            전체 <span className="font-semibold text-foreground">{rows.length}</span> 서비스
          </span>
          <span>·</span>
          <span>
            실행 중 <span className="font-semibold text-foreground">{runningCount}</span>
          </span>
          {externalCount > 0 && (
            <>
              <span>·</span>
              <span>
                외부(수동) <span className="font-semibold text-foreground">{externalCount}</span>
              </span>
            </>
          )}
          {troubleCount > 0 && <Badge variant="destructive">이상 {troubleCount}</Badge>}
          {failures.length > 0 && <Badge variant="warning">조회 실패 대상 {failures.length}</Badge>}
          {data && (
            <span>(기준 {new Date(data.generated_at).toLocaleTimeString()})</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={autoRefresh} onCheckedChange={setAutoRefresh} /> 자동 새로고침(30초)
          </label>
          <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={loading ? "size-4 animate-spin" : "size-4"} /> 새로고침
          </Button>
        </div>
      </div>

      {/* 유형 필터 칩 */}
      <div className="flex flex-wrap items-center gap-1.5">
        <Button
          variant={kindFilter == null ? "secondary" : "ghost"}
          size="sm"
          className="h-7 px-2.5 text-sm"
          onClick={() => setKindFilter(null)}
        >
          전체 {rows.length}
        </Button>
        {KIND_ORDER.filter((k) => kindCounts.has(k)).map((k) => (
          <Button
            key={k || "etc"}
            variant={kindFilter === k ? "secondary" : "ghost"}
            size="sm"
            className="h-7 px-2.5 text-sm"
            onClick={() => setKindFilter(kindFilter === k ? null : k)}
          >
            {KIND_LABELS[k]} {kindCounts.get(k)}
          </Button>
        ))}
      </div>

      {/* 조회 실패 대상 — 조용히 빠지면 "서비스 없음"과 구분이 안 되므로 명시 노출 */}
      {fetchError && (
        <div className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          <AlertTriangle className="size-4 shrink-0" /> {fetchError}
        </div>
      )}
      {failures.map((f, i) => (
        <div
          key={i}
          className="flex items-center gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm text-amber-700 dark:text-amber-400"
        >
          <AlertTriangle className="size-4 shrink-0" />
          <span className="font-medium">{targetLabel(f.target)}</span>
          {f.target.method && (
            <Badge variant="outline" className="text-xs">
              {RUNTIME_LABELS[f.target.method] ?? f.target.method}
            </Badge>
          )}
          <span>조회 실패 — {f.error}</span>
        </div>
      ))}

      {!loading && rows.length === 0 && failures.length === 0 && !fetchError && (
        <div className="rounded-md border px-3 py-8 text-center text-sm text-muted-foreground">
          배포된 서비스가 없습니다 — 서버 관리 탭에서 서버를 선택해 배포하세요.
        </div>
      )}

      {/* 통합 그리드 — 서비스당 3행(유형은 rowSpan=3 단독 셀) */}
      {rows.length > 0 && (
        <TooltipProvider delayDuration={300}>
          <div className="rounded-md border">
            <Table className="table-fixed text-sm">
              <TableHeader>
                <TableRow className="border-b-0">
                  <TableHead rowSpan={3} className="w-20 border-r text-center text-sm">유형</TableHead>
                  <TableHead className="h-8 w-[400px] text-sm">서비스</TableHead>
                  <TableHead className="h-8 w-[300px] text-sm">배포 위치</TableHead>
                  <TableHead className="h-8 w-[100px] text-center text-sm">배포 유형</TableHead>
                  <TableHead className="h-8 w-[100px] text-center text-sm">상태</TableHead>
                  <TableHead className="h-8 w-[100px] text-center text-sm">동작</TableHead>
                </TableRow>
                <TableRow className="border-b-0 bg-muted/20">
                  <TableHead className="h-8 text-sm">엔드포인트</TableHead>
                  <TableHead className="h-8 text-sm">모델</TableHead>
                  <TableHead className="h-8 text-center text-sm">디바이스</TableHead>
                  <TableHead className="h-8 text-center text-sm">가동시간</TableHead>
                  <TableHead className="h-8 text-center text-sm">재시작 횟수</TableHead>
                </TableRow>
                <TableRow className="bg-muted/20">
                  <TableHead className="h-8 text-sm">이미지 · 버전</TableHead>
                  <TableHead className="h-8 text-sm">GPU</TableHead>
                  <TableHead className="h-8 text-center text-sm">CPU</TableHead>
                  <TableHead className="h-8 text-center text-sm">MEM</TableHead>
                  <TableHead className="h-8 text-center text-sm">상세</TableHead>
                </TableRow>
              </TableHeader>
              {visible.map((r) =>
                  r.type === "managed" ? (
                    <ManagedRows
                      key={r.key}
                      r={r}
                      canManage={!!canManage}
                      busy={busy === r.key}
                      onRestart={() => setRestartTarget(r)}
                      onCopy={copyEndpoint}
                    />
                  ) : (
                  <ExternalRows key={r.key} r={r} onCopy={copyEndpoint} />
                )
              )}
            </Table>
          </div>
        </TooltipProvider>
      )}

      {/* 재시작 확인 — 어떤 서비스를 어디서 재시작하는지 명확히 */}
      <AlertDialog open={!!restartTarget} onOpenChange={(o) => !o && setRestartTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader className="text-start">
            <AlertDialogTitle>서비스 재시작</AlertDialogTitle>
            <AlertDialogDescription>
              <span className="font-mono font-medium text-foreground">{restartTarget?.svc.name}</span>
              {" "}({restartTarget ? targetLabel(restartTarget.target) : ""},{" "}
              {restartTarget ? RUNTIME_LABELS[restartTarget.svc.runtime] ?? restartTarget.svc.runtime : ""})
              {" "}서비스를 재시작합니다. 재시작 동안 이 서비스로의 요청은 실패할 수 있습니다.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button variant="ghost" onClick={() => setRestartTarget(null)}>취소</Button>
            <Button onClick={() => restartTarget && void restart(restartTarget)}>
              <RotateCw className="size-4" /> 재시작
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function EndpointCell({ url, onCopy }: { url?: string | null; onCopy: (v: string) => Promise<void> }) {
  if (!url) return <Dash />
  return (
    <span className="inline-flex items-center gap-1 font-mono text-sm">
      {url}
      <Button variant="ghost" size="icon" className="size-6" onClick={() => void onCopy(url)}>
        <Copy className="size-3" />
      </Button>
    </span>
  )
}

/** 유형 셀 — 3행을 관통하는 단독 셀(그룹 앵커). */
function KindCell({ kind }: { kind: string }) {
  return (
    <TableCell rowSpan={3} className="border-r text-center align-middle">
      <Badge variant="outline" className="text-xs">{KIND_LABELS[kind]}</Badge>
    </TableCell>
  )
}

function ManagedRows({
  r,
  canManage,
  busy,
  onRestart,
  onCopy,
}: {
  r: Extract<UnifiedRow, { type: "managed" }>
  canManage: boolean
  busy: boolean
  onRestart: () => void
  onCopy: (v: string) => Promise<void>
}) {
  const s = r.svc
  const st = s.stats
  const gpu = (st?.gpu ?? []).filter((g) => g.name)
  const loadedExtra = (st?.models_loaded?.length ?? 0) > 1 ? ` (+${st!.models_loaded!.length - 1})` : ""
  const uptime =
    s.state !== "running"
      ? ""
      : formatUptime(s.started_at) !== "-"
        ? formatUptime(s.started_at)
        : formatUptimeSeconds(st?.uptime_seconds)
  return (
    // 서비스(3행)를 tbody 그룹으로 — hover 시 세 행이 함께 하이라이트
    <TableBody className="group/svc border-b [&_tr]:h-[40px] [&_td]:py-0">
      {/* 1행 — 식별·상태·조작 */}
      <TableRow className="group-hover/svc:bg-muted/50 hover:bg-muted/50">
        <KindCell kind={r.kind} />
        <TableCell className="font-mono text-sm font-medium">{s.name}</TableCell>
        <TableCell>
          <TargetCell t={r.target} />
        </TableCell>
        <TableCell className="text-center">
          <Badge variant="outline" className={`text-xs ${RUNTIME_BADGE_CLS[s.runtime] ?? ""}`}>
            {RUNTIME_LABELS[s.runtime] ?? s.runtime}
          </Badge>
        </TableCell>
        <TableCell className="text-center">
          <ServiceState s={s} />
        </TableCell>
        <TableCell className="text-center">
          {canManage ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" className="size-7" disabled={busy} onClick={onRestart}>
                  <RotateCw className={busy ? "size-4 animate-spin" : "size-4"} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>재시작</TooltipContent>
            </Tooltip>
          ) : (
            <Dash />
          )}
        </TableCell>
      </TableRow>
      {/* 2행 — 엔드포인트·모델·디바이스·가동시간·재시작 횟수 */}
      <TableRow className="bg-muted/20 group-hover/svc:bg-muted/50 hover:bg-muted/50">
        <TableCell className="overflow-hidden py-1.5">
          <span className="block truncate">
            <EndpointCell url={s.endpoint} onCopy={onCopy} />
          </span>
        </TableCell>
        <TableCell className="overflow-hidden py-1.5">
          {st?.model ? (
            <span className="block truncate font-mono" title={st.models_loaded?.join(", ") || st.model}>
              {st.model}
              {loadedExtra}
            </span>
          ) : (
            <Dash />
          )}
        </TableCell>
        <TableCell className="py-1.5 text-center">
          <DeviceBadge device={st?.device} />
        </TableCell>
        <TableCell className="py-1.5 text-center">{uptime}</TableCell>
        <TableCell className="py-1.5 text-center">
          {s.restart_count != null && s.restart_count > 0 ? (
            <span className="text-amber-600">{s.restart_count}회</span>
          ) : (
            <span>{s.restart_count != null ? "0회" : ""}</span>
          )}
        </TableCell>
      </TableRow>
      {/* 3행 — 이미지·GPU·CPU·MEM·상세 */}
      <TableRow className="bg-muted/20 group-hover/svc:bg-muted/50 hover:bg-muted/50">
        <TableCell className="overflow-hidden py-1.5">
          {s.image ? (
            <span className="block truncate font-mono" title={s.image}>{s.image}</span>
          ) : s.version ? (
            <span>v{s.version}</span>
          ) : (
            <Dash />
          )}
        </TableCell>
        <TableCell className="overflow-hidden py-1.5">
          {gpu.length > 0 ? (
            <span className="block truncate" title={gpu.map((g) => g.name).join(", ")}>
              {gpu.map((g, i) => (
                <span key={i} className="inline-flex items-center gap-1.5">
                  {i > 0 && " · "}
                  {g.name}
                  {g.utilization_percent != null && <PctCell value={g.utilization_percent} />}
                  {gib(g.mem_used_bytes) ? `(${gib(g.mem_used_bytes)}/${gib(g.mem_total_bytes) ?? "?"})` : ""}
                </span>
              ))}
            </span>
          ) : (
            <Dash />
          )}
        </TableCell>
        <TableCell className="py-1.5 text-center"><PctCell value={s.cpu_percent ?? st?.cpu_percent} /></TableCell>
        <TableCell className="py-1.5 text-center"><PctCell value={s.mem_percent ?? st?.mem_percent} /></TableCell>
        <TableCell className="py-1.5 text-center">
          <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-sm">
            {s.kind === "worker" && <WorkerCell s={s} />}
            {s.message && (
              <span className="inline-flex items-center gap-1 text-destructive">
                <AlertTriangle className="size-3" />
                {s.message}
                {s.exit_code != null && s.state !== "running" ? ` (exit ${s.exit_code})` : ""}
              </span>
            )}
            {s.kind !== "worker" && !s.message && <Dash />}
          </div>
        </TableCell>
      </TableRow>
    </TableBody>
  )
}

function ExternalRows({
  r,
  onCopy,
}: {
  r: Extract<UnifiedRow, { type: "external" }>
  onCopy: (v: string) => Promise<void>
}) {
  const x = r.x
  const host = hostOf(x.url)
  return (
    <TableBody className="group/svc border-b [&_tr]:h-[40px] [&_td]:py-0">
      {/* 1행 — 식별·상태 */}
      <TableRow className="group-hover/svc:bg-muted/50 hover:bg-muted/50">
        <KindCell kind={r.kind} />
        <TableCell className="font-mono text-sm font-medium">{host}</TableCell>
        <TableCell className="text-sm">{host.split(":")[0]}</TableCell>
        <TableCell className="text-center">
          <Badge
            variant="outline"
            className={`text-xs ${RUNTIME_BADGE_CLS.manual}`}
            title={EXTERNAL_SOURCE_LABELS[x.source] ?? x.source}
          >
            MANUAL
          </Badge>
        </TableCell>
        <TableCell className="text-center">
          <Badge
            variant={x.ok ? "success" : "destructive"}
            title={x.error ?? undefined}
            className={x.error ? "cursor-help" : undefined}
          >
            {x.ok ? "CONNECTED" : "DISCONNECTED"}
          </Badge>
        </TableCell>
        <TableCell className="text-center">
          <Dash />
        </TableCell>
      </TableRow>
      {/* 2행 — 엔드포인트·모델·디바이스·가동시간 */}
      <TableRow className="bg-muted/20 group-hover/svc:bg-muted/50 hover:bg-muted/50">
        <TableCell className="overflow-hidden py-1.5">
          <span className="block truncate">
            <EndpointCell url={x.url} onCopy={onCopy} />
          </span>
        </TableCell>
        <TableCell className="overflow-hidden py-1.5">
          {x.model ? (
            <span className="block truncate font-mono" title={x.model}>{x.model}</span>
          ) : (
            <Dash />
          )}
        </TableCell>
        <TableCell className="py-1.5 text-center">
          <DeviceBadge device={x.device} />
        </TableCell>
        <TableCell className="py-1.5 text-center">
          {x.ok ? formatUptimeSeconds(x.uptime_seconds) : ""}
        </TableCell>
        <TableCell className="py-1.5 text-center">
          <Dash />
        </TableCell>
      </TableRow>
      {/* 3행 — 버전·CPU·MEM·관측 소스/오류 */}
      <TableRow className="bg-muted/20 group-hover/svc:bg-muted/50 hover:bg-muted/50">
        <TableCell className="py-1.5">{x.version ? `서버 v${x.version}` : <Dash />}</TableCell>
        <TableCell className="py-1.5">
          <Dash />
        </TableCell>
        <TableCell className="py-1.5 text-center"><PctCell value={x.cpu_percent} /></TableCell>
        <TableCell className="py-1.5 text-center"><PctCell value={x.mem_percent} /></TableCell>
        <TableCell className="py-1.5 text-center">
          <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-sm">
            {x.error && (
              <span className="inline-flex items-center gap-1 text-destructive">
                <AlertTriangle className="size-3" /> {x.error}
              </span>
            )}
          </div>
        </TableCell>
      </TableRow>
    </TableBody>
  )
}
