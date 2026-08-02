"use client"

import { useCallback, useEffect, useState } from "react"
import { Plus, RefreshCw, Rocket, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"

import {
  deleteCluster,
  listClusters,
  upsertCluster,
  type Cluster,
  type ClusterIn,
} from "../api"
import { K8sDeployDialog } from "./k8s-deploy-dialog"
import { PrivilegeBadge } from "./privilege-badge"

const EMPTY: ClusterIn = {
  cluster_id: "",
  name: "",
  api_server: "",
  token: "",
  ca_cert: "",
  verify_ssl: true,
  default_namespace: "default",
  default_arch: "amd64",
}

export function ClustersView() {
  const [clusters, setClusters] = useState<Cluster[]>([])
  const [loading, setLoading] = useState(false)
  const [registerOpen, setRegisterOpen] = useState(false)
  const [form, setForm] = useState<ClusterIn>(EMPTY)
  const [saving, setSaving] = useState(false)
  const [deployFor, setDeployFor] = useState<Cluster | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setClusters(await listClusters())
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function handleSave() {
    if (!form.cluster_id.trim() || !form.api_server.trim()) {
      toast.error("cluster_id 와 api_server 는 필수입니다.")
      return
    }
    setSaving(true)
    try {
      await upsertCluster({ ...form, name: form.name || form.cluster_id })
      toast.success("클러스터를 등록했습니다.")
      setRegisterOpen(false)
      setForm(EMPTY)
      await refresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "등록 실패")
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteCluster(id)
      toast.success(`${id} 삭제됨`)
      await refresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "삭제 실패")
    }
  }

  const set = (k: keyof ClusterIn) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold">Kubernetes 클러스터</h2>
          <PrivilegeBadge runtime="k8s" />
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={loading}>
            <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} /> 새로고침
          </Button>
          <Button size="sm" onClick={() => setRegisterOpen(true)}>
            <Plus className="size-4" /> 클러스터 등록
          </Button>
        </div>
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead>이름</TableHead>
              <TableHead>API 서버</TableHead>
              <TableHead className="text-center">arch</TableHead>
              <TableHead className="text-center">네임스페이스</TableHead>
              <TableHead className="text-center">토큰</TableHead>
              <TableHead className="text-right">동작</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {clusters.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground">
                  등록된 클러스터가 없습니다.
                </TableCell>
              </TableRow>
            ) : (
              clusters.map((c) => (
                <TableRow key={c.cluster_id}>
                  <TableCell className="font-mono text-xs">{c.cluster_id}</TableCell>
                  <TableCell>{c.name}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{c.api_server}</TableCell>
                  <TableCell className="text-center">
                    <Badge variant="outline">{c.default_arch}</Badge>
                  </TableCell>
                  <TableCell className="text-center text-xs">{c.default_namespace}</TableCell>
                  <TableCell className="text-center">
                    {c.has_token ? <Badge variant="secondary">설정됨</Badge> : <span className="text-xs text-muted-foreground">-</span>}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" size="sm" onClick={() => setDeployFor(c)}>
                        <Rocket className="size-4" /> 배포
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => handleDelete(c.cluster_id)}>
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* 등록 다이얼로그 */}
      <Dialog open={registerOpen} onOpenChange={setRegisterOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Kubernetes 클러스터 등록</DialogTitle>
            <DialogDescription>ServiceAccount bearer 토큰 + API 서버로 접속합니다(네임스페이스 RBAC).</DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <div className="grid grid-cols-2 gap-2">
              <div className="grid gap-1">
                <Label className="text-xs">cluster_id *</Label>
                <Input value={form.cluster_id} onChange={set("cluster_id")} placeholder="prod-a" />
              </div>
              <div className="grid gap-1">
                <Label className="text-xs">이름</Label>
                <Input value={form.name} onChange={set("name")} placeholder="Prod A" />
              </div>
            </div>
            <div className="grid gap-1">
              <Label className="text-xs">API 서버 *</Label>
              <Input value={form.api_server} onChange={set("api_server")} placeholder="https://192.0.2.60:6443" className="font-mono text-xs" />
            </div>
            <div className="grid gap-1">
              <Label className="text-xs">SA 토큰</Label>
              <Input value={form.token} onChange={set("token")} type="password" placeholder="eyJ..." className="font-mono text-xs" />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="grid gap-1">
                <Label className="text-xs">기본 네임스페이스</Label>
                <Input value={form.default_namespace} onChange={set("default_namespace")} />
              </div>
              <div className="grid gap-1">
                <Label className="text-xs">노드풀 arch</Label>
                <Select value={form.default_arch} onValueChange={(v) => setForm((f) => ({ ...f, default_arch: v }))}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="amd64">amd64</SelectItem>
                    <SelectItem value="arm64">arm64 (DGX/Blackwell)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRegisterOpen(false)}>
              취소
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? "저장 중…" : "등록"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {deployFor && (
        <K8sDeployDialog open={!!deployFor} onOpenChange={(o) => !o && setDeployFor(null)} cluster={deployFor} />
      )}
    </div>
  )
}
