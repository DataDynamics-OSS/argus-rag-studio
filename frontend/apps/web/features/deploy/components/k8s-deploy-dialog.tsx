"use client"

import { useCallback, useEffect, useState } from "react"
import { Loader2, Plus, RefreshCw, Rocket, RotateCw, Square, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
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
  deploy,
  listServices,
  removeService,
  scaleService,
  serviceAction,
  type Cluster,
  type DeployTarget,
  type ManagedService,
  type ServiceKind,
} from "../api"
import { PrivilegeBadge } from "./privilege-badge"

const KINDS: { value: ServiceKind; label: string; gpu: boolean; scalable: boolean }[] = [
  { value: "embedding", label: "임베딩 서버", gpu: true, scalable: false },
  { value: "reranker", label: "리랭커 서버", gpu: true, scalable: false },
  { value: "detection", label: "검출 서버", gpu: true, scalable: false },
  { value: "hwp_render", label: "HWP 렌더 서버", gpu: false, scalable: false },
  { value: "worker", label: "워커", gpu: false, scalable: true },
]

export function K8sDeployDialog({
  open,
  onOpenChange,
  cluster,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  cluster: Cluster
}) {
  const [namespace, setNamespace] = useState(cluster.default_namespace)
  const [kind, setKind] = useState<ServiceKind>("embedding")
  const [replicas, setReplicas] = useState("1")
  const [gpu, setGpu] = useState(true)
  const [version, setVersion] = useState("")
  const [services, setServices] = useState<ManagedService[]>([])
  const [loading, setLoading] = useState(false)
  const [deploying, setDeploying] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)

  const meta = KINDS.find((k) => k.value === kind) ?? KINDS[0]!
  const target: DeployTarget = { type: "k8s", cluster_id: cluster.cluster_id, namespace }

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setServices(await listServices({ type: "k8s", cluster_id: cluster.cluster_id, namespace }))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [cluster.cluster_id, namespace])

  useEffect(() => {
    if (open) void refresh()
  }, [open, refresh])

  async function handleDeploy() {
    setDeploying(true)
    try {
      const r = await deploy(
        {
          kind,
          replicas: meta.scalable ? Number(replicas) || 1 : 1,
          gpu: meta.gpu && gpu,
          version: version.trim() || undefined,
        },
        target
      )
      const applied = Object.keys(r.applied_settings)
      toast.success(
        `${r.service.name} 배포됨${applied.length ? ` · 설정 주입: ${applied.join(", ")}` : ""}`
      )
      await refresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "배포 실패")
    } finally {
      setDeploying(false)
    }
  }

  async function act(name: string, fn: () => Promise<unknown>, label: string) {
    setBusy(name)
    try {
      await fn()
      toast.success(`${name} ${label}`)
      await refresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "실패")
    } finally {
      setBusy(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            클러스터 배포 — {cluster.name} <PrivilegeBadge runtime="k8s" />
          </DialogTitle>
          <DialogDescription>
            {cluster.api_server} · arch {cluster.default_arch}
          </DialogDescription>
        </DialogHeader>

        {/* 배포 폼 */}
        <div className="grid grid-cols-2 gap-3 rounded-md border p-3">
          <div className="grid gap-1">
            <Label className="text-xs">네임스페이스</Label>
            <Input value={namespace} onChange={(e) => setNamespace(e.target.value)} className="text-xs" />
          </div>
          <div className="grid gap-1">
            <Label className="text-xs">종류(kind)</Label>
            <Select value={kind} onValueChange={(v) => setKind(v as ServiceKind)}>
              <SelectTrigger className="text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {KINDS.map((k) => (
                  <SelectItem key={k.value} value={k.value}>
                    {k.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {meta.scalable && (
            <div className="grid gap-1">
              <Label className="text-xs">replicas</Label>
              <Input
                type="number"
                min={1}
                max={32}
                value={replicas}
                onChange={(e) => setReplicas(e.target.value)}
                className="text-xs"
              />
            </div>
          )}
          <div className="grid gap-1">
            <Label className="text-xs">버전(태그, 선택)</Label>
            <Input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="latest" className="text-xs" />
          </div>
          {meta.gpu && (
            <div className="flex items-center gap-2">
              <Switch checked={gpu} onCheckedChange={setGpu} id="k8s-gpu" />
              <Label htmlFor="k8s-gpu" className="text-xs">
                GPU (nvidia.com/gpu)
              </Label>
            </div>
          )}
          <div className="col-span-2 flex justify-end">
            <Button size="sm" onClick={handleDeploy} disabled={deploying}>
              {deploying ? <Loader2 className="size-4 animate-spin" /> : <Rocket className="size-4" />}
              배포
            </Button>
          </div>
        </div>

        {/* 배포된 서비스 */}
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">배포된 서비스</span>
          <Button variant="ghost" size="sm" onClick={() => void refresh()} disabled={loading}>
            <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
        <div className="max-h-[40vh] overflow-auto rounded-md border">
          <TooltipProvider delayDuration={300}>
          <Table className="text-sm">
            <TableHeader>
              <TableRow>
                <TableHead className="text-sm">이름</TableHead>
                <TableHead className="text-sm">kind</TableHead>
                <TableHead className="text-center text-sm">상태</TableHead>
                <TableHead className="text-center text-sm">ready/desired</TableHead>
                <TableHead className="text-right text-sm">동작</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {services.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-sm text-muted-foreground">
                    배포된 서비스 없음
                  </TableCell>
                </TableRow>
              ) : (
                services.map((s) => (
                  <TableRow key={s.name}>
                    <TableCell className="font-mono text-sm">{s.name}</TableCell>
                    <TableCell className="text-sm">{s.kind}</TableCell>
                    <TableCell className="text-center">
                      <Badge variant={s.state === "running" ? "default" : "secondary"}>{s.state}</Badge>
                    </TableCell>
                    <TableCell className="text-center text-sm">
                      {s.ready_replicas}/{s.desired_replicas}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button variant="ghost" size="icon" disabled={busy === s.name}
                              onClick={() => act(s.name, () => serviceAction(target, s.name, "restart"), "재시작")}>
                              <RotateCw className="size-4" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>재시작</TooltipContent>
                        </Tooltip>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button variant="ghost" size="icon" disabled={busy === s.name}
                              onClick={() => act(s.name, () => serviceAction(target, s.name, "stop"), "중지")}>
                              <Square className="size-4" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>중지</TooltipContent>
                        </Tooltip>
                        {s.kind === "worker" && (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button variant="ghost" size="icon" disabled={busy === s.name}
                                onClick={() => act(s.name, () => scaleService(target, s.name, s.desired_replicas + 1), "스케일+1")}>
                                <Plus className="size-4" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>스케일 +1</TooltipContent>
                          </Tooltip>
                        )}
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button variant="ghost" size="icon" disabled={busy === s.name}
                              onClick={() => act(s.name, () => removeService(target, s.name), "제거")}>
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
      </DialogContent>
    </Dialog>
  )
}
