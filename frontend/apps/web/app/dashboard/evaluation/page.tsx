// 평가 — 골든 데이터셋 목록/생성 탭 + 사용법 탭. 사용법은 RAG 개요와 같은 안내 블록을 공유한다.
"use client"

import { useCallback, useEffect, useState, type FormEvent } from "react"
import Link from "next/link"
import { AlertTriangle, BarChart3, CheckCircle2, ClipboardCheck, Database, Plus } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
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
import { TabsContent, TabsList, TabsTrigger } from "@workspace/ui/components/tabs"
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard-header"
import { DataTablePagination, useClientPagination } from "@/components/data-table"
import { Bullets, Callout, Heading, Sub, TabShell } from "@/components/doc-blocks"
import { useAuth } from "@/features/auth"
import { createDataset, listAllRuns, listDatasets } from "@/features/evaluation/api"
import type { EvalDataset, EvalRun } from "@/features/evaluation/data/schema"
import { listCollections } from "@/features/collections/api"
import type { Collection } from "@/features/collections/data/schema"
import { relativeTime } from "@/lib/format"
import { UrlTabs } from "@/components/url-tabs"

const fmtMetric = (v: number | null) => (v == null ? "—" : v.toFixed(3))
const RUN_STATUS: Record<string, { label: string; variant: "secondary" | "outline" | "default" | "destructive" }> = {
  succeeded: { label: "완료", variant: "secondary" },
  running: { label: "진행 중", variant: "default" },
  queued: { label: "대기", variant: "outline" },
  failed: { label: "실패", variant: "destructive" },
}

