// 평가 데이터셋 상세 — 항목 관리 + 평가 Run 실행/지표 + 항목별 결과.
"use client"

import { useCallback, useEffect, useState, type FormEvent } from "react"
import { useParams, useRouter } from "next/navigation"
import { ArrowLeft, Play, Plus, Trash2 } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Textarea } from "@workspace/ui/components/textarea"
import { Label } from "@workspace/ui/components/label"
import { Badge } from "@workspace/ui/components/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@workspace/ui/components/card"
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
  DialogDescription,
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
import { Checkbox } from "@workspace/ui/components/checkbox"
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard-header"
import { useAuth } from "@/features/auth"
import {
  addItem,
  createRun,
  deleteItem,
  getDataset,
  listItems,
  listResults,
  listRuns,
} from "@/features/evaluation/api"
import { SweepPanel } from "@/features/evaluation/components/sweep-panel"
import type { EvalDataset, EvalItem, EvalResult, EvalRun } from "@/features/evaluation/data/schema"
import { listPipelines } from "@/features/pipelines/api"
import type { Pipeline } from "@/features/pipelines/data/schema"

const fmt = (v: number | null) => (v == null ? "—" : v.toFixed(3))
const STATUS: Record<string, "secondary" | "outline" | "default" | "destructive"> = {
  succeeded: "secondary",
  queued: "outline",
  running: "default",
  failed: "destructive",
}

