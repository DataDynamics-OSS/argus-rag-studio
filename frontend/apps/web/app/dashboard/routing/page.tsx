// 문서 라우팅 — 컬렉션 미지정 문서를 적절한 지식베이스로 자동 배분하는 정책 관리·테스트·인테이크.
// 백엔드 app/routing. 라우팅은 파싱/임베딩 전 메타데이터+분류로 결정(무비용), 결정 후 기존 인제스천 경로 재사용.
"use client"

import { Fragment, useCallback, useEffect, useRef, useState } from "react"
import Link from "next/link"
import {
  ChevronDown,
  ChevronRight,
  FileUp,
  FlaskConical,
  FolderInput,
  FolderSearch,
  GitBranch,
  HardDrive,
  History,
  Network,
  RotateCcw,
  Save,
  Upload,
} from "lucide-react"
import { Checkbox } from "@workspace/ui/components/checkbox"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Badge } from "@workspace/ui/components/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@workspace/ui/components/card"
import { Popover, PopoverContent, PopoverTrigger } from "@workspace/ui/components/popover"
import { TabsContent, TabsList, TabsTrigger } from "@workspace/ui/components/tabs"
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
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard-header"
import { Bullets, Callout, Heading, Sub, TabShell } from "@/components/doc-blocks"
import { useAuth } from "@/features/auth"
import { listCollections } from "@/features/collections/api"
import {
  applyFeedbackSuggestion,
  getPolicy,
  intake,
  intakeByReference,
  intakeScan,
  listFeedbackSuggestions,
  listPolicyVersions,
  listRouters,
  listRoutingDecisions,
  resolveRoutingDecision,
  rollbackPolicy,
  routePreview,
  listRoutingProfiles,
  recomputeRoutingProfiles,
  routePreviewByReference,
  updatePolicy,
} from "@/features/routing/api"
import type {
  FeedbackSuggestion,
  FeedbackSuggestions,
  RoutingDecisionItem,
  RoutingDecisionList,
  RoutingProfileStatus,
} from "@/features/routing/api"
import { listSources } from "@/features/storage-sources/api"
import type { StorageSource } from "@/features/storage-sources/data/schema"
import { SourcePathPicker } from "@/features/storage-sources/components/source-path-picker"
import type {
  RouteDecision,
  RouterInfo,
  RoutePreviewResult,
  RoutingPolicy,
  RoutingPolicyConfig,
  RoutingPolicyVersion,
  ScanIntakeResult,
  ScanItemStatus,
} from "@/features/routing/data/schema"
import { DecisionBadges, RouterHelp, RoutingPolicyBuilder } from "@/features/routing/components/routing-policy-builder"
import { UrlTabs } from "@/components/url-tabs"

type CollectionOpt = { id: number; name: string }

// yyyy-MM-dd HH:mm:ss (로컬 시간)
function fmtDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "—"
  const p = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