export default function EvaluationPage() {
  return (
    <>
      <DashboardHeader title="평가" />
      <div className="flex flex-1 flex-col p-4">
        <UrlTabs defaultValue="list" className="gap-4">
          <TabsList>
            <TabsTrigger value="list">목록</TabsTrigger>
            <TabsTrigger value="guide">사용법</TabsTrigger>
          </TabsList>
          <TabsContent value="list">
            <EvaluationListTab />
          </TabsContent>
          <TabsContent value="guide">
            <EvaluationUsageTab />
          </TabsContent>
        </UrlTabs>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// 목록 / 생성
// ---------------------------------------------------------------------------

function EvaluationListTab() {
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser
  const [datasets, setDatasets] = useState<EvalDataset[]>([])
  const [collections, setCollections] = useState<Collection[]>([])
  const [runs, setRuns] = useState<EvalRun[]>([]) // 최신순 전역 Run — 데이터셋별 최근 실행/점수 표시용
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [collectionId, setCollectionId] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [ds, cols, rns] = await Promise.all([
        listDatasets(),
        listCollections({ page_size: 100 }),
        listAllRuns().catch(() => [] as EvalRun[]), // 권한/실패해도 목록 자체는 표시
      ])
      setDatasets(ds)
      setCollections(cols.items)
      setRuns(rns)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [])

  // runs 는 최신순 — 데이터셋(내부 id)별 첫 매치가 최신.
  const latestRun = (dsId: number) => runs.find((r) => r.dataset_id === dsId)
  const latestScored = (dsId: number) =>
    runs.find((r) => r.dataset_id === dsId && r.status === "succeeded" && r.hit_rate != null)

  useEffect(() => {
    refresh()
  }, [refresh])

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    try {
      await createDataset({ name, collection_id: collectionId ? Number(collectionId) : null })
      toast.success("데이터셋을 생성했습니다.")
      setOpen(false)
      setName("")
      setCollectionId("")
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "생성 실패")
    } finally {
      setSubmitting(false)
    }
  }

  const { table, pageItems } = useClientPagination(datasets, 30)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          골든 데이터셋으로 RAG 파이프라인을 평가하고 지표를 추적합니다.
        </p>
        {canManage && (
          <Button size="sm" onClick={() => setOpen(true)}>
            <Plus className="size-4" />
            데이터셋 생성
          </Button>
        )}
      </div>

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>이름</TableHead>
              <TableHead className="text-center">항목 수</TableHead>
              <TableHead className="text-center">기본 컬렉션</TableHead>
              <TableHead className="text-center">최근 Hit / MRR</TableHead>
              <TableHead className="text-right">최근 실행</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                  불러오는 중...
                </TableCell>
              </TableRow>
            ) : datasets.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                  <ClipboardCheck className="mx-auto mb-2 size-6 opacity-50" />
                  평가 데이터셋이 없습니다.
                </TableCell>
              </TableRow>
            ) : (
              pageItems.map((d) => {
                const last = latestRun(d.id)
                const scored = latestScored(d.id)
                const st = last ? RUN_STATUS[last.status] : null
                return (
                  <TableRow key={d.id}>
                    <TableCell>
                      <Link
                        href={`/dashboard/evaluation/${d.dataset_id}`}
                        className="font-medium hover:underline"
                      >
                        {d.name}
                      </Link>
                      {d.description && (
                        <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground" title={d.description}>
                          {d.description}
                        </p>
                      )}
                    </TableCell>
                    <TableCell className="text-center">{d.item_count}</TableCell>
                    <TableCell className="text-center">
                      {collections.find((c) => c.id === d.collection_id)?.name ?? "-"}
                    </TableCell>
                    <TableCell className="text-center">
                      {scored ? (
                        <span className="font-medium tabular-nums">
                          {fmtMetric(scored.hit_rate)} / {fmtMetric(scored.mrr)}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {last && st ? (
                        <span className="inline-flex items-center gap-1.5">
                          <Badge variant={st.variant} className="font-normal">{st.label}</Badge>
                          <span className="text-xs text-muted-foreground">
                            {relativeTime(last.finished_at ?? last.created_at)}
                          </span>
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground">미실행</span>
                      )}
                    </TableCell>
                  </TableRow>
                )
              })
            )}
          </TableBody>
        </Table>
      </div>

      {datasets.length > 0 && <DataTablePagination table={table} />}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>평가 데이터셋 생성</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreate} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="ds-name">이름</Label>
              <Input id="ds-name" value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
            </div>
            <div className="flex flex-col gap-2">
              <Label>기본 평가 대상 지식베이스</Label>
              <Select value={collectionId} onValueChange={setCollectionId}>
                <SelectTrigger>
                  <SelectValue placeholder="컬렉션 선택 (선택)" />
                </SelectTrigger>
                <SelectContent>
                  {collections.map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
                취소
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? "생성 중..." : "생성"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 사용법
// ---------------------------------------------------------------------------

const METRIC_ROWS: { metric: string; meaning: string }[] = [
  { metric: "Hit Rate", meaning: "기대 출처 문서가 상위 결과(top-k) 안에 들어온 비율입니다. \"맞는 문서를 가져오기는 하나?\"" },
  { metric: "MRR", meaning: "기대 문서가 몇 번째로 나왔는지의 평균입니다(1등=1.0, 2등=0.5…). \"얼마나 위에 올리나?\"" },
  { metric: "Faithfulness", meaning: "(judge) 답변이 근거에 충실한지, 없는 말을 지어내지 않는지 0~1로 채점합니다." },
  { metric: "Answer Relevance", meaning: "(judge) 답변이 질문에 실제로 답하는지 0~1로 채점합니다." },
  { metric: "Correctness", meaning: "(judge) 답변이 기대 정답과 일치하는지 0~1로 채점합니다." },
]

function EvaluationUsageTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={ClipboardCheck}>평가 — 품질을 숫자로 확인</Heading>
        <p className="text-muted-foreground">
          평가는 정답을 미리 정해 둔 <span className="font-medium text-foreground">질문 모음(골든셋)</span>으로 검색·답변이
          실제로 잘 맞는지 <span className="font-medium text-foreground">점수로 측정</span>하는 곳입니다. &ldquo;좋아진 것
          같다&rdquo;가 아니라, 설정을 바꿨을 때 숫자가 올랐는지 비교할 수 있습니다. <span className="font-medium text-foreground">생성·수정은
          관리자</span>만 가능합니다.
        </p>
      </section>

      <section>
        <Sub icon={Database}>① 데이터셋 만들기</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">데이터셋 생성</span> 버튼으로 골든셋을 만듭니다. <span className="font-medium text-foreground">기본 평가 대상 지식베이스</span>를 지정해 두면 실행 시 매번 고르지 않아도 됩니다(선택).</>,
            <>목록에서 데이터셋 이름을 누르면 상세 화면으로 이동해 <span className="font-medium text-foreground">항목(질문)을 추가</span>하고 평가를 실행합니다.</>,
            <>피드백 화면의 👎 사례를 <span className="font-medium text-foreground">승격</span>하면 곧바로 이 데이터셋의 항목이 됩니다.</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={ClipboardCheck}>② 골든셋 항목 구성</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">질문</span> — 사용자가 실제로 물어볼 법한 질문을 표현을 다양하게(동의어·구어체) 넣으십시오.</>,
            <><span className="font-medium text-foreground">기대 정답</span> — 모범 답안. judge(LLM 채점)를 켤 때 비교 기준이 됩니다(선택).</>,
            <><span className="font-medium text-foreground">기대 출처</span> — 정답이 들어 있는 문서 이름. Hit Rate·MRR 계산의 핵심입니다.</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={BarChart3}>③ 지표 읽는 법</Sub>
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="w-32 p-2">지표</th>
                <th className="p-2">의미</th>
              </tr>
            </thead>
            <tbody>
              {METRIC_ROWS.map((r) => (
                <tr key={r.metric} className="border-t align-top">
                  <td className="p-2 font-medium text-foreground">{r.metric}</td>
                  <td className="p-2 text-muted-foreground">{r.meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <Sub icon={AlertTriangle} color="text-amber-500">평가를 의미 있게 하려면</Sub>
        <Bullets
          items={[
            "임베딩 모델만 비교하려면 검색 방식을 '벡터'로 격리하십시오(하이브리드는 키워드 검색이 섞여 차이가 가려집니다).",
            "지식베이스에 문서가 1개뿐이면 무엇을 검색해도 1등이라 Hit Rate가 항상 1.0이 됩니다. 다른 주제의 문서를 함께 넣으십시오.",
            "여러 설정 조합을 한 번에 비교하려면 설정 스윕을 쓰십시오. 결과가 리더보드로 정리됩니다.",
          ]}
          icon={CheckCircle2}
          color="text-amber-500"
        />
      </section>

      <Callout>
        평가는 RAG의 나침반입니다. 모델·청킹·리랭커·<Link href="/dashboard/pipelines" className="text-primary hover:underline">파이프라인</Link> 등
        무엇을 바꾸든, 바꾸기 전·후를 같은 골든셋으로 측정해 <span className="font-medium text-foreground">숫자로 확인</span>하는
        습관을 들이십시오.
      </Callout>
    </TabShell>
  )
}