export default function EvalDatasetPage() {
  const params = useParams()
  const router = useRouter()
  // 외부 노출은 데이터셋 UUID. 내부 작업은 해석된 dataset.id(정수 PK)를 쓴다.
  const uuid = String(params.id)
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser

  const [dataset, setDataset] = useState<EvalDataset | null>(null)
  const [items, setItems] = useState<EvalItem[]>([])
  const [runs, setRuns] = useState<EvalRun[]>([])
  const [selectedRun, setSelectedRun] = useState<string | null>(null)
  const [results, setResults] = useState<EvalResult[]>([])

  // 항목 추가
  const [open, setOpen] = useState(false)
  const [question, setQuestion] = useState("")
  const [sources, setSources] = useState("")
  const [expected, setExpected] = useState("")
  const [deleteTarget, setDeleteTarget] = useState<EvalItem | null>(null)

  // Run 옵션
  const [mode, setMode] = useState("hybrid")
  const [rerank, setRerank] = useState(false)
  const [judge, setJudge] = useState(false)
  const [pipelineId, setPipelineId] = useState("") // "" = 사용 안 함(직접 설정)
  const [pipelines, setPipelines] = useState<Pipeline[]>([])
  const [running, setRunning] = useState(false)
  const usingPipeline = pipelineId !== ""
  const pipelineName = (id: number | null) => pipelines.find((p) => p.id === id)?.name

  const refresh = useCallback(async () => {
    try {
      const ds = await getDataset(uuid) // UUID 로 데이터셋 해석(내부 PK 포함)
      const [its, rns] = await Promise.all([listItems(ds.id), listRuns(ds.id)])
      setDataset(ds)
      setItems(its)
      setRuns(rns)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "조회 실패")
    }
  }, [uuid])

  useEffect(() => {
    if (uuid && uuid !== "undefined") refresh()
  }, [uuid, refresh])

  useEffect(() => {
    listPipelines().then(setPipelines).catch(() => {})
  }, [])

  // 진행 중 Run 이 있으면 주기적으로 갱신
  useEffect(() => {
    if (!dataset || !runs.some((r) => r.status === "queued" || r.status === "running")) return
    const t = setInterval(() => listRuns(dataset.id).then(setRuns).catch(() => {}), 1500)
    return () => clearInterval(t)
  }, [runs, dataset])

  async function handleAddItem(e: FormEvent) {
    e.preventDefault()
    if (!dataset) return
    try {
      await addItem(dataset.id, {
        question,
        expected_answer: expected || null,
        expected_sources: sources.split("\n").map((s) => s.trim()).filter(Boolean),
      })
      toast.success("항목을 추가했습니다.")
      setOpen(false)
      setQuestion("")
      setSources("")
      setExpected("")
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "추가 실패")
    }
  }

  async function confirmDeleteItem(e: FormEvent) {
    e.preventDefault()
    if (!deleteTarget) return
    try {
      await deleteItem(deleteTarget.item_id)
      toast.success("항목을 삭제했습니다.")
      setDeleteTarget(null)
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "삭제 실패")
    }
  }

  async function handleRun() {
    if (!dataset) return
    setRunning(true)
    try {
      await createRun(dataset.id, {
        mode, rerank, judge,
        ...(pipelineId ? { pipeline_id: Number(pipelineId) } : {}),
      })
      toast.success("평가를 시작했습니다.")
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "평가 실행 실패")
    } finally {
      setRunning(false)
    }
  }

  async function openResults(runId: string) {
    if (selectedRun === runId) {
      setSelectedRun(null)
      return
    }
    setSelectedRun(runId)
    try {
      setResults(await listResults(runId))
    } catch {
      setResults([])
    }
  }

  return (
    <>
      <DashboardHeader title={dataset?.name ?? "평가 데이터셋"} />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <Button variant="ghost" size="sm" className="self-start" onClick={() => router.push("/dashboard/evaluation")}>
          <ArrowLeft className="size-4" />
          목록으로
        </Button>

        {/* 평가 실행 */}
        {canManage && (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">평가 실행</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <div className="flex flex-wrap items-end gap-4">
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">파이프라인</Label>
                  <Select value={pipelineId || "__none__"} onValueChange={(v) => setPipelineId(v === "__none__" ? "" : v)}>
                    <SelectTrigger className="w-44">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__none__">사용 안 함(직접 설정)</SelectItem>
                      {pipelines.map((p) => (
                        <SelectItem key={p.id} value={String(p.id)}>
                          {p.name} (v{p.active_version})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">검색 방식</Label>
                  <Select value={mode} onValueChange={setMode} disabled={usingPipeline}>
                    <SelectTrigger className="w-32">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="hybrid">하이브리드</SelectItem>
                      <SelectItem value="vector">벡터</SelectItem>
                      <SelectItem value="lexical">렉시컬</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <label className="flex items-center gap-2 pb-2 text-sm">
                  <Checkbox checked={rerank} onCheckedChange={(v) => setRerank(!!v)} disabled={usingPipeline} />
                  리랭크
                </label>
                <label className="flex items-center gap-2 pb-2 text-sm">
                  <Checkbox checked={judge} onCheckedChange={(v) => setJudge(!!v)} />
                  LLM 판정(생성 지표)
                </label>
                <Button className="ml-auto" onClick={handleRun} disabled={running || items.length === 0}>
                  <Play className="size-4" />
                  평가 실행
                </Button>
              </div>
              {usingPipeline && (
                <p className="text-xs text-muted-foreground">
                  파이프라인 적용 — 검색 방식·리랭크는 선택한 파이프라인의 활성 버전 설정을 따릅니다(위 선택은 무시됨). 버전별 Hit Rate·MRR 비교에 사용하십시오.
                </p>
              )}
            </CardContent>
          </Card>
        )}

        {/* Run 목록 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">평가 Run</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>상태</TableHead>
                  <TableHead>방식</TableHead>
                  <TableHead className="text-center">진행</TableHead>
                  <TableHead className="text-center">Hit Rate</TableHead>
                  <TableHead className="text-center">MRR</TableHead>
                  <TableHead className="text-center">Faith.</TableHead>
                  <TableHead className="text-center">Rel.</TableHead>
                  <TableHead className="text-center">Corr.</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="py-6 text-center text-muted-foreground">
                      아직 평가 Run 이 없습니다.
                    </TableCell>
                  </TableRow>
                ) : (
                  runs.map((r) => (
                    <TableRow
                      key={r.run_id}
                      className="cursor-pointer"
                      onClick={() => openResults(r.run_id)}
                    >
                      <TableCell>
                        <Badge variant={STATUS[r.status] ?? "outline"}>{r.status}</Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {r.pipeline_id ? (
                          <Badge variant="secondary" className="mr-1 font-normal">
                            {pipelineName(r.pipeline_id) ?? `파이프라인 #${r.pipeline_id}`}
                          </Badge>
                        ) : null}
                        {r.mode}
                        {r.mode !== "lexical" && r.distance_metric ? ` · ${r.distance_metric}` : ""}
                        {r.rerank ? " +rerank" : ""}
                        {r.judge ? " +judge" : ""}
                      </TableCell>
                      <TableCell className="text-center text-muted-foreground">
                        {r.completed_items}/{r.total_items}
                      </TableCell>
                      <TableCell className="text-center font-medium">{fmt(r.hit_rate)}</TableCell>
                      <TableCell className="text-center font-medium">{fmt(r.mrr)}</TableCell>
                      <TableCell className="text-center text-muted-foreground">{fmt(r.faithfulness)}</TableCell>
                      <TableCell className="text-center text-muted-foreground">{fmt(r.answer_relevance)}</TableCell>
                      <TableCell className="text-center text-muted-foreground">{fmt(r.correctness)}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>

            {selectedRun && (
              <div className="mt-4 rounded-md border bg-muted/30 p-3">
                <p className="mb-2 text-xs font-medium text-muted-foreground">항목별 결과</p>
                <div className="flex flex-col gap-2">
                  {results.map((res) => (
                    <div key={res.id} className="rounded border bg-background p-2 text-xs">
                      <div className="flex items-center gap-2">
                        {res.hit != null && (
                          <Badge variant={res.hit ? "secondary" : "destructive"} className="h-4">
                            {res.hit ? "hit" : "miss"}
                          </Badge>
                        )}
                        <span className="font-medium">{res.question}</span>
                        <span className="ml-auto text-muted-foreground">rr {fmt(res.reciprocal_rank)}</span>
                      </div>
                      {res.answer && <p className="mt-1 text-muted-foreground">{res.answer}</p>}
                      <p className="mt-1 truncate text-muted-foreground">출처: {res.retrieved_docs.join(", ")}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* 항목 */}
        <div className="flex items-center justify-between">
          <h2 className="font-display text-sm font-semibold">항목 ({items.length})</h2>
          {canManage && (
            <Button size="sm" onClick={() => setOpen(true)}>
              <Plus className="size-4" />
              항목 추가
            </Button>
          )}
        </div>
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>질문</TableHead>
                <TableHead>기대 출처</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={3} className="py-6 text-center text-muted-foreground">
                    항목을 추가하세요. (질문 + 기대 출처/답변)
                  </TableCell>
                </TableRow>
              ) : (
                items.map((it) => (
                  <TableRow key={it.id}>
                    <TableCell className="font-medium">{it.question}</TableCell>
                    <TableCell className="text-muted-foreground">{it.expected_sources.join(", ") || "-"}</TableCell>
                    <TableCell className="text-center">
                      {canManage && (
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          onClick={() => setDeleteTarget(it)}
                          title="삭제"
                        >
                          <Trash2 className="size-3.5" />
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>

        {dataset && (
          <SweepPanel datasetId={dataset.id} defaultCollectionId={dataset.collection_id ?? null} />
        )}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>평가 항목 추가</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleAddItem} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="q">질문</Label>
              <Textarea id="q" value={question} onChange={(e) => setQuestion(e.target.value)} required autoFocus />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="src">기대 출처 (문서명 부분문자열, 한 줄에 하나)</Label>
              <Textarea id="src" value={sources} onChange={(e) => setSources(e.target.value)} placeholder="정관" />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="exp">기대 답변 (선택, LLM 판정 시 correctness 채점)</Label>
              <Textarea id="exp" value={expected} onChange={(e) => setExpected(e.target.value)} />
            </div>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
                취소
              </Button>
              <Button type="submit">추가</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 항목 삭제 확인 — Enter 로 삭제(폼 submit) */}
      <Dialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <DialogContent>
          <form onSubmit={confirmDeleteItem}>
            <DialogHeader>
              <DialogTitle>평가 항목 삭제</DialogTitle>
              <DialogDescription>
                이 항목을 삭제할까요? 이 작업은 되돌릴 수 없습니다.
              </DialogDescription>
            </DialogHeader>
            {deleteTarget && (
              <p className="my-3 rounded-md border bg-muted/40 p-2 text-sm">{deleteTarget.question}</p>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDeleteTarget(null)}>
                취소
              </Button>
              <Button type="submit" variant="destructive" autoFocus>
                삭제
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
