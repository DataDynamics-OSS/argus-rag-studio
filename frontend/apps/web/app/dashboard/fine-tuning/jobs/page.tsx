// 학습 작업 — 목록 + 생성. 실제 학습은 외부 트레이너가 수행하고 상태를 콜백으로 갱신한다.
"use client"

import { useCallback, useEffect, useState, type FormEvent } from "react"
import Link from "next/link"
import { Cpu, Plus } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
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
import { createJob, listDatasets, listJobs } from "@/features/finetune/api"
import type { FtDataset, FtJob, FtTask } from "@/features/finetune/data/schema"
import { JobStatusBadge } from "@/features/finetune/job-status"

export default function FtJobsPage() {
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser
  const [jobs, setJobs] = useState<FtJob[]>([])
  const [datasets, setDatasets] = useState<FtDataset[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)

  // 폼
  const [datasetId, setDatasetId] = useState("")
  const [task, setTask] = useState<FtTask>("embedding")
  const [baseModel, setBaseModel] = useState("")
  const [epochs, setEpochs] = useState("3")
  const [batchSize, setBatchSize] = useState("32")
  const [lr, setLr] = useState("0.00002")
  const [submitting, setSubmitting] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [js, ds] = await Promise.all([listJobs(), listDatasets()])
      setJobs(js)
      setDatasets(ds)
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
    if (!datasetId) {
      toast.error("데이터셋을 선택하세요.")
      return
    }
    setSubmitting(true)
    try {
      await createJob({
        dataset_id: Number(datasetId),
        task,
        base_model: baseModel.trim() || null,
        epochs: Number(epochs) || 3,
        batch_size: Number(batchSize) || 32,
        lr: Number(lr) || 2e-5,
      })
      toast.success("학습 작업을 생성했습니다(대기). 외부 트레이너가 실행 후 상태를 갱신합니다.")
      setOpen(false)
      setDatasetId("")
      await refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "생성 실패")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <DashboardHeader title="학습 작업" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <div className="flex items-center justify-between">
          <p className="max-w-3xl text-sm text-muted-foreground">
            학습 작업을 등록하면 외부 트레이너(extensions/retrieval-fine-tuning)가 데이터셋을 받아
            학습하고 진행 상태를 갱신합니다. Argus 는 작업을 기록·추적하고 결과를 평가에 연결합니다.
          </p>
          {canManage && (
            <Button onClick={() => setOpen(true)} size="sm">
              <Plus className="size-4" /> 작업 생성
            </Button>
          )}
        </div>

        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>작업</TableHead>
                <TableHead>데이터셋</TableHead>
                <TableHead>대상</TableHead>
                <TableHead>베이스 모델</TableHead>
                <TableHead className="w-20 text-center">진행</TableHead>
                <TableHead>상태</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-sm text-muted-foreground">
                    불러오는 중…
                  </TableCell>
                </TableRow>
              ) : jobs.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-sm text-muted-foreground">
                    학습 작업이 없습니다. &lsquo;작업 생성&rsquo;으로 시작하세요.
                  </TableCell>
                </TableRow>
              ) : (
                jobs.map((j) => (
                  <TableRow key={j.id}>
                    <TableCell>
                      <Link
                        href={`/dashboard/fine-tuning/jobs/${j.job_id}`}
                        className="flex items-center gap-2 font-medium text-foreground hover:underline"
                      >
                        <Cpu className="size-4 text-muted-foreground" />#{j.id}
                      </Link>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">{j.dataset_name ?? "—"}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className="font-normal">
                        {j.task === "reranker" ? "리랭커" : "임베딩"}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{j.base_model ?? "—"}</TableCell>
                    <TableCell className="text-center text-xs text-muted-foreground">{j.progress}%</TableCell>
                    <TableCell>
                      <JobStatusBadge status={j.status} />
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-3xl">
          <form onSubmit={onSubmit}>
            <DialogHeader>
              <DialogTitle>학습 작업 생성</DialogTitle>
            </DialogHeader>
            <table className="my-4 w-full table-fixed border-collapse text-sm text-black">
              <colgroup>
                <col className="w-[96px]" />
                <col />
                <col className="w-[44%]" />
              </colgroup>
              <tbody>
                <tr>
                  <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">데이터셋</th>
                  <td className="border px-2 py-1 align-middle">
                    <Select value={datasetId} onValueChange={setDatasetId}>
                      <SelectTrigger className="h-8 w-full">
                        <SelectValue placeholder="학습 데이터셋 선택" />
                      </SelectTrigger>
                      <SelectContent>
                        {datasets.map((d) => (
                          <SelectItem key={d.id} value={String(d.id)}>
                            {d.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </td>
                  <td className="border px-3 py-2 align-middle text-sm text-muted-foreground">
                    학습에 사용할 (질의·정답·오답) 트리플 데이터셋입니다.
                  </td>
                </tr>
                <tr>
                  <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">학습 대상</th>
                  <td className="border px-2 py-1 align-middle">
                    <Select value={task} onValueChange={(v) => setTask(v as FtTask)}>
                      <SelectTrigger className="h-8 w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="embedding">임베딩 (bi-encoder)</SelectItem>
                        <SelectItem value="reranker">리랭커 (cross-encoder)</SelectItem>
                      </SelectContent>
                    </Select>
                  </td>
                  <td className="border px-3 py-2 align-middle text-sm text-muted-foreground">
                    임베딩(bi-encoder)은 검색용 벡터 모델, 리랭커(cross-encoder)는 1차 검색 결과를 재정렬하는 모델입니다.
                  </td>
                </tr>
                <tr>
                  <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">베이스 모델</th>
                  <td className="border px-2 py-1 align-middle">
                    <Input
                      id="job-base"
                      className="h-8"
                      value={baseModel}
                      onChange={(e) => setBaseModel(e.target.value)}
                      placeholder="예: cross-encoder/ms-marco-MiniLM-L-6-v2"
                    />
                  </td>
                  <td className="border px-3 py-2 align-middle text-sm text-muted-foreground">
                    추가 학습의 출발점이 되는 기성 모델입니다. 비우면 데이터셋의 기본 모델을 사용합니다.
                  </td>
                </tr>
                <tr>
                  <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">epochs</th>
                  <td className="border px-2 py-1 align-middle">
                    <Input id="job-epochs" className="h-8" value={epochs} onChange={(e) => setEpochs(e.target.value)} inputMode="numeric" />
                  </td>
                  <td className="border px-3 py-2 align-middle text-sm text-muted-foreground">
                    전체 학습 데이터를 몇 번 반복 학습할지. 보통 1~5회이며, 너무 크면 과적합됩니다.
                  </td>
                </tr>
                <tr>
                  <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">batch</th>
                  <td className="border px-2 py-1 align-middle">
                    <Input id="job-batch" className="h-8" value={batchSize} onChange={(e) => setBatchSize(e.target.value)} inputMode="numeric" />
                  </td>
                  <td className="border px-3 py-2 align-middle text-sm text-muted-foreground">
                    한 번에 학습하는 샘플 수. 크면 빠르지만 GPU 메모리를 더 사용합니다.
                  </td>
                </tr>
                <tr>
                  <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">lr</th>
                  <td className="border px-2 py-1 align-middle">
                    <Input id="job-lr" className="h-8" value={lr} onChange={(e) => setLr(e.target.value)} />
                  </td>
                  <td className="border px-3 py-2 align-middle text-sm text-muted-foreground">
                    학습률(learning rate) — 가중치를 한 번에 얼마나 갱신할지. 보통 1e-5~5e-5, 크면 학습이 불안정합니다.
                  </td>
                </tr>
              </tbody>
            </table>
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