export default function RoutingPage() {
  // 검토 대기 건수 배지 — 탭 진입 없이도 처리할 게 있는지 보이게 한다.
  const [pendingReview, setPendingReview] = useState(0)
  useEffect(() => {
    listRoutingDecisions({ reviewOnly: true, page: 1, pageSize: 1 })
      .then((r) => setPendingReview(r.pending_review))
      .catch(() => {})
  }, [])
  return (
    <>
      <DashboardHeader title="RAG 문서 라우팅" />
      <div className="flex flex-1 flex-col p-4">
        <UrlTabs defaultValue="policy" className="gap-4">
          <TabsList>
            <TabsTrigger value="policy">라우팅 정책</TabsTrigger>
            <TabsTrigger value="test">라우팅 테스트</TabsTrigger>
            <TabsTrigger value="intake">인테이크</TabsTrigger>
            <TabsTrigger value="review">
              검토 대기
              {pendingReview > 0 && (
                <Badge variant="warning" className="ml-1 px-1.5 text-xs tabular-nums">
                  {pendingReview}
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="profiles">내용 라우팅 기준</TabsTrigger>
            <TabsTrigger value="guide">사용법</TabsTrigger>
          </TabsList>
          <TabsContent value="policy"><PolicyTab /></TabsContent>
          <TabsContent value="test"><RouteTestTab /></TabsContent>
          <TabsContent value="intake"><IntakeTab /></TabsContent>
          <TabsContent value="review"><ReviewTab onPendingChange={setPendingReview} /></TabsContent>
          <TabsContent value="profiles"><ProfilesTab /></TabsContent>
          <TabsContent value="guide"><GuideTab /></TabsContent>
        </UrlTabs>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// 결정 표시(미리보기/인테이크 공용)
// ---------------------------------------------------------------------------

// 라우터 id → 표시 라벨(레지스트리 label) — 정책 탭과 동일한 이름으로 보여준다.
// weighted_vote(모드) 등 레지스트리에 없는 값은 그대로 둔다.
function useRouterLabels(): Record<string, string> {
  const [labels, setLabels] = useState<Record<string, string>>({})
  useEffect(() => {
    listRouters()
      .then((r) => setLabels(Object.fromEntries(r.routers.map((x) => [x.id, x.label]))))
      .catch(() => {})
  }, [])
  return labels
}

function DecisionView({ decision }: { decision: RouteDecision }) {
  const routerLabels = useRouterLabels()
  const labelOf = (id: string | null) => (id ? routerLabels[id] ?? id : id)
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-baseline gap-2">
          <span className="text-sm text-muted-foreground">선택된 지식베이스</span>
          <span className="text-sm font-semibold">
            {decision.collection_name ?? (decision.collection_id != null ? `#${decision.collection_id}` : "없음")}
          </span>
        </div>
        <Badge variant="outline" className="text-sm tabular-nums">신뢰도 {decision.confidence.toFixed(3)}</Badge>
        <DecisionBadges matched={labelOf(decision.matched_router)} fallback={decision.fallback_used} review={decision.review} />
      </div>

      <div>
        <p className="mb-1 text-sm font-medium text-muted-foreground">라우터별 평가(trace)</p>
        <div className="overflow-hidden rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-44">라우터</TableHead>
                <TableHead>후보 (컬렉션 · 점수 · 사유)</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {decision.trace.length === 0 ? (
                <TableRow><TableCell colSpan={2} className="py-4 text-center text-sm text-muted-foreground">실행된 라우터가 없습니다(빈 정책).</TableCell></TableRow>
              ) : (
                decision.trace.map((t, i) => (
                  <TableRow key={i}>
                    <TableCell className="align-top">
                      <span className="flex items-center gap-1 text-sm">{labelOf(t.router)} <RouterHelp id={t.router} /></span>
                    </TableCell>
                    <TableCell>
                      {t.candidates.length === 0 ? (
                        <span className="text-sm text-muted-foreground">후보 없음</span>
                      ) : (
                        <div className="flex flex-col gap-1">
                          {t.candidates.map((c, j) => (
                            <div key={j} className="flex items-center gap-2 text-sm">
                              <Badge variant="secondary" className="text-sm font-normal tabular-nums">#{c.collection_id} · {c.score.toFixed(3)}</Badge>
                              <span className="text-muted-foreground">{c.reason}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  )
}

// 파일 드롭존 + 파일 선택(단일 파일). 드래그 앤 드롭과 클릭 선택 모두 지원.
function FileDrop({
  file,
  onFile,
  disabled,
  hint,
}: {
  file: File | null
  onFile: (f: File | null) => void
  disabled?: boolean
  hint?: string
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        if (!disabled) setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragOver(false)
        if (!disabled) onFile(e.dataTransfer.files?.[0] ?? null)
      }}
      className={`flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-4 py-8 text-center transition-colors ${
        dragOver ? "border-primary bg-primary/5" : "border-muted-foreground/30"
      } ${disabled ? "opacity-60" : ""}`}
    >
      <FileUp className="size-6 text-muted-foreground" />
      <div className="text-sm">
        파일을 끌어다 놓거나{" "}
        <button
          type="button"
          className="font-medium text-primary underline-offset-2 hover:underline disabled:opacity-50"
          onClick={() => inputRef.current?.click()}
          disabled={disabled}
        >
          파일 선택
        </button>
      </div>
      {file ? (
        <div className="text-sm font-medium text-foreground">{file.name}</div>
      ) : (
        hint && <div className="text-sm text-muted-foreground">{hint}</div>
      )}
      <input ref={inputRef} type="file" className="hidden" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
    </div>
  )
}

function useCollections() {
  const [collections, setCollections] = useState<CollectionOpt[]>([])
  useEffect(() => {
    listCollections({ status: "active", page_size: 200 })
      .then((res) => setCollections(res.items.map((c) => ({ id: c.id, name: c.name }))))
      .catch(() => {})
  }, [])
  return collections
}

function useSources() {
  const [sources, setSources] = useState<StorageSource[]>([])
  useEffect(() => {
    listSources().then(setSources).catch(() => {})
  }, [])
  return sources
}

// ---------------------------------------------------------------------------
// 정책 탭
// ---------------------------------------------------------------------------

function formatBuiltAt(iso: string | null): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ""
  const p = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function ProfilesTab() {
  // 내용 임베딩 라우터(content_embedding)의 컬렉션 디스크립터(centroid) 관리 — Phase 2.
  const { user } = useAuth()
  const [rows, setRows] = useState<RoutingProfileStatus[]>([])
  const [loading, setLoading] = useState(false)
  const [computing, setComputing] = useState<number | "all" | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      setRows(await listRoutingProfiles())
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "디스크립터 조회 실패")
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => {
    void reload()
  }, [reload])

  async function recompute(collectionId?: number) {
    setComputing(collectionId ?? "all")
    try {
      const results = await recomputeRoutingProfiles(collectionId)
      const built = results.filter((r) => r.status === "built").length
      const errs = results.filter((r) => r.status === "error")
      toast.success(`디스크립터 계산 완료 — ${built}건 갱신${errs.length ? `, 실패 ${errs.length}건` : ""}`)
      if (errs.length) errs.forEach((r) => toast.error(`${r.name}: ${r.error ?? "실패"}`))
      await reload()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "재계산 실패")
    } finally {
      setComputing(null)
    }
  }

  return (
    <div className="flex flex-col gap-4 text-sm">
      <p className="w-[900px] text-sm">
        내용 라우팅(content_embedding 단계)이 문서를 비교할 컬렉션별 기준 벡터(디스크립터) — 최근 청크
        샘플(없으면 컬렉션 설명)을 전역 임베딩 설정으로 계산합니다. 새 문서가 충분히 쌓였거나
        전역 임베딩 설정을 바꿨을 때(stale) 재계산하세요.
      </p>
      {user?.is_admin && (
        <div className="flex w-[900px] justify-end">
          <Button size="sm" disabled={computing !== null} onClick={() => void recompute()}>
            {computing === "all" ? "계산 중..." : "전체 재계산"}
          </Button>
        </div>
      )}
      <Table className="w-[900px]">
        <TableHeader>
          <TableRow>
            <TableHead>컬렉션</TableHead>
            <TableHead>상태</TableHead>
            <TableHead>기준</TableHead>
            <TableHead className="text-right">샘플 수</TableHead>
            <TableHead>임베딩 모델</TableHead>
            <TableHead>계산 값</TableHead>
            <TableHead>계산 시간</TableHead>
            <TableHead className="w-[110px]" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.collection_id}>
              <TableCell className="text-sm">{r.name}</TableCell>
              <TableCell>
                {!r.built ? (
                  <Badge variant="outline" className="text-amber-600">미계산</Badge>
                ) : r.stale ? (
                  <Badge variant="outline" className="text-amber-600">재계산 필요</Badge>
                ) : (
                  <Badge variant="secondary" className="text-emerald-600">유효</Badge>
                )}
              </TableCell>
              <TableCell className="text-sm">
                {r.source === "chunks" ? "청크 샘플" : r.source === "description" ? "컬렉션 설명" : ""}
              </TableCell>
              <TableCell className="text-right text-sm tabular-nums">
                {r.built ? r.sample_count : ""}
              </TableCell>
              <TableCell className="text-sm">{r.space_model ?? ""}</TableCell>
              <TableCell>
                {r.built && r.centroid_preview.length > 0 && (
                  <Popover>
                    <PopoverTrigger asChild>
                      <Button size="sm" variant="ghost" className="h-7 px-2 font-mono text-xs">
                        [{r.centroid_preview[0]}, {r.centroid_preview[1]} …] {r.dim}d
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent align="start" className="w-96">
                      <div className="mb-1 text-sm font-medium">
                        centroid — {r.dim}차원 (L2 정규화, 앞 16개)
                      </div>
                      <div className="break-all font-mono text-xs text-muted-foreground">
                        [{r.centroid_preview.join(", ")}, …]
                      </div>
                    </PopoverContent>
                  </Popover>
                )}
              </TableCell>
              <TableCell className="text-sm tabular-nums">
                {formatBuiltAt(r.built_at)}
              </TableCell>
              <TableCell>
                {user?.is_admin && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={computing !== null}
                    onClick={() => void recompute(r.collection_id)}
                  >
                    {computing === r.collection_id ? "계산 중..." : "재계산"}
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
          {!loading && rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={8} className="text-center text-sm text-muted-foreground">
                활성 컬렉션이 없습니다.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      <div className="w-[900px]">
      <Callout>
        정책의 <b>내용 임베딩</b> 단계는 유효한 디스크립터가 있는 컬렉션만 후보로 봅니다 —
        미계산/재계산 필요 상태의 컬렉션은 해당 단계에서 제외됩니다(다른 규칙·폴백은 그대로 동작).
      </Callout>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 검토 대기 탭(Phase 3) — 저신뢰/폴백 결정 확인·재배정
// ---------------------------------------------------------------------------

function ReviewTab({ onPendingChange }: { onPendingChange: (n: number) => void }) {
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser
  const collections = useCollections()
  const routerLabels = useRouterLabels()
  const labelOf = (id: string | null) => (id ? routerLabels[id] ?? id : id)
  const [data, setData] = useState<RoutingDecisionList | null>(null)
  const [page, setPage] = useState(1)
  const [showAll, setShowAll] = useState(false) // true = 처리된 결정 포함(전체 이력)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null) // trace 펼친 decision_id
  const [targets, setTargets] = useState<Record<string, number>>({}) // decision_id → 재배정 대상
  const [busy, setBusy] = useState<string | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const r = await listRoutingDecisions({ reviewOnly: !showAll, page, pageSize: 20 })
      setData(r)
      onPendingChange(r.pending_review)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "결정 로그 조회 실패")
    } finally {
      setLoading(false)
    }
  }, [page, showAll, onPendingChange])
  useEffect(() => {
    void reload()
  }, [reload])

  async function resolve(d: RoutingDecisionItem, targetCollectionId?: number) {
    setBusy(d.decision_id)
    try {
      const r = await resolveRoutingDecision(d.decision_id, targetCollectionId)
      toast.success(
        r.reassigned
          ? `재배정 완료 — ${r.decision.corrected_collection_name ?? targetCollectionId} 로 재색인을 시작했습니다.`
          : "확인 처리했습니다(현재 배분 유지)."
      )
      await reload()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "검토 처리 실패")
    } finally {
      setBusy(null)
    }
  }

  // 결정 로그 행 → RouteDecision 형태로 변환 — 미리보기/인테이크와 동일한
  // DecisionView(trace 테이블)를 재사용하기 위한 어댑터.
  const toRouteDecision = (d: RoutingDecisionItem): RouteDecision => ({
    collection_id: d.collection_id,
    collection_name: d.collection_name,
    confidence: d.confidence,
    mode: d.mode ?? "first_match",
    matched_router: d.matched_router,
    fallback_used: d.fallback_used,
    review: d.review,
    policy_version: d.policy_version,
    trace: d.trace,
  })

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1
  return (
    <div className="flex flex-col gap-4 text-sm">
      <p className="w-[1100px] text-sm">
        자동 라우팅이 <b>자신 없었던 결정</b>(신뢰도가 정책의 검토 임계 미만이거나 폴백으로 배분)의
        대기열입니다. 근거(trace)를 보고 <b>맞음 확인</b>하거나 올바른 지식베이스로 <b>재배정</b>하세요 —
        재배정하면 문서가 이동하고 새 지식베이스 설정으로 재색인됩니다. 수정 내역은 규칙 튜닝의
        근거 데이터로 남습니다.
      </p>
      <div className="flex w-[1100px] items-center justify-between">
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={showAll}
            onCheckedChange={(v) => {
              setPage(1)
              setShowAll(v === true)
            }}
          />
          처리된 결정 포함(전체 이력)
        </label>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="tabular-nums">
            {data ? `${data.total}건 · ${page}/${totalPages} 페이지` : ""}
          </span>
          <Button size="sm" variant="outline" disabled={page <= 1 || loading} onClick={() => setPage((p) => p - 1)}>
            이전
          </Button>
          <Button size="sm" variant="outline" disabled={page >= totalPages || loading} onClick={() => setPage((p) => p + 1)}>
            다음
          </Button>
        </div>
      </div>
      <Table className="w-[1100px]">
        <TableHeader>
          <TableRow>
            <TableHead>문서</TableHead>
            <TableHead>배분된 지식베이스</TableHead>
            <TableHead className="text-right">신뢰도</TableHead>
            <TableHead>근거</TableHead>
            <TableHead>시각</TableHead>
            <TableHead className="w-[340px]">처리</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {(data?.items ?? []).map((d) => {
            const isExpanded = expanded === d.decision_id
            const target = targets[d.decision_id] ?? 0
            return (
              <Fragment key={d.decision_id}>
                <TableRow>
                  <TableCell className="max-w-64">
                    <button
                      type="button"
                      className="flex items-center gap-1 text-left text-sm underline-offset-2 hover:underline"
                      onClick={() => setExpanded(isExpanded ? null : d.decision_id)}
                      title="라우터별 평가(trace) 펼치기"
                    >
                      {isExpanded ? <ChevronDown className="size-3.5 shrink-0" /> : <ChevronRight className="size-3.5 shrink-0" />}
                      <span className="truncate">{d.document_name ?? `문서 #${d.document_id}`}</span>
                    </button>
                  </TableCell>
                  <TableCell className="text-sm">
                    {d.collection_name ?? (d.collection_id != null ? `#${d.collection_id}` : "—")}
                  </TableCell>
                  <TableCell className="text-right text-sm tabular-nums">{d.confidence.toFixed(3)}</TableCell>
                  <TableCell>
                    <DecisionBadges matched={labelOf(d.matched_router)} fallback={d.fallback_used} review={d.review} />
                  </TableCell>
                  <TableCell className="text-sm tabular-nums">{fmtDateTime(d.created_at)}</TableCell>
                  <TableCell>
                    {d.review ? (
                      canManage ? (
                        <div className="flex items-center gap-2">
                          <Select
                            value={target ? String(target) : ""}
                            onValueChange={(v) => setTargets((m) => ({ ...m, [d.decision_id]: Number(v) }))}
                          >
                            <SelectTrigger className="h-8 w-44 text-sm">
                              <SelectValue placeholder="지식베이스 선택" />
                            </SelectTrigger>
                            <SelectContent>
                              {collections
                                .filter((c) => c.id !== d.collection_id)
                                .map((c) => (
                                  <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                                ))}
                            </SelectContent>
                          </Select>
                          <Button
                            size="sm"
                            disabled={!target || busy !== null}
                            onClick={() => void resolve(d, target)}
                          >
                            {busy === d.decision_id ? "처리 중..." : "재배정"}
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busy !== null}
                            onClick={() => void resolve(d)}
                          >
                            맞음 확인
                          </Button>
                        </div>
                      ) : (
                        <span className="text-sm text-muted-foreground">관리자만 처리 가능</span>
                      )
                    ) : (
                      <span className="text-sm text-muted-foreground">
                        {d.corrected_collection_id != null
                          ? `${d.corrected_collection_name ?? `#${d.corrected_collection_id}`} 로 재배정`
                          : d.reviewed_at
                            ? "확인됨"
                            : "—"}
                        {d.reviewed_by ? ` · ${d.reviewed_by}` : ""}
                        {d.reviewed_at ? ` · ${fmtDateTime(d.reviewed_at)}` : ""}
                      </span>
                    )}
                  </TableCell>
                </TableRow>
                {isExpanded && (
                  <TableRow>
                    <TableCell colSpan={6} className="bg-muted/30">
                      <div className="py-2">
                        <DecisionView decision={toRouteDecision(d)} />
                        {d.policy_version != null && (
                          <p className="mt-2 text-xs text-muted-foreground">정책 v{d.policy_version} 로 결정됨</p>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            )
          })}
          {!loading && (data?.items.length ?? 0) === 0 && (
            <TableRow>
              <TableCell colSpan={6} className="py-8 text-center text-sm text-muted-foreground">
                {showAll ? "라우팅 결정 이력이 없습니다." : "검토할 결정이 없습니다 — 모든 자동 배분이 신뢰 임계를 넘었습니다."}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      <FeedbackSection canManage={!!canManage} refreshKey={data?.pending_review ?? -1} />
      <div className="w-[1100px]">
        <Callout>
          검토 대상 기준은 라우팅 정책의 <b>검토 임계(review_below)</b>와 <b>폴백 사용 여부</b>입니다 —
          정책 탭에서 임계를 조정하면 이후 결정부터 적용됩니다. 재배정해도 원 결정 로그는 남으며,
          같은 유형의 수정이 반복되면 아래 <b>규칙 제안</b>으로 정책에 반영하세요.
        </Callout>
      </div>
    </div>
  )
}

// 수정 피드백 루프 — 재배정 내역의 반복 신호를 규칙 제안으로 보여주고 1클릭 반영.
// refreshKey: 재배정이 일어나면(pending_review 변화) 제안을 다시 계산한다.
function FeedbackSection({ canManage, refreshKey }: { canManage: boolean; refreshKey: number }) {
  const routerLabels = useRouterLabels()
  const [data, setData] = useState<FeedbackSuggestions | null>(null)
  const [applying, setApplying] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      setData(await listFeedbackSuggestions())
    } catch {
      // 제안은 부가 기능 — 조회 실패로 검토 큐 화면을 막지 않는다.
    }
  }, [])
  useEffect(() => {
    void reload()
  }, [reload, refreshKey])

  const KIND_LABEL: Record<string, string> = {
    extension: "확장자",
    filename_token: "파일명 키워드",
    doc_type: "문서 유형(doc_type)",
    source_path: "소스 경로",
  }

  async function apply(s: FeedbackSuggestion) {
    const key = `${s.router}:${s.value}:${s.collection_id}`
    setApplying(key)
    try {
      const policy = await applyFeedbackSuggestion(s)
      toast.success(`정책 v${policy.active_version} 생성 — ${routerLabels[s.router] ?? s.router}에 규칙을 추가했습니다.`)
      await reload()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "제안 반영 실패")
    } finally {
      setApplying(null)
    }
  }

  if (!data) return null
  return (
    <div className="flex w-[1100px] flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <p className="text-sm font-medium">규칙 제안 — 수정 피드백</p>
        <span className="text-xs text-muted-foreground">
          수동 재배정 {data.total_corrections}건 분석
          {data.already_covered > 0 && ` · 정책에 이미 반영된 제안 ${data.already_covered}건 제외`}
        </span>
      </div>
      {data.suggestions.length === 0 ? (
        <p className="rounded-md border border-dashed px-4 py-3 text-sm text-muted-foreground">
          {data.total_corrections === 0
            ? "아직 수동 재배정 내역이 없습니다 — 재배정이 쌓이면 반복 패턴을 규칙으로 제안합니다."
            : "제안할 반복 패턴이 없습니다 — 같은 신호(확장자·키워드·유형·경로)가 같은 지식베이스로 2회 이상 수정되면 나타납니다."}
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {data.suggestions.map((s) => {
            const key = `${s.router}:${s.value}:${s.collection_id}`
            return (
              <div key={key} className="flex items-center justify-between gap-3 rounded-md border px-4 py-2.5">
                <div className="flex min-w-0 flex-col gap-1">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <Badge variant="secondary" className="font-normal">{KIND_LABEL[s.kind] ?? s.kind}</Badge>
                    <span className="font-mono">{s.value}</span>
                    {s.storage && <span className="text-xs text-muted-foreground">(소스: {s.storage})</span>}
                    <span className="text-muted-foreground">→</span>
                    <span className="font-medium">{s.collection_name ?? `#${s.collection_id}`}</span>
                    <span className="text-xs text-muted-foreground">
                      {routerLabels[s.router] ?? s.router} 규칙으로 추가
                    </span>
                  </div>
                  <div className="truncate text-xs text-muted-foreground">
                    근거: 수정 {s.support}/{s.total}건 (순도 {(s.purity * 100).toFixed(0)}%) · 예: {s.samples.join(", ")}
                  </div>
                </div>
                {canManage && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="shrink-0"
                    disabled={applying !== null}
                    onClick={() => void apply(s)}
                  >
                    {applying === key ? "반영 중..." : "정책에 반영"}
                  </Button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function PolicyTab() {
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser
  const collections = useCollections()
  const sources = useSources()
  const [policy, setPolicy] = useState<RoutingPolicy | null>(null)
  const [routers, setRouters] = useState<RouterInfo[]>([])
  const [draft, setDraft] = useState<RoutingPolicyConfig | null>(null)
  const [versions, setVersions] = useState<RoutingPolicyVersion[]>([])
  const [versionPage, setVersionPage] = useState(0) // 버전 이력 페이지(10개씩, 이전/다음)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState("")

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [p, r, v] = await Promise.all([getPolicy(), listRouters(), listPolicyVersions()])
      setPolicy(p)
      setDraft(p.config)
      setRouters(r.routers)
      setVersions(v)
      setVersionPage(0)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { refresh() }, [refresh])

  async function save() {
    if (!draft) return
    setSaving(true)
    try {
      await updatePolicy(draft, note.trim() || undefined)
      toast.success("정책을 저장했습니다(새 버전).")
      setNote("")
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "저장 실패")
    } finally {
      setSaving(false)
    }
  }

  async function doRollback(version: number) {
    try {
      await rollbackPolicy(version)
      toast.success(`v${version} 로 롤백했습니다.`)
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "롤백 실패")
    }
  }

  if (loading || !draft) return <p className="p-4 text-sm text-muted-foreground">불러오는 중...</p>

  const dirty = JSON.stringify(draft) !== JSON.stringify(policy?.config)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          컬렉션 미지정 문서를 라우터 조합으로 적절한 지식베이스에 배분합니다. 저장 시 새 버전이 만들어집니다(active).
          {!canManage && <span className="text-destructive"> 편집은 관리자만 가능합니다.</span>}
        </p>
        {policy && <Badge variant="outline" className="text-sm">활성 v{policy.active_version} · 총 {policy.version_count}버전</Badge>}
      </div>

      <Card>
        <CardContent className="pt-6">
          <RoutingPolicyBuilder
            config={draft}
            onChange={setDraft}
            routers={routers}
            collections={collections}
            sources={sources.map((s) => s.name)}
            disabled={!canManage}
          />
        </CardContent>
      </Card>

      {canManage && (
        <div className="flex items-center justify-end gap-2">
          <Input className="w-64" placeholder="변경 메모(선택)" value={note} onChange={(e) => setNote(e.target.value)} />
          <Button variant="outline" onClick={() => setDraft(policy?.config ?? draft)} disabled={!dirty || saving}>
            <RotateCcw className="size-4" /> 되돌리기
          </Button>
          <Button onClick={save} disabled={!dirty || saving}>
            <Save className="size-4" /> {saving ? "저장 중..." : "저장(새 버전)"}
          </Button>
        </div>
      )}

      {/* 버전 이력 */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm font-medium"><History className="size-4" /> 버전 이력</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-hidden rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-20 text-center">버전</TableHead>
                  <TableHead className="w-20 text-center">상태</TableHead>
                  <TableHead className="w-24 text-center">단계 수</TableHead>
                  <TableHead>메모</TableHead>
                  <TableHead className="w-40 text-center">작성자</TableHead>
                  <TableHead className="w-48 text-center">작성일</TableHead>
                  <TableHead className="w-24 text-center">작업</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {versions.slice(versionPage * 10, versionPage * 10 + 10).map((v) => (
                  <TableRow key={v.version}>
                    <TableCell className="text-center tabular-nums">v{v.version}</TableCell>
                    <TableCell className="text-center">
                      {policy?.active_version === v.version
                        ? <Badge variant="success" className="text-sm">활성</Badge>
                        : <span className="text-muted-foreground">—</span>}
                    </TableCell>
                    <TableCell className="text-center text-sm tabular-nums">{v.config.stages?.length ?? 0}</TableCell>
                    <TableCell className="text-sm">{v.note || "—"}</TableCell>
                    <TableCell className="text-center text-sm">{v.created_by || "—"}</TableCell>
                    <TableCell className="text-center text-sm tabular-nums">{fmtDateTime(v.created_at)}</TableCell>
                    <TableCell className="text-center">
                      {canManage && policy?.active_version !== v.version && (
                        <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => doRollback(v.version)}>
                          <RotateCcw className="size-3.5" /> 롤백
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {versions.length > 10 && (
            <div className="mt-2 flex items-center justify-end gap-2">
              <span className="text-sm tabular-nums text-muted-foreground">
                {versionPage * 10 + 1}–{Math.min((versionPage + 1) * 10, versions.length)} / {versions.length}
              </span>
              <Button
                variant="outline"
                size="sm"
                className="h-7 px-2"
                disabled={versionPage === 0}
                onClick={() => setVersionPage((p) => p - 1)}
              >
                이전
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-7 px-2"
                disabled={(versionPage + 1) * 10 >= versions.length}
                onClick={() => setVersionPage((p) => p + 1)}
              >
                다음
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 라우팅 테스트 탭(route-preview)
// ---------------------------------------------------------------------------

const NO_SOURCE = "__none__"

function RouteTestTab() {
  const sources = useSources()
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<RoutePreviewResult | null>(null)
  const [running, setRunning] = useState(false)

  // 경로 시뮬레이션(파일 없이 경로·소스명만으로 정책 검증)
  const [simSource, setSimSource] = useState<string>(NO_SOURCE) // source_id
  const [simPath, setSimPath] = useState("")
  const [simRunning, setSimRunning] = useState(false)

  async function run() {
    if (!file) return
    setRunning(true)
    try {
      setResult(await routePreview(file))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "미리보기 실패")
    } finally {
      setRunning(false)
    }
  }

  async function runPathSim() {
    if (!simPath.trim()) return
    setSimRunning(true)
    try {
      setResult(await routePreviewByReference({
        path: simPath.trim(),
        source_id: simSource === NO_SOURCE ? undefined : simSource,
        path_only: true,
      }))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "경로 시뮬레이션 실패")
    } finally {
      setSimRunning(false)
    }
  }

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        파일을 올리면 <span className="font-medium text-foreground">저장 없이</span> 현재 활성 정책으로 어느 지식베이스에 배분될지와 라우터별 근거를 보여줍니다. 정책을 바꾸기 전·후로 검증하십시오.
      </p>
      <FileDrop file={file} onFile={(f) => { setFile(f); setResult(null) }} />
      <div>
        <Button onClick={run} disabled={!file || running}>
          <FlaskConical className="size-4" /> {running ? "평가 중..." : "라우팅 미리보기"}
        </Button>
      </div>

      {/* 경로 시뮬레이션 — 파일 없이 경로 문자열만으로 경로 규칙(path_rule) 검증 */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm font-medium"><FolderSearch className="size-4" /> 경로 시뮬레이션</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            파일 없이 <span className="font-medium text-foreground">소스·경로 문자열만으로</span> 어디로 라우팅될지 확인합니다(경로 규칙 검증용 — 파일명 신호는 경로의 마지막 이름으로 평가).
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Select value={simSource} onValueChange={setSimSource}>
              <SelectTrigger className="h-9 w-44"><SelectValue placeholder="소스(선택)" /></SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_SOURCE}>소스 미지정</SelectItem>
                {sources.map((s) => <SelectItem key={s.source_id} value={s.source_id}>{s.name}</SelectItem>)}
              </SelectContent>
            </Select>
            <Input
              className="h-9 flex-1 font-mono text-sm" placeholder="contracts/2026/계약서.pdf"
              value={simPath} onChange={(e) => setSimPath(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") runPathSim() }}
            />
            <Button variant="outline" onClick={runPathSim} disabled={!simPath.trim() || simRunning}>
              {simRunning ? "평가 중..." : "경로로 미리보기"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {result && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">{result.filename}</CardTitle>
            {result.source_path && (
              <p className="font-mono text-sm text-muted-foreground">
                {result.storage ? `${result.storage}:` : ""}{result.source_path}
              </p>
            )}
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <DecisionView decision={result.decision} />
            <div>
              <p className="mb-1 text-sm font-medium text-muted-foreground">추출된 메타데이터(라우팅 입력)</p>
              <pre className="overflow-auto rounded-md border bg-muted/30 p-2 text-sm">{JSON.stringify(result.metadata, null, 2)}</pre>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 인테이크 탭(intake)
// ---------------------------------------------------------------------------

function IntakeTab() {
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser
  const sources = useSources()
  const enabledSources = sources.filter((s) => s.enabled)
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<RouteDecision | null>(null)
  const [jobInfo, setJobInfo] = useState<{ job_id: string; name: string } | null>(null)
  const [running, setRunning] = useState(false)

  // 소스에서 가져오기(참조 인테이크)
  const [refSource, setRefSource] = useState<string>("") // source_id
  const [refPath, setRefPath] = useState("")
  const [pickerOpen, setPickerOpen] = useState(false)
  const refSourceObj = enabledSources.find((s) => s.source_id === refSource)

  function clearResult() {
    setResult(null)
    setJobInfo(null)
  }

  async function finish(run: () => Promise<{ decision: RouteDecision; job_id: string; name: string }>) {
    setRunning(true)
    try {
      const res = await run()
      setResult(res.decision)
      setJobInfo({ job_id: res.job_id, name: res.name })
      toast.success(`"${res.name}" → ${res.decision.collection_name ?? "컬렉션"} 인제스천 시작`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "인테이크 실패")
    } finally {
      setRunning(false)
    }
  }

  if (!canManage) return <Callout>인테이크 업로드는 관리자만 가능합니다.</Callout>

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        컬렉션을 지정하지 않고 문서를 넣습니다. 활성 정책이 자동으로 지식베이스를 정해 등록·인제스천합니다.
        매칭 규칙도 폴백 컬렉션도 없으면 거부됩니다(정책 탭에서 폴백을 설정하십시오).
      </p>

      <UrlTabs defaultValue="upload" param="intake" className="gap-4">
        <TabsList>
          <TabsTrigger value="upload"><FileUp className="size-4" /> 파일 업로드</TabsTrigger>
          <TabsTrigger value="reference"><HardDrive className="size-4" /> 소스에서 가져오기</TabsTrigger>
          <TabsTrigger value="scan"><FolderInput className="size-4" /> 폴더 일괄 가져오기</TabsTrigger>
        </TabsList>

        <TabsContent value="upload" className="flex flex-col gap-4">
          <FileDrop file={file} onFile={(f) => { setFile(f); clearResult() }} />
          <div>
            <Button onClick={() => file && finish(() => intake(file))} disabled={!file || running}>
              <Upload className="size-4" /> {running ? "처리 중..." : "라우팅 후 인제스천"}
            </Button>
          </div>
        </TabsContent>

        <TabsContent value="reference" className="flex flex-col gap-4">
          <p className="text-sm text-muted-foreground">
            등록된 스토리지 소스(S3·NAS)의 문서를 <span className="font-medium text-foreground">경로로 가져와(pull)</span> 인테이크합니다.
            원본은 내부 저장소로 스냅샷 복사되고, 소스·경로는 경로 규칙(path_rule)의 라우팅 신호가 됩니다.
            {enabledSources.length === 0 && (
              <> 등록된 소스가 없습니다 — <Link href="/dashboard/storage-sources" className="text-primary hover:underline">스토리지 소스</Link>에서 먼저 등록하십시오.</>
            )}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Select value={refSource} onValueChange={(v) => { setRefSource(v); setRefPath(""); clearResult() }}>
              <SelectTrigger className="h-9 w-44"><SelectValue placeholder="소스 선택" /></SelectTrigger>
              <SelectContent>
                {enabledSources.map((s) => <SelectItem key={s.source_id} value={s.source_id}>{s.name}</SelectItem>)}
              </SelectContent>
            </Select>
            <Input
              className="h-9 flex-1 font-mono text-sm" placeholder="contracts/2026/계약서.pdf"
              value={refPath} onChange={(e) => setRefPath(e.target.value)} disabled={!refSourceObj}
            />
            <Button variant="outline" onClick={() => setPickerOpen(true)} disabled={!refSourceObj}>
              <FolderSearch className="size-4" /> 찾아보기
            </Button>
          </div>
          <div>
            <Button
              onClick={() => refSourceObj && finish(() => intakeByReference(refSourceObj.source_id, refPath.trim()))}
              disabled={!refSourceObj || !refPath.trim() || running}
            >
              <Upload className="size-4" /> {running ? "처리 중..." : "가져와서 라우팅 후 인제스천"}
            </Button>
          </div>
          {refSourceObj && (
            <SourcePathPicker
              open={pickerOpen} onOpenChange={setPickerOpen}
              sourceId={refSourceObj.source_id} sourceName={refSourceObj.name}
              onSelect={(p) => { setRefPath(p); clearResult() }}
            />
          )}
        </TabsContent>

        <TabsContent value="scan">
          <ScanIntakeSection sources={enabledSources} />
        </TabsContent>
      </UrlTabs>

      {result && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium">{jobInfo?.name}</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-4">
            <DecisionView decision={result} />
            {jobInfo && (
              <p className="text-sm text-muted-foreground">
                인제스천 잡 <span className="font-mono">{jobInfo.job_id}</span> — 진행 상황은{" "}
                <Link href="/dashboard/jobs" className="text-primary hover:underline">잡 모니터링</Link>에서 확인하십시오.
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 폴더 일괄 인테이크(드롭존) — 소스 prefix 하위 파일들을 dry run 미리보기 후 일괄 실행
// ---------------------------------------------------------------------------

// 시맨틱 상태색 — 초록=정상 확정, 회색=중립(스킵), 빨강=실패/오류.
const SCAN_STATUS_META: Record<ScanItemStatus, { label: string; variant: "success" | "outline" | "destructive" }> = {
  routed: { label: "배분됨", variant: "success" },
  duplicate: { label: "중복 스킵", variant: "outline" },
  no_route: { label: "라우팅 실패", variant: "destructive" },
  failed: { label: "오류", variant: "destructive" },
}

function ScanStatusBadge({ status }: { status: ScanItemStatus }) {
  const meta = SCAN_STATUS_META[status] ?? { label: status, variant: "outline" as const }
  return <Badge variant={meta.variant} className="text-sm font-normal">{meta.label}</Badge>
}

function ScanIntakeSection({ sources }: { sources: StorageSource[] }) {
  const [sourceId, setSourceId] = useState<string>("")
  const [prefix, setPrefix] = useState("")
  const [recursive, setRecursive] = useState(true)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [running, setRunning] = useState<"dry" | "run" | null>(null)
  const [report, setReport] = useState<ScanIntakeResult | null>(null)
  const sourceObj = sources.find((s) => s.source_id === sourceId)

  async function run(dryRun: boolean) {
    if (!sourceObj) return
    setRunning(dryRun ? "dry" : "run")
    try {
      const res = await intakeScan({
        source_id: sourceObj.source_id, prefix: prefix.trim(), recursive, dry_run: dryRun,
      })
      setReport(res)
      const routed = res.counts.routed ?? 0
      if (dryRun) toast.success(`미리보기 완료 — ${res.scanned}개 중 ${routed}개 배분 가능`)
      else toast.success(`일괄 인테이크 완료 — ${routed}개 등록·인제스천 시작`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "폴더 일괄 인테이크 실패")
    } finally {
      setRunning(null)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        소스의 폴더(프리픽스) 하위 파일들을 한 번에 가져와 라우팅·인제스천합니다(드롭존).
        같은 요청을 반복 실행해도 이미 등록된 파일은 <span className="font-medium text-foreground">중복 스킵</span>되므로 안전합니다.
        먼저 <span className="font-medium text-foreground">미리보기(dry run)</span>로 배분 결과를 확인하십시오. 한 번에 최대 500개 파일을 처리합니다.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <Select value={sourceId} onValueChange={(v) => { setSourceId(v); setPrefix(""); setReport(null) }}>
          <SelectTrigger className="h-9 w-44"><SelectValue placeholder="소스 선택" /></SelectTrigger>
          <SelectContent>
            {sources.map((s) => <SelectItem key={s.source_id} value={s.source_id}>{s.name}</SelectItem>)}
          </SelectContent>
        </Select>
        <Input
          className="h-9 flex-1 font-mono text-sm" placeholder="폴더 프리픽스(비우면 루트) — 예: inbox/"
          value={prefix} onChange={(e) => setPrefix(e.target.value)} disabled={!sourceObj}
        />
        <Button variant="outline" onClick={() => setPickerOpen(true)} disabled={!sourceObj}>
          <FolderSearch className="size-4" /> 찾아보기
        </Button>
        <label className="flex items-center gap-1.5 text-sm">
          <Checkbox checked={recursive} onCheckedChange={(v) => setRecursive(v === true)} /> 하위 폴더 포함
        </label>
      </div>

      <div className="flex items-center gap-2">
        <Button variant="outline" onClick={() => run(true)} disabled={!sourceObj || running !== null}>
          <FlaskConical className="size-4" /> {running === "dry" ? "미리보는 중..." : "미리보기 (dry run)"}
        </Button>
        <Button onClick={() => run(false)} disabled={!sourceObj || running !== null}>
          <Upload className="size-4" /> {running === "run" ? "처리 중..." : "일괄 인테이크 실행"}
        </Button>
      </div>

      {sourceObj && (
        <SourcePathPicker
          open={pickerOpen} onOpenChange={setPickerOpen} folderMode
          sourceId={sourceObj.source_id} sourceName={sourceObj.name}
          onSelect={(p) => { setPrefix(p); setReport(null) }}
        />
      )}

      {report && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex flex-wrap items-center gap-2 text-sm font-medium">
              배분 리포트 — {report.source_name}:{report.prefix || "(루트)"}
              {report.dry_run && <Badge variant="outline" className="text-sm font-normal">미리보기(저장 없음)</Badge>}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-1.5 text-sm">
              <Badge variant="outline" className="text-sm font-normal tabular-nums">검사 {report.scanned}개</Badge>
              {(Object.keys(SCAN_STATUS_META) as ScanItemStatus[]).map((st) =>
                report.counts[st] ? (
                  <Badge key={st} variant={SCAN_STATUS_META[st].variant} className="text-sm font-normal tabular-nums">
                    {SCAN_STATUS_META[st].label} {report.counts[st]}
                  </Badge>
                ) : null
              )}
              {report.truncated && (
                <span className="text-muted-foreground">
                  일부만 처리했습니다(상한 초과) — 같은 요청을 다시 실행하면 남은 파일이 처리됩니다.
                </span>
              )}
            </div>
            <div className="max-h-96 overflow-y-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>경로</TableHead>
                    <TableHead className="w-28 text-center">상태</TableHead>
                    <TableHead className="w-44">지식베이스</TableHead>
                    <TableHead className="w-20 text-center">신뢰도</TableHead>
                    <TableHead>비고</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {report.items.map((it, i) => (
                    <TableRow key={i}>
                      <TableCell className="max-w-0">
                        <span className="block truncate font-mono text-sm" title={it.path}>{it.path}</span>
                      </TableCell>
                      <TableCell className="text-center"><ScanStatusBadge status={it.status} /></TableCell>
                      <TableCell className="text-sm">
                        {it.collection_name ?? (it.collection_id != null ? `#${it.collection_id}` : "—")}
                      </TableCell>
                      <TableCell className="text-center text-sm tabular-nums">
                        {it.confidence != null ? it.confidence.toFixed(3) : "—"}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        <span className="flex flex-wrap items-center gap-1">
                          {it.review && <Badge variant="warning" className="text-sm font-normal">검토 필요</Badge>}
                          {it.fallback_used && <Badge variant="warning" className="text-sm font-normal">폴백</Badge>}
                          {it.detail}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {!report.dry_run && (report.counts.routed ?? 0) > 0 && (
              <p className="text-sm text-muted-foreground">
                등록된 문서의 인제스천 진행 상황은 <Link href="/dashboard/jobs" className="text-primary hover:underline">잡 모니터링</Link>에서 확인하십시오.
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 사용법 탭
// ---------------------------------------------------------------------------

function GuideTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={Network}>문서 라우팅 — 지식베이스 자동 선택</Heading>
        <p className="text-muted-foreground">
          업로드한 문서를 <span className="font-medium text-foreground">어느 지식베이스(컬렉션)에 넣을지</span> 자동으로 정합니다. 분류
          (<span className="font-mono text-sm">doc_type</span> 등)는 &lsquo;문서가 무엇인가&rsquo;를 정할 뿐이고, 라우팅은 그 위에서 &lsquo;그래서 어디로 보낼지&rsquo;를 정하는 정책입니다.
          규칙 라우터는 <span className="font-medium text-foreground">파싱·임베딩 전</span> 파일명/메타데이터만으로 결정되어 무비용이고,
          <span className="font-mono text-sm"> content_embedding</span> 단계를 추가한 경우에만 선두 텍스트 추출+임베딩 1회 비용이 듭니다.
        </p>
      </section>

      <section>
        <Sub icon={GitBranch}>① 정책 구성 — 라우터 단계</Sub>
        <p className="text-muted-foreground">
          정책은 라우터 단계들의 목록입니다. 라우터는 두 부류입니다 —{" "}
          <span className="font-medium text-foreground">규칙 라우터</span>(무비용·결정적, 컬렉션을 직접 지정)와{" "}
          <span className="font-medium text-foreground">내용 기반 라우터</span>(문서 내용을 읽고 후보를 추론).
        </p>
        <Bullets
          items={[
            <><span className="font-mono text-sm">path_rule</span> — 스토리지 소스 내 경로 프리픽스/글롭(예: <span className="font-mono text-sm">contracts/</span> → 계약). 드롭존 규약이 있으면 가장 정확합니다.</>,
            <><span className="font-mono text-sm">filename_rule</span> — 파일명/경로 키워드·정규식.</>,
            <><span className="font-mono text-sm">extension_rule</span> — 파일 확장자(hwp/hwpx → HWP 문서고 등).</>,
            <><span className="font-mono text-sm">metadata_match</span> — 자동분류 결과(doc_type)·출처 시스템 등 메타데이터 값 동등 비교.</>,
            <><span className="font-mono text-sm">content_embedding</span>(내용 임베딩) — 문서 선두 텍스트와 컬렉션별 기준 벡터의 유사도로 후보를 냅니다. 컬렉션을 직접 지정하지 않는 대신, 먼저 <span className="font-medium text-foreground">내용 라우팅 기준</span> 탭에서 기준 벡터를 계산해 두어야 합니다. 비용: 문서당 텍스트 추출+임베딩 1회.</>,
            <><span className="font-mono text-sm">llm_classify</span>(LLM 분류) — 컬렉션 이름·설명 목록을 사내 LLM 에 주고 zero-shot 으로 고르게 합니다. 내용이 비슷해도 <span className="font-medium text-foreground">용도로 갈리는 경계 케이스</span>·기준 벡터가 없는 신규 컬렉션에 유효합니다. 비용: 문서당 LLM 1회(수 초) — 반드시 맨 마지막 단계로. 서버/모델은 전역 LLM 설정 또는 단계 설정으로 지정합니다.</>,
            <><span className="font-mono text-sm">custom_function</span>(사용자 정의 함수) — 관리자가 작성한 Python <span className="font-mono text-sm">route(doc)</span> 함수로 직접 라우팅합니다. 규칙·유사도로 표현이 안 되는 조직 고유 로직(예: 파일명의 사업번호 파싱)의 <span className="font-medium text-foreground">탈출구</span>입니다. 코드는 정책 버전과 함께 저장·롤백되며, import 금지·샌드박스(별도 프로세스, 시간/메모리 제한)에서 실행됩니다.</>,
          ]}
        />
        <p className="text-muted-foreground">
          권장 배치는 <span className="font-medium text-foreground">비용 사다리</span>입니다 — 정확·무비용 규칙을 위에, 비싼 판단을 아래에:{" "}
          <span className="font-mono text-sm">path_rule → filename_rule → metadata_match → content_embedding → llm_classify → 폴백</span>.
          이렇게 두면 대부분의 문서는 규칙에서 무비용으로 확정되고, 규칙을 통과 못 한 문서만 내용/LLM 비용을 씁니다.
        </p>
      </section>

      <section>
        <Sub icon={GitBranch}>② 정책 구성 — 조합·폴백·검토</Sub>
        <Bullets
          items={[
            <><span className="font-mono text-sm">first_match</span>(캐스케이드) — 위에서부터 실행해 후보 점수가 그 단계의 <span className="font-medium text-foreground">최소 신뢰도(min_confidence)</span> 이상이면 즉시 확정하고 종료. 아래 단계(비싼 것)는 호출되지 않습니다.</>,
            <><span className="font-mono text-sm">weighted_vote</span>(앙상블) — 모든 단계를 실행해 컬렉션별로 점수×<span className="font-medium text-foreground">가중치(weight)</span> 를 합산, 최댓값을 채택. 여러 약한 신호를 합칠 때 씁니다.</>,
            <><span className="font-medium text-foreground">폴백 컬렉션</span> — 어느 단계도 확정하지 못하면 보낼 미분류/Inbox. 없으면 인테이크가 422 로 거부됩니다.</>,
            <><span className="font-medium text-foreground">검토 임계(review_below)</span> — 최종 신뢰도가 이 값 미만이거나 폴백이 쓰이면 결정은 유지하되 &lsquo;검토 필요(review)&rsquo;로 기록되어 <span className="font-medium text-foreground">검토 대기</span> 탭에 쌓입니다. 거기서 근거(trace)를 보고 맞음 확인하거나 올바른 지식베이스로 재배정(이동+재색인)하세요. 같은 신호(확장자·파일명 키워드·문서 유형·소스 경로)가 같은 곳으로 반복 수정되면 하단 <span className="font-medium text-foreground">규칙 제안</span>이 뜨고, 1클릭으로 정책 새 버전에 반영할 수 있습니다.</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={Network}>③ 내용 라우팅 기준 (기준 벡터)</Sub>
        <p className="text-muted-foreground">
          <span className="font-mono text-sm">content_embedding</span> 이 비교할 컬렉션별 기준 벡터(centroid)를 관리합니다.
          각 컬렉션의 <span className="font-medium text-foreground">최근 청크 샘플</span>(없으면 컬렉션 설명)을 전역 임베딩 설정으로 계산하며,
          표에서 상태(유효/미계산/재계산 필요)·계산 값·계산 시간을 확인합니다. 재계산이 필요한 시점: 새 문서가 충분히 쌓였을 때,
          컬렉션을 새로 만들었을 때, <span className="font-medium text-foreground">전역 임베딩 설정을 바꿨을 때</span>(기존 값은 &lsquo;재계산 필요&rsquo;로 표시되고 라우팅에서 자동 제외).
        </p>
      </section>

      <section>
        <Sub icon={FlaskConical}>④ 테스트로 검증</Sub>
        <p className="text-muted-foreground">
          <span className="font-medium text-foreground">라우팅 테스트</span> 탭에서 파일을 올리면 저장 없이 어디로 갈지와 라우터별 점수(trace)를 미리 봅니다 —
          내용 임베딩은 <span className="font-mono text-sm">cos=0.77 (chunks)</span>, LLM 은 <span className="font-mono text-sm">llm:&lt;모델&gt;</span> 형태로 근거가 남습니다.
          정책 저장 전·후로 확인하십시오.
        </p>
      </section>

      <section>
        <Sub icon={FileUp}>⑤ 인테이크 — 수동·자동</Sub>
        <p className="text-muted-foreground">
          <span className="font-medium text-foreground">인테이크</span> 탭은 컬렉션을 지정하지 않고 문서를 넣습니다 — 파일 업로드 또는{" "}
          <span className="font-medium text-foreground">&lsquo;소스에서 가져오기&rsquo;</span>(등록된 <Link href="/dashboard/storage-sources" className="text-primary hover:underline">스토리지 소스</Link>의
          경로 참조, 원본은 스냅샷 복사). <Link href="/dashboard/storage-sources" className="text-primary hover:underline">소스 워치(자동 수집)</Link>가
          주기 스캔으로 가져오는 문서에도 같은 활성 정책이 적용됩니다. 정책이 지식베이스를 정해 곧바로 등록·인제스천하며,
          이후 처리는 <Link href="/dashboard/jobs" className="text-primary hover:underline">잡 모니터링</Link>에서 추적합니다.
        </p>
      </section>

      <section>
        <Sub icon={History}>⑥ 버전 관리</Sub>
        <p className="text-muted-foreground">
          정책 저장은 항상 <span className="font-medium text-foreground">새 버전을 추가</span>합니다(기존 버전 불변).
          라우팅 정책 탭 하단의 <span className="font-medium text-foreground">버전 이력</span>에서 단계 수·메모·작성자를 확인하고,
          문제가 생기면 <span className="font-medium text-foreground">롤백</span>으로 활성 버전 포인터만 되돌립니다(새 버전 생성 없이 즉시 적용).
          모든 인테이크 결정에는 결정 당시의 정책 버전이 기록됩니다.
        </p>
      </section>

      <Callout icon={RotateCcw}>
        지식베이스는 생성 시 <span className="font-medium text-foreground">임베딩 공간이 고정</span>되므로, 잘못 라우팅된 문서를 다른 지식베이스로 옮기려면
        <span className="font-medium text-foreground"> 재인제스트(재임베딩)</span>가 필요합니다. 그래서 폴백·검토 임계 설정이 중요합니다.
      </Callout>
    </TabShell>
  )
}
