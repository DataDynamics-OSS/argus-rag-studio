// 학습 데이터셋 — 목록 + 생성. 외부 트레이너(extensions/retrieval-fine-tuning) 입력 소스.
"use client"

import { useCallback, useEffect, useState, type FormEvent } from "react"
import Link from "next/link"
import { Database, Plus } from "lucide-react"
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
import { createDataset, listDatasets } from "@/features/finetune/api"
import type { FtDataset, FtTask } from "@/features/finetune/data/schema"

function countLabel(counts: Record<string, number>): string {
  const t = counts.train ?? 0
  const v = counts.valid ?? 0
  const te = counts.test ?? 0
  return `train ${t} · valid ${v} · test ${te}`
}

export default function FtDatasetsPage() {
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser
  const [datasets, setDatasets] = useState<FtDataset[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [baseModel, setBaseModel] = useState("intfloat/multilingual-e5-large")
  const [task, setTask] = useState<FtTask>("embedding")
  const [submitting, setSubmitting] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setDatasets(await listDatasets())
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
      await createDataset({ name: name.trim(), base_model: baseModel.trim() || null, task })
      toast.success("학습 데이터셋을 생성했습니다.")
      setOpen(false)
      setName("")
      await refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "생성 실패")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <DashboardHeader title="학습 데이터셋" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <div className="flex items-center justify-between">
          <p className="max-w-3xl text-sm text-muted-foreground">
            파인튜닝에 쓸 (질의·정답·오답) 예시를 모아 관리하고, 외부 트레이너 입력 포맷(JSONL)으로
            내보냅니다. test 스플릿은 홀드아웃이라 내보내지 않고 평가에만 씁니다.
          </p>
          {canManage && (
            <Button onClick={() => setOpen(true)} size="sm">
              <Plus className="size-4" /> 데이터셋 생성
            </Button>
          )}
        </div>

        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>이름</TableHead>
                <TableHead>작업</TableHead>
                <TableHead>베이스 모델</TableHead>
                <TableHead>예시 수</TableHead>
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
              ) : datasets.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-sm text-muted-foreground">
                    데이터셋이 없습니다. 먼저 생성하세요.
                  </TableCell>
                </TableRow>
              ) : (
                datasets.map((d) => (
                  <TableRow key={d.id}>
                    <TableCell>
                      <Link
                        href={`/dashboard/fine-tuning/datasets/${d.dataset_id}`}
                        className="flex items-center gap-2 font-medium text-foreground hover:underline"
                      >
                        <Database className="size-4 text-muted-foreground" />
                        {d.name}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="font-normal">
                        {d.task === "reranker" ? "리랭커" : "임베딩"}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {d.base_model ?? "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{countLabel(d.counts)}</TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="font-normal">
                        {d.status}
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
              <DialogTitle>학습 데이터셋 생성</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-4 py-4">
              <div className="flex flex-col gap-2">
                <Label htmlFor="ft-name">이름</Label>
                <Input
                  id="ft-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="예: 세금·법률 학습셋 v1"
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label>학습 대상</Label>
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
                <Label htmlFor="ft-base-model">베이스 모델</Label>
                <Input
                  id="ft-base-model"
                  value={baseModel}
                  onChange={(e) => setBaseModel(e.target.value)}
                  placeholder="intfloat/multilingual-e5-large"
                />
                <p className="text-xs text-muted-foreground">
                  매니페스트에 기록되어 트레이너의 기본 베이스 모델이 됩니다.
                </p>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
                취소
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? "생성 중…" : "생성"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
