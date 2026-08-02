// 피드백 — 답변 👍/👎 수집 목록/승격 탭 + 사용법 탭. 사용법은 RAG 개요와 같은 안내 블록을 공유한다.
"use client"

import { useCallback, useEffect, useState, type FormEvent } from "react"
import Link from "next/link"
import { ArrowUpRight, Filter, MessageSquare, Plus, RefreshCw, ThumbsDown, ThumbsUp, Trash2, X } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import { Badge } from "@workspace/ui/components/badge"
import { Textarea } from "@workspace/ui/components/textarea"
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
import { TabsContent, TabsList, TabsTrigger } from "@workspace/ui/components/tabs"
import { Tooltip, TooltipContent, TooltipTrigger } from "@workspace/ui/components/tooltip"
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard-header"
import { DataTablePagination, useClientPagination } from "@/components/data-table"
import { Bullets, Callout, Heading, Sub, TabShell } from "@/components/doc-blocks"
import { useAuth } from "@/features/auth"
import {
  deleteFeedback,
  dismissFeedback,
  getFeedbackStats,
  listFeedback,
  promoteFeedback,
  submitFeedback,
} from "@/features/feedback/api"
import type { Feedback, FeedbackRating, FeedbackStats } from "@/features/feedback/data/schema"
import { listDatasets } from "@/features/evaluation/api"
import type { EvalDataset } from "@/features/evaluation/data/schema"
import { listCollections } from "@/features/collections/api"
import type { Collection } from "@/features/collections/data/schema"
import { UrlTabs } from "@/components/url-tabs"

const STATUS_FILTERS = [
  { value: "all", label: "전체" },
  { value: "new", label: "신규" },
  { value: "promoted", label: "승격됨" },
  { value: "dismissed", label: "무시됨" },
]

const RATING_FILTERS = [
  { value: "all", label: "전체" },
  { value: "up", label: "👍 도움됨" },
  { value: "down", label: "👎 개선필요" },
]

function StatusBadge({ status }: { status: string }) {
  if (status === "promoted") return <Badge className="bg-emerald-600">승격됨</Badge>
  if (status === "dismissed") return <Badge variant="outline">무시됨</Badge>
  return <Badge variant="secondary">신규</Badge>
}

