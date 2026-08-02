// 모델 레지스트리 — 학습 결과 모델 목록 + 수동 등록. 서빙·평가 연결.
"use client"

import { useCallback, useEffect, useState, type FormEvent } from "react"
import Link from "next/link"
import { Boxes, Plus } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { Badge } from "@workspace/ui/components/badge"
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard-header"
import { useAuth } from "@/features/auth"
import { listModels, registerModel } from "@/features/finetune/api"
import type { FtModel, FtTask } from "@/features/finetune/data/schema"

const STATUS: Record<string, string> = {
  registered: "border-muted-foreground/30 text-muted-foreground",
  serving: "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  archived: "border-muted-foreground/30 text-muted-foreground line-through",
}

export default function FtModelsPage() {
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser
  const [models, setModels] = useState<FtModel[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)

  const [name, setName] = useState("")
  const [task, setTask] = useState<FtTask>("embedding")
  const [baseModel, setBaseModel] = useState("")
  const [artifact, setArtifact] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setModels(await listModels())
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!name.trim()) {
      toast.error("이름을 입력하세요.")
      return
    }
    setSubmitting(true)
    try {
      await registerModel({
        name: name.trim(),
        task,
        base_model: baseModel.trim() || null,
        artifact_uri: artifact.trim() || null,
        format: task === "reranker" ? "sentence-transformers-cross-encoder" : "sentence-transformers",
      })
      toast.success("모델을 등록했습니다.")
      setOpen(false)
      setName("")
      setArtifact("")
      await refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "등록 실패")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <DashboardHeader title="모델" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <div className="flex items-center justify-between">
          <p className="max-w-3xl text-sm text-muted-foreground">
            학습 결과 모델을 등록해 서빙 서버에 연결하고, 홀드아웃 골든셋으로 기존 모델과 비교 평가합니다.
            보통 학습 작업이 성공하면 작업 상세에서 &lsquo;모델로 등록&rsquo;으로 승격합니다.
          </p>
          {canManage && (
            <Button onClick={() => setOpen(true)} size="sm">
              <Plus className="size-4" /> 모델 등록
            </Button>
          )}
        </div>

        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>이름</TableHead>
                <TableHead>대상</TableHead>
                <TableHead>베이스 모델</TableHead>
                <TableHead>서빙</TableHead>
                <TableHead>상태</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-sm text-muted-foreground">
                    불러오는 중…
                  </TableCell>
                </TableRow>
              ) : models.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-sm text-muted-foreground">
                    등록된 모델이 없습니다.
                  </TableCell>
                </TableRow>
              ) : (
                models.map((m) => (
                  <TableRow key={m.id}>
                    <TableCell>
                      <Link
                        href={`/dashboard/fine-tuning/models/${m.model_id}`}
                        className="flex items-center gap-2 font-medium text-foreground hover:underline"
                      >
                        <Boxes className="size-4 text-muted-foreground" />
                        {m.name}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="font-normal">
                        {m.task === "reranker" ? "리랭커" : "임베딩"}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{m.base_model ?? "—"}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{m.serving_url ?? "미연결"}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={`font-normal ${STATUS[m.status] ?? ""}`}>
                        {m.status}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <form onSubmit={onSubmit}>
            <DialogHeader>
              <DialogTitle>모델 등록</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-4 py-4">
              <div className="flex flex-col gap-2">
                <Label htmlFor="m-name">이름</Label>
                <Input id="m-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="예: tax-law-e5-v1" />
              </div>
              <div className="flex flex-col gap-2">
                <Label>대상</Label>
                <Select value={task} onValueChange={(v) => setTask(v as FtTask)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="embedding">임베딩 (bi-encoder)</SelectItem>
                    <SelectItem value="reranker">리랭커 (cross-encoder)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="m-base">베이스 모델</Label>
                <Input id="m-base" value={baseModel} onChange={(e) => setBaseModel(e.target.value)} placeholder="intfloat/multilingual-e5-large" />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="m-artifact">아티팩트 위치</Label>
                <Input id="m-artifact" value={artifact} onChange={(e) => setArtifact(e.target.value)} placeholder="s3://models/… 또는 로컬 경로" />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
                취소
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? "등록 중…" : "등록"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
