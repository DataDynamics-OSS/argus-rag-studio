// 학습 데이터셋 상세 — 예시 목록 + 추가 + JSONL 내보내기.
"use client"

import { useCallback, useEffect, useState, type FormEvent } from "react"
import { useParams } from "next/navigation"
import Link from "next/link"
import { ArrowLeft, Download, Plus, Sparkles, Trash2, Wand2 } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import { Textarea } from "@workspace/ui/components/textarea"
import { Badge } from "@workspace/ui/components/badge"
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
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard-header"
import { useAuth } from "@/features/auth"
import {
  addExample,
  buildFromEval,
  deleteExample,
  downloadExport,
  getDataset,
  listExamples,
  mineNegatives,
} from "@/features/finetune/api"
import type { FtDataset, FtExample, FtSplit } from "@/features/finetune/data/schema"
import { listDatasets as listEvalDatasets } from "@/features/evaluation/api"
import type { EvalDataset } from "@/features/evaluation/data/schema"

const SPLIT_LABEL: Record<string, string> = { train: "train", valid: "valid", test: "test" }

export default function FtDatasetDetailPage() {
  const params = useParams<{ id: string }>()
  // 외부 노출은 데이터셋 UUID. 내부 작업은 해석된 dataset.id(정수 PK)를 쓴다.
  const uuid = String(params.id)
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser

  const [dataset, setDataset] = useState<FtDataset | null>(null)
  const [examples, setExamples] = useState<FtExample[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)

  // 폼 상태
  const [query, setQuery] = useState("")
  const [positive, setPositive] = useState("")
  const [negatives, setNegatives] = useState("") // 줄바꿈 구분
  const [split, setSplit] = useState<FtSplit>("train")
  const [submitting, setSubmitting] = useState(false)

  // 빌더(골든셋) 상태
  const [buildOpen, setBuildOpen] = useState(false)
  const [evalDatasets, setEvalDatasets] = useState<EvalDataset[]>([])
  const [evalId, setEvalId] = useState("")
  const [buildSplit, setBuildSplit] = useState<FtSplit>("train")
  const [building, setBuilding] = useState(false)
  const [mining, setMining] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const ds = await getDataset(uuid) // UUID 로 데이터셋 해석(내부 PK 포함)
      const ex = await listExamples(ds.id)
      setDataset(ds)
      setExamples(ex)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [uuid])

  useEffect(() => {
    if (uuid && uuid !== "undefined") refresh()
  }, [uuid, refresh])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!query.trim() || !positive.trim()) {
      toast.error("질의와 정답을 입력하세요.")
      return
    }
    if (!dataset) return
    setSubmitting(true)
    try {
      await addExample(dataset.id, {
        query: query.trim(),
        positive: positive.trim(),
        negatives: negatives.split("\n").map((s) => s.trim()).filter(Boolean),
        split,
      })
      toast.success("예시를 추가했습니다.")
      setQuery("")
      setPositive("")
      setNegatives("")
      setOpen(false)
      await refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "추가 실패")
    } finally {
      setSubmitting(false)
    }
  }

  async function onDelete(exampleUuid: string) {
    try {
      await deleteExample(exampleUuid)
      setExamples((prev) => prev.filter((x) => x.example_id !== exampleUuid))
      toast.success("예시를 삭제했습니다.")
      // counts 갱신
      getDataset(uuid).then(setDataset).catch(() => {})
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "삭제 실패")
    }
  }

  async function onExport(s: "train" | "valid") {
    if (!dataset) return
    try {
      await downloadExport(dataset.id, s)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "내보내기 실패")
    }
  }

  async function openBuild() {
    try {
      const eds = await listEvalDatasets()
      setEvalDatasets(eds)
      setEvalId("")
      setBuildOpen(true)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "골든셋 조회 실패")
    }
  }

  async function onBuild() {
    if (!evalId) {
      toast.error("골든셋을 선택하세요.")
      return
    }
    if (!dataset) return
    setBuilding(true)
    try {
      const r = await buildFromEval(dataset.id, { eval_dataset_id: Number(evalId), split: buildSplit, top_k: 10, max_negatives: 3 })
      toast.success(r.message ?? `${r.built}건 생성`)
      setBuildOpen(false)
      await refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "빌드 실패")
    } finally {
      setBuilding(false)
    }
  }

  async function onMine() {
    if (!dataset) return
    setMining(true)
    try {
      const r = await mineNegatives(dataset.id, { per_example: 3, top_k: 10, only_missing: true })
      toast.success(r.message ?? `${r.updated}개 보강`)
      await refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "마이닝 실패")
    } finally {
      setMining(false)
    }
  }

  const counts = dataset?.counts ?? {}

  return (
    <>
      <DashboardHeader title={dataset?.name ?? "학습 데이터셋"} />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Link
            href="/dashboard/fine-tuning/datasets"
            className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-4" /> 데이터셋 목록
          </Link>
          <div className="flex flex-wrap items-center gap-2">
            {canManage && (
              <>
                <Button variant="outline" size="sm" onClick={openBuild}>
                  <Wand2 className="size-4" /> 골든셋에서 빌드
                </Button>
                <Button variant="outline" size="sm" onClick={onMine} disabled={mining}>
                  <Sparkles className="size-4" /> {mining ? "마이닝 중…" : "하드네거티브 마이닝"}
                </Button>
              </>
            )}
            <Button variant="outline" size="sm" onClick={() => onExport("train")} disabled={!counts.train}>
              <Download className="size-4" /> train.jsonl
            </Button>
            <Button variant="outline" size="sm" onClick={() => onExport("valid")} disabled={!counts.valid}>
              <Download className="size-4" /> valid.jsonl
            </Button>
            {canManage && (
              <Button size="sm" onClick={() => setOpen(true)}>
                <Plus className="size-4" /> 예시 추가
              </Button>
            )}
          </div>
        </div>

        {dataset && (
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="outline" className="font-normal">
              {dataset.task === "reranker" ? "리랭커" : "임베딩"}
            </Badge>
            <span className="font-mono">{dataset.base_model ?? "베이스 모델 미지정"}</span>
            <span>· train {counts.train ?? 0} · valid {counts.valid ?? 0} · test {counts.test ?? 0}</span>
            <span>· prompt {dataset.prompt_format}</span>
            <span className="text-amber-600 dark:text-amber-400">· test 는 홀드아웃(내보내기 제외)</span>
          </div>
        )}

        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">split</TableHead>
                <TableHead>질의</TableHead>
                <TableHead>정답(positive)</TableHead>
                <TableHead className="w-16 text-center">오답</TableHead>
                {canManage && <TableHead className="w-10" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={canManage ? 5 : 4} className="text-center text-sm text-muted-foreground">
                    불러오는 중…
                  </TableCell>
                </TableRow>
              ) : examples.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={canManage ? 5 : 4} className="text-center text-sm text-muted-foreground">
                    예시가 없습니다. &lsquo;예시 추가&rsquo;로 (질의·정답·오답)을 등록하세요.
                  </TableCell>
                </TableRow>
              ) : (
                examples.map((ex) => (
                  <TableRow key={ex.id}>
                    <TableCell>
                      <Badge variant="secondary" className="font-normal">
                        {SPLIT_LABEL[ex.split] ?? ex.split}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-[220px] truncate text-sm" title={ex.query}>
                      {ex.query}
                    </TableCell>
                    <TableCell className="max-w-[320px] truncate text-sm text-muted-foreground" title={ex.positive}>
                      {ex.positive}
                    </TableCell>
                    <TableCell className="text-center text-xs text-muted-foreground">
                      {ex.negatives.length}
                    </TableCell>
                    {canManage && (
                      <TableCell>
                        <Button variant="ghost" size="icon" className="size-7" onClick={() => onDelete(ex.example_id)}>
                          <Trash2 className="size-3.5 text-muted-foreground" />
                        </Button>
                      </TableCell>
                    )}
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
              <DialogTitle>학습 예시 추가</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-4 py-4">
              <div className="flex flex-col gap-2">
                <Label htmlFor="ex-query">질의 (anchor)</Label>
                <Textarea
                  id="ex-query"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  rows={2}
                  placeholder="예: 1세대 1주택 양도세 비과세 요건이 뭔가요?"
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="ex-positive">정답 (positive)</Label>
                <Textarea
                  id="ex-positive"
                  value={positive}
                  onChange={(e) => setPositive(e.target.value)}
                  rows={3}
                  placeholder="정답이 담긴 문서 조각"
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="ex-negatives">오답 (hard negatives) — 한 줄에 하나</Label>
                <Textarea
                  id="ex-negatives"
                  value={negatives}
                  onChange={(e) => setNegatives(e.target.value)}
                  rows={3}
                  placeholder={"주제는 비슷하나 정답이 아닌 조각\n여러 개면 줄바꿈으로 구분"}
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label>split</Label>
                <Select value={split} onValueChange={(v) => setSplit(v as FtSplit)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="train">train (학습)</SelectItem>
                    <SelectItem value="valid">valid (검증)</SelectItem>
                    <SelectItem value="test">test (홀드아웃 — 내보내기 제외)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
                취소
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? "추가 중…" : "추가"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 골든셋에서 빌드 */}
      <Dialog open={buildOpen} onOpenChange={setBuildOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>골든셋에서 빌드</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-4 py-4">
            <p className="text-xs text-muted-foreground">
              평가 골든셋(질문+기대출처)을 골라, 연결된 컬렉션에서 검색해 (질의·정답·오답) 트리플을 생성합니다.
              골든셋에 컬렉션이 연결되어 있어야 합니다.
            </p>
            <div className="flex flex-col gap-2">
              <Label>평가 골든셋</Label>
              <Select value={evalId} onValueChange={setEvalId}>
                <SelectTrigger>
                  <SelectValue placeholder="골든셋 선택" />
                </SelectTrigger>
                <SelectContent>
                  {evalDatasets.map((d) => (
                    <SelectItem key={d.id} value={String(d.id)}>
                      {d.name}
                      {d.collection_id ? "" : " (컬렉션 미연결)"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-2">
              <Label>split</Label>
              <Select value={buildSplit} onValueChange={(v) => setBuildSplit(v as FtSplit)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="train">train</SelectItem>
                  <SelectItem value="valid">valid</SelectItem>
                  <SelectItem value="test">test</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setBuildOpen(false)}>
              취소
            </Button>
            <Button type="button" onClick={onBuild} disabled={building}>
              {building ? "빌드 중…" : "빌드"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
