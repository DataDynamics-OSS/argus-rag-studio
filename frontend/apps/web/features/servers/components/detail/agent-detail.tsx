// 에이전트 상세 — 헤더 + 요약 스트립 + 탭(개요/GPU/서비스·배포/프로세스/터미널). 실시간 차트 포함.
"use client"

import { UrlTabs } from "@/components/url-tabs"
import { useCallback, useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { ArrowLeft, Cpu, HardDrive, MemoryStick, RefreshCw, Rocket, RotateCw, Square, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import { Card, CardContent, CardHeader, CardTitle } from "@workspace/ui/components/card"
import { TabsContent, TabsList, TabsTrigger } from "@workspace/ui/components/tabs"
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
  fetchGpu,
  fetchMetrics,
  fetchProcesses,
  fetchServer,
  registerServers,
  type GpuResult,
  type HostMetrics,
} from "../../api"
import {
  formatUptime,
  listServices,
  removeService,
  serviceAction,
  type DeployTarget,
  type ManagedService,
} from "@/features/deploy/api"
import { serverStatusLabels, serverStatusStyles } from "../../data/data"
import { ResourceCell, ServiceState } from "@/features/deploy/components/service-state"
import { WorkerCell } from "@/features/deploy/components/worker-cell"

import { type Server } from "../../data/schema"
import { useRollingSeries } from "../../hooks/use-rolling-series"
import { ServersServicesDialog } from "../servers-services-dialog"
import { TimeAreaChart, TimeLineChart, UsageBar } from "./charts"

function gib(bytes?: number | null) {
  return bytes == null ? "-" : (bytes / 1024 ** 3).toLocaleString(undefined, { maximumFractionDigits: 1 })
}
function mbps(bytesPerSec: number) {
  return bytesPerSec / 1024 / 1024
}

export function AgentDetail({ hostname }: { hostname: string }) {
  const [server, setServer] = useState<Server | null>(null)
  const [loading, setLoading] = useState(true)
  const [servicesOpen, setServicesOpen] = useState(false)

  const refreshServer = useCallback(async () => {
    try {
      setServer(await fetchServer(hostname))
    } catch {
      /* 무시 — 헤더만 영향 */
    } finally {
      setLoading(false)
    }
  }, [hostname])

  useEffect(() => {
    void refreshServer()
    const t = setInterval(() => void refreshServer(), 10000)
    return () => clearInterval(t)
  }, [refreshServer])

  const registered = server?.status === "REGISTERED"

  // 실시간 폴링(REGISTERED 일 때만)
  const metricsFetch = useCallback(() => fetchMetrics(hostname), [hostname])
  const gpuFetch = useCallback(() => fetchGpu(hostname), [hostname])
  const { latest: metrics, series: mSeries, error: mErr } = useRollingSeries<HostMetrics>(metricsFetch, {
    intervalMs: 3000,
    enabled: registered,
  })
  const { latest: gpu, series: gSeries } = useRollingSeries<GpuResult>(gpuFetch, {
    intervalMs: 3000,
    enabled: registered,
  })

  // ---- 차트 데이터 가공 ----
  const cpuData = useMemo(
    () => mSeries.map((s) => ({ t: s.t, cpu: s.v.cpu?.usage_percent ?? 0 })),
    [mSeries]
  )
  const memData = useMemo(
    () => mSeries.map((s) => ({ t: s.t, mem: s.v.memory?.usage_percent ?? 0 })),
    [mSeries]
  )
  const netData = useMemo(() => {
    const sumNet = (m: HostMetrics) =>
      (m.networks ?? [])
        .filter((n) => n.interface !== "lo")
        .reduce((a, n) => ({ rx: a.rx + n.bytes_recv, tx: a.tx + n.bytes_sent }), { rx: 0, tx: 0 })
    const out: { t: number; rx: number; tx: number }[] = []
    for (let i = 1; i < mSeries.length; i++) {
      const prev = mSeries[i - 1]!
      const cur = mSeries[i]!
      const dt = (cur.t - prev.t) / 1000 || 1
      const a = sumNet(prev.v)
      const b = sumNet(cur.v)
      out.push({
        t: cur.t,
        rx: Math.max(0, mbps((b.rx - a.rx) / dt)),
        tx: Math.max(0, mbps((b.tx - a.tx) / dt)),
      })
    }
    return out
  }, [mSeries])
  const gpuUtilData = useMemo(
    () =>
      gSeries.map((s) => {
        const gs = s.v.gpus ?? []
        const avg = gs.length ? gs.reduce((a, g) => a + (g.util_percent ?? 0), 0) / gs.length : 0
        return { t: s.t, gpu: avg }
      }),
    [gSeries]
  )

  // 실디스크(squashfs/loop 제외)
  const realDisks = (metrics?.disks ?? []).filter(
    (d) => !d.fs_type?.includes("squashfs") && !d.device?.startsWith("/dev/loop")
  )

  async function handleRegister() {
    try {
      await registerServers([hostname])
      toast.success("등록했습니다.")
      await refreshServer()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "등록 실패")
    }
  }

  const cpuPct = metrics?.cpu?.usage_percent ?? null
  const memPct = metrics?.memory?.usage_percent ?? null
  const rootDisk = realDisks.find((d) => d.mount_point === "/") ?? realDisks[0]
  const gpuPct = gpu?.gpus?.length
    ? gpu.gpus.reduce((a, g) => a + (g.util_percent ?? 0), 0) / gpu.gpus.length
    : null

  return (
    <div className="flex flex-col gap-4 p-6">
      {/* 헤더 */}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" asChild>
          <Link href="/dashboard/server-management">
            <ArrowLeft className="size-4" /> 목록
          </Link>
        </Button>
        <h1 className="text-xl font-semibold">{server?.hostname ?? hostname}</h1>
        <span className="font-mono text-sm text-muted-foreground">{server?.ipAddress ?? ""}</span>
        {server?.arch && <Badge variant="outline">{server.arch}</Badge>}
        {server && (
          <Badge variant="outline" className={serverStatusStyles.get(server.status)}>
            {serverStatusLabels.get(server.status) ?? server.status}
          </Badge>
        )}
        {server?.gpuName && (
          <Badge variant="outline">
            {server.gpuCount && server.gpuCount > 1 ? `${server.gpuCount}× ` : ""}
            {server.gpuName}
          </Badge>
        )}
        <div className="ml-auto flex gap-2">
          {server?.status === "UNREGISTERED" && (
            <Button size="sm" onClick={handleRegister}>
              등록
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => void refreshServer()}>
            <RefreshCw className="size-4" /> 새로고침
          </Button>
        </div>
      </div>

      {!registered && !loading && (
        <div className="rounded-md border bg-muted/30 p-3 text-sm text-muted-foreground">
          {server?.status === "DISCONNECTED"
            ? "연결이 끊긴(DISCONNECTED) 에이전트입니다. 실시간 정보를 볼 수 없습니다."
            : "등록(REGISTERED)되지 않은 에이전트입니다. 상단 ‘등록’ 후 상세 정보를 볼 수 있습니다."}
        </div>
      )}

      {registered && (
        <>
          {/* 요약 스트립 */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard icon={<Cpu className="size-4" />} label="CPU" pct={cpuPct} sub={`${metrics?.cpu?.core_count ?? "-"} cores`} />
            <StatCard
              icon={<MemoryStick className="size-4" />}
              label="메모리"
              pct={memPct}
              sub={`${gib(metrics?.memory?.used_bytes)} / ${gib(metrics?.memory?.total_bytes)} GiB`}
            />
            <StatCard
              icon={<HardDrive className="size-4" />}
              label="디스크 /"
              pct={rootDisk?.usage_percent ?? null}
              sub={rootDisk ? `${gib(rootDisk.used_bytes)} / ${gib(rootDisk.total_bytes)} GiB` : "-"}
            />
            <StatCard
              icon={<Rocket className="size-4" />}
              label="GPU"
              pct={gpuPct}
              sub={gpu?.count ? `${gpu.count}× ${gpu.gpus[0]?.name ?? ""}` : "GPU 없음"}
            />
          </div>
          {mErr && <p className="text-xs text-destructive">메트릭 폴링 오류: {mErr}</p>}

          <UrlTabs defaultValue="overview">
            <TabsList>
              <TabsTrigger value="overview">개요</TabsTrigger>
              <TabsTrigger value="gpu">GPU</TabsTrigger>
              <TabsTrigger value="services">서비스 / 배포</TabsTrigger>
              <TabsTrigger value="processes">프로세스</TabsTrigger>
            </TabsList>

            {/* 개요 */}
            <TabsContent value="overview" className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-2">
              <ChartCard title="CPU 사용률">
                <TimeLineChart data={cpuData} percent unit="%" series={[{ key: "cpu", label: "CPU", color: "#3b82f6" }]} />
              </ChartCard>
              <ChartCard title="메모리 사용률">
                <TimeAreaChart data={memData} dataKey="mem" label="메모리" color="#8b5cf6" />
              </ChartCard>
              <ChartCard title="네트워크 (MB/s)">
                <TimeLineChart
                  data={netData}
                  unit=" MB/s"
                  series={[
                    { key: "rx", label: "수신", color: "#10b981" },
                    { key: "tx", label: "송신", color: "#f59e0b" },
                  ]}
                />
              </ChartCard>
              <ChartCard title="GPU 평균 사용률">
                <TimeLineChart data={gpuUtilData} percent unit="%" series={[{ key: "gpu", label: "GPU", color: "#ef4444" }]} />
              </ChartCard>
              <ChartCard title="디스크 파티션" className="lg:col-span-2">
                <div className="space-y-2">
                  {realDisks.map((d) => (
                    <div key={d.mount_point} className="flex items-center gap-3 text-sm">
                      <span className="w-40 truncate font-mono text-xs">{d.mount_point}</span>
                      <UsageBar percent={d.usage_percent} />
                      <span className="w-32 text-right text-xs text-muted-foreground">
                        {gib(d.used_bytes)}/{gib(d.total_bytes)} GiB ({d.usage_percent.toFixed(0)}%)
                      </span>
                    </div>
                  ))}
                  {realDisks.length === 0 && <p className="text-sm text-muted-foreground">데이터 없음</p>}
                </div>
              </ChartCard>
            </TabsContent>

            {/* GPU */}
            <TabsContent value="gpu" className="mt-3">
              {!gpu?.available ? (
                <p className="text-sm text-muted-foreground">GPU가 없거나 nvidia-smi를 사용할 수 없습니다.</p>
              ) : (
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                  {gpu.gpus.map((g) => (
                    <Card key={g.index}>
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm">
                          GPU {g.index} · {g.name}
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="space-y-2 text-sm">
                        <Metric label="이용률" value={g.util_percent != null ? `${g.util_percent.toFixed(0)}%` : "-"} />
                        <Metric
                          label="VRAM"
                          value={
                            g.mem_total_mb != null
                              ? `${((g.mem_used_mb ?? 0) / 1024).toFixed(1)} / ${(g.mem_total_mb / 1024).toFixed(1)} GiB`
                              : "통합메모리(시스템 RAM 공유)"
                          }
                        />
                        <Metric label="온도" value={g.temp_c != null ? `${g.temp_c.toFixed(0)} °C` : "-"} />
                        <Metric
                          label="전력"
                          value={g.power_w != null ? `${g.power_w.toFixed(0)} W${g.power_limit_w ? ` / ${g.power_limit_w.toFixed(0)} W` : ""}` : "-"}
                        />
                      </CardContent>
                    </Card>
                  ))}
                  <ChartCard title="GPU 평균 사용률" className="lg:col-span-2">
                    <TimeLineChart data={gpuUtilData} percent unit="%" series={[{ key: "gpu", label: "GPU", color: "#ef4444" }]} />
                  </ChartCard>
                </div>
              )}
            </TabsContent>

            {/* 서비스 / 배포 */}
            <TabsContent value="services" className="mt-3">
              <div className="mb-3 flex items-center justify-between">
                <p className="text-sm text-muted-foreground">Docker 컨테이너로 배포된 워커·임베딩/리랭커/검출·hwp</p>
                <Button size="sm" onClick={() => setServicesOpen(true)}>
                  <Rocket className="size-4" /> 서비스 / 배포 관리
                </Button>
              </div>
              <ContainersTable hostname={hostname} />
              {server && (
                <ServersServicesDialog open={servicesOpen} onOpenChange={setServicesOpen} currentRow={server} />
              )}
            </TabsContent>

            {/* 프로세스 */}
            <TabsContent value="processes" className="mt-3">
              <ProcessesTable hostname={hostname} />
            </TabsContent>
          </UrlTabs>
        </>
      )}
    </div>
  )
}

function StatCard({ icon, label, pct, sub }: { icon: React.ReactNode; label: string; pct: number | null; sub?: string }) {
  return (
    <Card>
      <CardContent className="p-3">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {icon} {label}
        </div>
        <div className="mt-1 text-2xl font-semibold">{pct == null ? "-" : `${pct.toFixed(0)}%`}</div>
        {pct != null && <UsageBar percent={pct} />}
        {sub && <div className="mt-1 truncate text-xs text-muted-foreground">{sub}</div>}
      </CardContent>
    </Card>
  )
}

function ChartCard({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <Card className={className}>
      <CardHeader className="pb-1">
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  )
}

function ContainersTable({ hostname }: { hostname: string }) {
  const target: DeployTarget = { type: "agent_host", hostname, method: "docker" }
  const fetcher = useCallback(() => listServices({ type: "agent_host", hostname, method: "docker" }), [hostname])
  const { latest, loading } = useRollingSeries<ManagedService[]>(fetcher, { intervalMs: 5000 })
  const [busy, setBusy] = useState<string | null>(null)
  const list = latest ?? []

  async function act(name: string, action: "start" | "stop" | "restart") {
    setBusy(name)
    try {
      await serviceAction(target, name, action)
      toast.success(`${name} ${action}`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "실패")
    } finally {
      setBusy(null)
    }
  }
  async function rm(name: string) {
    setBusy(name)
    try {
      await removeService(target, name)
      toast.success(`${name} 제거`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "실패")
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="rounded-md border">
      <TooltipProvider delayDuration={300}>
        <Table className="text-sm">
          <TableHeader>
            <TableRow>
              <TableHead className="text-center text-sm">이름</TableHead>
              <TableHead className="text-center text-sm">종류</TableHead>
              <TableHead className="text-center text-sm">런타임</TableHead>
              <TableHead className="text-center text-sm">이미지</TableHead>
              <TableHead className="text-center text-sm">상태</TableHead>
              <TableHead className="text-center text-sm">CPU/MEM</TableHead>
              <TableHead className="text-center text-sm">복제</TableHead>
              <TableHead className="text-center text-sm">가동시간</TableHead>
              <TableHead className="text-center text-sm">워커</TableHead>
              <TableHead className="text-center text-sm">동작</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {list.length === 0 ? (
              <TableRow>
                <TableCell colSpan={10} className="text-center text-sm text-muted-foreground">
                  {loading ? "불러오는 중…" : "관리 컨테이너 없음"}
                </TableCell>
              </TableRow>
            ) : (
              list.map((c) => (
                <TableRow key={c.name}>
                  <TableCell className="font-mono text-sm">{c.name}</TableCell>
                  <TableCell className="text-center text-sm">{c.kind ?? "-"}</TableCell>
                  <TableCell className="text-center">
                    <Badge variant="outline" className="text-xs">{c.runtime}</Badge>
                  </TableCell>
                  <TableCell className="font-mono text-sm text-muted-foreground">{c.image ?? "-"}</TableCell>
                  <TableCell className="text-center">
                    <ServiceState s={c} />
                  </TableCell>
                  <TableCell className="text-center">
                    <ResourceCell s={c} />
                  </TableCell>
                  <TableCell className="text-center text-sm">
                    {c.ready_replicas}/{c.desired_replicas}
                  </TableCell>
                  <TableCell className="text-center text-sm text-muted-foreground">
                    {c.state === "running" ? formatUptime(c.started_at) : "-"}
                  </TableCell>
                  <TableCell className="text-center">
                    <WorkerCell s={c} />
                  </TableCell>
                  <TableCell className="text-center">
                    <div className="flex justify-center gap-1">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button variant="ghost" size="icon" disabled={busy === c.name} onClick={() => act(c.name, "restart")}>
                            <RotateCw className="size-4" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>재시작</TooltipContent>
                      </Tooltip>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button variant="ghost" size="icon" disabled={busy === c.name} onClick={() => act(c.name, "stop")}>
                            <Square className="size-4" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>중지</TooltipContent>
                      </Tooltip>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button variant="ghost" size="icon" disabled={busy === c.name} onClick={() => rm(c.name)}>
                            <Trash2 className="size-4 text-destructive" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>제거</TooltipContent>
                      </Tooltip>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TooltipProvider>
    </div>
  )
}

type Proc = { pid: number; username: string; cpu_percent: number; memory_percent: number; cmdline?: string; name?: string }

function ProcessesTable({ hostname }: { hostname: string }) {
  const fetcher = useCallback(() => fetchProcesses(hostname), [hostname])
  const { latest } = useRollingSeries<Record<string, unknown>>(fetcher, { intervalMs: 5000 })
  const procs = ((latest?.processes as Proc[]) ?? [])
    .slice()
    .sort((a, b) => (b.cpu_percent ?? 0) - (a.cpu_percent ?? 0))
    .slice(0, 30)

  return (
    <div className="max-h-[60vh] overflow-auto rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>PID</TableHead>
            <TableHead>USER</TableHead>
            <TableHead className="text-right">CPU%</TableHead>
            <TableHead className="text-right">MEM%</TableHead>
            <TableHead>COMMAND</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {procs.map((p) => (
            <TableRow key={p.pid}>
              <TableCell className="font-mono text-xs">{p.pid}</TableCell>
              <TableCell className="text-xs">{p.username}</TableCell>
              <TableCell className="text-right text-xs">{(p.cpu_percent ?? 0).toFixed(1)}</TableCell>
              <TableCell className="text-right text-xs">{(p.memory_percent ?? 0).toFixed(1)}</TableCell>
              <TableCell className="max-w-md truncate font-mono text-xs text-muted-foreground">
                {p.cmdline || p.name}
              </TableCell>
            </TableRow>
          ))}
          {procs.length === 0 && (
            <TableRow>
              <TableCell colSpan={5} className="text-center text-muted-foreground">
                불러오는 중…
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  )
}