export default function FeedbackPage() {
  return (
    <>
      <DashboardHeader title="피드백" />
      <div className="flex flex-1 flex-col p-4">
        <UrlTabs defaultValue="list" className="gap-4">
          <TabsList>
            <TabsTrigger value="list">목록</TabsTrigger>
            <TabsTrigger value="guide">사용법</TabsTrigger>
          </TabsList>
          <TabsContent value="list">
            <FeedbackListTab />
          </TabsContent>
          <TabsContent value="guide">
            <FeedbackUsageTab />
          </TabsContent>
        </UrlTabs>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// 목록 / 승격
// ---------------------------------------------------------------------------

function FeedbackListTab() {
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser
  const [items, setItems] = useState<Feedback[]>([])
  const [stats, setStats] = useState<FeedbackStats | null>(null)
  const [datasets, setDatasets] = useState<EvalDataset[]>([])
  const [loading, setLoading] = useState(true)
  const [ratingFilter, setRatingFilter] = useState("all")
  const [statusFilter, setStatusFilter] = useState("all")

  // 승격 다이얼로그
  const [promoteTarget, setPromoteTarget] = useState<Feedback | null>(null)
  const [datasetId, setDatasetId] = useState("")
  const [expectedAnswer, setExpectedAnswer] = useState("")
  const [submitting, setSubmitting] = useState(false)

  // 삭제 확인 다이얼로그
  const [deleteTarget, setDeleteTarget] = useState<Feedback | null>(null)

  // 수동 등록 다이얼로그
  const [addOpen, setAddOpen] = useState(false)
  const [collections, setCollections] = useState<Collection[]>([])
  const [fbRating, setFbRating] = useState<FeedbackRating>("up")
  const [fbCollectionId, setFbCollectionId] = useState("")
  const [fbQuery, setFbQuery] = useState("")
  const [fbAnswer, setFbAnswer] = useState("")
  const [fbComment, setFbComment] = useState("")
  const [fbCorrected, setFbCorrected] = useState("")
  const [adding, setAdding] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [list, st] = await Promise.all([
        listFeedback({
          rating: ratingFilter !== "all" ? ratingFilter : undefined,
          status: statusFilter !== "all" ? statusFilter : undefined,
        }),
        getFeedbackStats(),
      ])
      setItems(list)
      setStats(st)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [ratingFilter, statusFilter])

  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    listCollections({ page_size: 100 }).then((r) => setCollections(r.items)).catch(() => {})
  }, [])

  async function handleManualAdd(e: FormEvent) {
    e.preventDefault()
    if (!fbQuery.trim()) return
    setAdding(true)
    try {
      await submitFeedback({
        rating: fbRating,
        query: fbQuery.trim(),
        answer: fbAnswer.trim() || null,
        collection_id: fbCollectionId ? Number(fbCollectionId) : null,
        comment: fbComment.trim() || null,
        corrected_answer: fbCorrected.trim() || null,
      })
      toast.success("피드백을 등록했습니다.")
      setAddOpen(false)
      setFbQuery("")
      setFbAnswer("")
      setFbComment("")
      setFbCorrected("")
      setFbCollectionId("")
      setFbRating("up")
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "등록 실패")
    } finally {
      setAdding(false)
    }
  }

  function openPromote(f: Feedback) {
    setPromoteTarget(f)
    setExpectedAnswer(f.corrected_answer || f.answer || "")
    setDatasetId("")
    listDatasets()
      .then((ds) => {
        setDatasets(ds)
        if (ds.length) setDatasetId(String(ds[0]!.id))
      })
      .catch(() => {})
  }

  async function handlePromote(e: FormEvent) {
    e.preventDefault()
    if (!promoteTarget || !datasetId) return
    setSubmitting(true)
    try {
      await promoteFeedback(promoteTarget.feedback_id, {
        dataset_id: Number(datasetId),
        expected_answer: expectedAnswer.trim() || null,
      })
      toast.success("평가 골든셋 항목으로 승격했습니다.")
      setPromoteTarget(null)
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "승격 실패")
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDismiss(f: Feedback) {
    try {
      await dismissFeedback(f.feedback_id)
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "처리 실패")
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    try {
      await deleteFeedback(deleteTarget.feedback_id)
      toast.success("피드백을 삭제했습니다.")
      setDeleteTarget(null)
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "삭제 실패")
    }
  }

  const { table, pageItems } = useClientPagination(items, 30)

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        사용자가 남긴 답변 평가(👍/👎)를 모아 평가 골든셋으로 승격해 검색·생성 품질을 지속 보강합니다.
      </p>

      {stats && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {[
            { label: "전체", value: stats.total },
            { label: "👍 도움됨", value: stats.up },
            { label: "👎 개선필요", value: stats.down },
            { label: "신규", value: stats.new },
            { label: "승격됨", value: stats.promoted },
          ].map((s) => (
            <Card key={s.label}>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium">{s.label}</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{s.value}</div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">평가</Label>
          <Select value={ratingFilter} onValueChange={setRatingFilter}>
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RATING_FILTERS.map((f) => (
                <SelectItem key={f.value} value={f.value}>
                  {f.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">상태</Label>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUS_FILTERS.map((f) => (
                <SelectItem key={f.value} value={f.value}>
                  {f.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {canManage && (
          <Button size="sm" className="ml-auto" onClick={() => setAddOpen(true)}>
            <Plus className="size-4" />
            피드백 등록
          </Button>
        )}
      </div>

      <div className="rounded-lg border">
        <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-14 text-center">평가</TableHead>
                <TableHead>질문</TableHead>
                <TableHead className="hidden md:table-cell">코멘트</TableHead>
                <TableHead className="w-24">상태</TableHead>
                <TableHead className="hidden lg:table-cell">작성자</TableHead>
                <TableHead className="w-32 text-right">작업</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-8 text-center text-sm text-muted-foreground">
                    불러오는 중...
                  </TableCell>
                </TableRow>
              ) : items.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-8 text-center text-sm text-muted-foreground">
                    수집된 피드백이 없습니다.
                  </TableCell>
                </TableRow>
              ) : (
                pageItems.map((f) => (
                  <TableRow key={f.id}>
                    <TableCell className="text-center">
                      {f.rating === "up" ? (
                        <ThumbsUp className="mx-auto size-4 text-emerald-600" />
                      ) : (
                        <ThumbsDown className="mx-auto size-4 text-rose-600" />
                      )}
                    </TableCell>
                    <TableCell className="max-w-xs">
                      <span className="line-clamp-2 text-sm">{f.query}</span>
                    </TableCell>
                    <TableCell className="hidden max-w-xs md:table-cell">
                      <span className="line-clamp-2 text-sm">
                        {f.comment || (f.corrected_answer ? "(수정답변 제공됨)" : "—")}
                      </span>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={f.status} />
                    </TableCell>
                    <TableCell className="hidden text-xs lg:table-cell">
                      {f.created_by || "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      {canManage && f.status === "new" && (
                        <div className="flex justify-end gap-1">
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => openPromote(f)}>
                                <ArrowUpRight className="size-4" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>평가 골든셋으로 승격</TooltipContent>
                          </Tooltip>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => handleDismiss(f)}>
                                <X className="size-4" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>무시 (평가에 반영 안 함)</TooltipContent>
                          </Tooltip>
                        </div>
                      )}
                      {canManage && f.status !== "new" && (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 px-2 text-muted-foreground"
                              onClick={() => setDeleteTarget(f)}
                            >
                              <Trash2 className="size-4" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>삭제</TooltipContent>
                        </Tooltip>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
        </Table>
      </div>

      {items.length > 0 && <DataTablePagination table={table} />}

      {/* 삭제 확인 */}
      <Dialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>피드백 삭제</DialogTitle>
            <DialogDescription>
              이 피드백을 삭제할까요? 이 작업은 되돌릴 수 없습니다.
            </DialogDescription>
          </DialogHeader>
          {deleteTarget && (
            <p className="rounded-md border bg-muted/40 p-2 text-sm">{deleteTarget.query}</p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setDeleteTarget(null)}>
              취소
            </Button>
            <Button type="button" variant="destructive" onClick={confirmDelete}>
              삭제
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 수동 등록 */}
      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent>
          <form onSubmit={handleManualAdd}>
            <DialogHeader>
              <DialogTitle>피드백 등록</DialogTitle>
              <DialogDescription>
                답변 평가를 수동으로 추가합니다. (보통은 Chat·Playground 답변의 👍/👎로 자동 수집됩니다.)
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-3 py-2">
              <div className="flex flex-wrap items-end gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">평가</Label>
                  <Select value={fbRating} onValueChange={(v) => setFbRating(v as FeedbackRating)}>
                    <SelectTrigger className="w-36">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="up">👍 도움됨</SelectItem>
                      <SelectItem value="down">👎 개선필요</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-1 flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">지식베이스 (선택)</Label>
                  <Select value={fbCollectionId || "__none__"} onValueChange={(v) => setFbCollectionId(v === "__none__" ? "" : v)}>
                    <SelectTrigger>
                      <SelectValue placeholder="컬렉션 선택" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__none__">없음</SelectItem>
                      {collections.map((c) => (
                        <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">질문</Label>
                <Input value={fbQuery} onChange={(e) => setFbQuery(e.target.value)} required autoFocus placeholder="사용자가 물어본 질문" />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">답변 (선택)</Label>
                <Textarea value={fbAnswer} onChange={(e) => setFbAnswer(e.target.value)} placeholder="평가 대상이 된 답변" className="min-h-20" />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">코멘트 (선택)</Label>
                <Textarea value={fbComment} onChange={(e) => setFbComment(e.target.value)} placeholder="개선 의견 등" className="min-h-16" />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">수정 답변 (선택)</Label>
                <Textarea value={fbCorrected} onChange={(e) => setFbCorrected(e.target.value)} placeholder="더 나은 답변 — 승격 시 정답 후보로 사용" className="min-h-16" />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setAddOpen(false)}>
                취소
              </Button>
              <Button type="submit" disabled={adding || !fbQuery.trim()}>
                {adding ? "등록 중..." : "등록"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={!!promoteTarget} onOpenChange={(o) => !o && setPromoteTarget(null)}>
        <DialogContent>
          <form onSubmit={handlePromote}>
            <DialogHeader>
              <DialogTitle>평가 골든셋으로 승격</DialogTitle>
              <DialogDescription>
                이 질문과 기대답변을 선택한 평가 데이터셋의 항목으로 추가합니다.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-3 py-2">
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">질문</Label>
                <p className="rounded-md border bg-muted/40 p-2 text-sm">{promoteTarget?.query}</p>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">대상 데이터셋</Label>
                <Select value={datasetId} onValueChange={setDatasetId}>
                  <SelectTrigger>
                    <SelectValue placeholder="데이터셋 선택" />
                  </SelectTrigger>
                  <SelectContent>
                    {datasets.map((d) => (
                      <SelectItem key={d.id} value={String(d.id)}>
                        {d.name} ({d.item_count})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {datasets.length === 0 && (
                  <span className="text-xs text-rose-600">먼저 평가 화면에서 데이터셋을 만들어 주세요.</span>
                )}
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">기대답변</Label>
                <Textarea
                  value={expectedAnswer}
                  onChange={(e) => setExpectedAnswer(e.target.value)}
                  placeholder="골든셋의 정답으로 사용할 답변"
                  className="min-h-24"
                />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setPromoteTarget(null)}>
                취소
              </Button>
              <Button type="submit" disabled={submitting || !datasetId}>
                {submitting ? "승격 중..." : "승격"}
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

function FeedbackUsageTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={ThumbsUp}>피드백 — 실제 사용에서 배우기</Heading>
        <p className="text-muted-foreground">
          피드백은 사용자가 답변에 남긴 <span className="font-medium text-foreground">👍/👎를 모아</span>, 나쁜 답변을
          평가용 질문으로 승격해 품질을 개선하는 곳입니다. <span className="font-medium text-foreground">실제 실패 사례가
          곧 다음 평가 문제</span>가 되는, 사용 → 평가 → 개선의 선순환을 만듭니다. 답변의 👍/👎는 Chat·Playground에서
          쌓이고, 여기서는 모인 피드백을 검토·처리합니다. <span className="font-medium text-foreground">승격·무시·삭제는
          관리자</span>만 가능합니다.
        </p>
      </section>

      <section>
        <Sub icon={MessageSquare}>① 무엇을 수집하나</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">평점</span> — 👍 도움됨 / 👎 개선필요. 상단 카드에서 전체·👍·👎·신규·승격됨 집계를 한눈에 봅니다.</>,
            <><span className="font-medium text-foreground">수정 답변 · 코멘트</span> — 사용자가 제시한 더 나은 답과 메모(선택). 승격 시 정답 후보로 활용됩니다.</>,
            <><span className="font-medium text-foreground">상태</span> — 신규(new) → 승격(promoted) / 무시(dismissed)로 처리 흐름을 관리합니다. 평가·상태 필터로 추려 보십시오.</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={ArrowUpRight}>② 승격 · 무시 · 삭제</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">승격</span>(<ArrowUpRight className="inline size-3.5 align-text-bottom" />) — 👎 사례를 골든셋 항목으로 올립니다. 대상 <Link href="/dashboard/evaluation" className="text-primary hover:underline">데이터셋</Link>을 고르고 기대답변을 다듬어 추가하십시오(데이터셋이 없으면 평가 화면에서 먼저 생성).</>,
            <><span className="font-medium text-foreground">무시</span>(✕) — 평가에 넣을 필요 없는 신규 항목을 정리합니다.</>,
            <><span className="font-medium text-foreground">삭제</span> — 이미 처리된(승격·무시) 항목을 목록에서 제거합니다.</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={Filter}>③ 무엇을 먼저 보나</Sub>
        <Bullets
          items={[
            <>평가 필터를 <span className="font-medium text-foreground">👎 개선필요</span>, 상태 필터를 <span className="font-medium text-foreground">신규</span>로 두면 손봐야 할 실패 사례만 추려집니다.</>,
            <>수정 답변이 함께 달린 👎부터 승격하면 양질의 골든셋이 빠르게 쌓입니다.</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={RefreshCw} color="text-emerald-500">개선 루프</Sub>
        <p className="text-sm text-muted-foreground">
          답변 평점 수집 → 👎 사례 검토 → <span className="font-medium text-foreground">골든셋 항목으로 승격(promote)</span>
          {" "}→ 다음 <Link href="/dashboard/evaluation" className="text-primary hover:underline">평가</Link>에 반영 → 설정·
          <Link href="/dashboard/pipelines" className="text-primary hover:underline">파이프라인</Link> 개선. 이 과정을
          반복할수록 평가셋이 현실에 가까워집니다.
        </p>
      </section>

      <Callout>
        👎 피드백에는 <span className="font-medium text-foreground">수정 답변과 기대 출처</span>를 함께 받도록 유도하십시오.
        승격 시 곧바로 양질의 골든셋 항목이 되어, <Link href="/dashboard/evaluation" className="text-primary hover:underline">평가</Link>의
        정확도가 올라갑니다.
      </Callout>
    </TabShell>
  )
}
