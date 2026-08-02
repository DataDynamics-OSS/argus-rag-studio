// Playground — 질의 → 하이브리드 검색(청크+점수) + 인용 포함 답변 생성.
// 검색·리랭크·생성 파이프라인을 한 화면에서 확인/튜닝한다.
"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { FileText, Filter, Layers, ListFilter, Search, Sparkles } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Textarea } from "@workspace/ui/components/textarea"
import { Label } from "@workspace/ui/components/label"
import { Badge } from "@workspace/ui/components/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@workspace/ui/components/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { Checkbox } from "@workspace/ui/components/checkbox"
import { TabsContent, TabsList, TabsTrigger } from "@workspace/ui/components/tabs"
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard-header"
import { Bullets, Callout, Heading, Sub, TabShell } from "@/components/doc-blocks"
import { listCollections } from "@/features/collections/api"
import type { Collection } from "@/features/collections/data/schema"
import { listPipelines } from "@/features/pipelines/api"
import type { Pipeline } from "@/features/pipelines/data/schema"
import { query, queryFederated, search, searchFederated } from "@/features/search/api"
import type {
  ChunkHit,
  Citation,
  CollectionContribution,
  QueryResult,
  SearchMode,
} from "@/features/search/data/schema"
import { FeedbackButtons } from "@/features/feedback/feedback-buttons"
import { EvidencePageButton } from "@/features/search/components/evidence-page-button"
import { ChunkImageRefs, ImageTypeBadges } from "@/features/search/components/image-type-badges"
import {
  MetadataFilterBar,
  rowsToFilters,
  type FilterRow,
} from "@/features/search/components/metadata-filter-bar"
import { DocumentInspectDialog } from "@/features/documents/components/document-inspect-dialog"
import { UrlTabs } from "@/components/url-tabs"

type Scope = "single" | "federated"

// 질의어가 청크에 직접 등장하는지(키워드 매칭 여부). 표시 전용 — 랭킹/LLM 컨텍스트에 영향 없음.
function chunkHasKeyword(text: string, query: string): boolean {
  const terms = query.toLowerCase().split(/\s+/).map((t) => t.trim()).filter((t) => t.length >= 2)
  if (terms.length === 0) return false
  const lower = text.toLowerCase()
  return terms.some((t) => lower.includes(t))
}

export default function PlaygroundPage() {
  return (
    <>
      <DashboardHeader title="Playground" />
      <div className="flex flex-1 flex-col p-4">
        <UrlTabs defaultValue="query" className="gap-4">
          <TabsList>
            <TabsTrigger value="query">검색·답변</TabsTrigger>
            <TabsTrigger value="guide">사용법</TabsTrigger>
          </TabsList>
          <TabsContent value="query">
            <PlaygroundQueryTab />
          </TabsContent>
          <TabsContent value="guide">
            <PlaygroundUsageTab />
          </TabsContent>
        </UrlTabs>
      </div>
    </>
  )
}

function PlaygroundQueryTab() {
  const [collections, setCollections] = useState<Collection[]>([])
  const [collectionId, setCollectionId] = useState<string>("")
  const [scope, setScope] = useState<Scope>("single")
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [q, setQ] = useState("")
  const [mode, setMode] = useState<SearchMode>("hybrid")
  const [rerank, setRerank] = useState(false)
  const [pipelines, setPipelines] = useState<Pipeline[]>([])
  const [pipelineId, setPipelineId] = useState("") // "" = 사용 안 함(직접 설정)
  const [filterRows, setFilterRows] = useState<FilterRow[]>([])
  const [loading, setLoading] = useState<"search" | "answer" | null>(null)

  const [hits, setHits] = useState<ChunkHit[]>([])
  const [answer, setAnswer] = useState<string>("")
  const [citations, setCitations] = useState<Citation[]>([])
  const [answered, setAnswered] = useState<{ query: string; traceId: string | null } | null>(null)
  const [contributions, setContributions] = useState<CollectionContribution[]>([])
  const [groupByDoc, setGroupByDoc] = useState(true)
  const [expandedDocs, setExpandedDocs] = useState<Set<number>>(new Set())
  const [inspectDoc, setInspectDoc] = useState<{ uuid: string; name: string; text: string } | null>(null)
  const [reranked, setReranked] = useState(false) // 표시 score 가 리랭커 점수인지(라벨 표기용)

  const selectedMetric = collections.find((c) => String(c.id) === collectionId)?.distance_metric
  const collName = (id: number) => collections.find((c) => c.id === id)?.name ?? `#${id}`

  // 같은 문서의 청크를 묶는다(통합 검색에서도 document_id 는 전역 PK 라 안전). 그룹·내부 모두 랭크순.
  const groups = useMemo(() => {
    const map = new Map<number, ChunkHit[]>()
    for (const h of hits) {
      const arr = map.get(h.document_id)
      if (arr) arr.push(h)
      else map.set(h.document_id, [h])
    }
    return Array.from(map, ([documentId, gh]) => ({
      documentId,
      documentName: gh[0]!.document_name,
      documentUuid: gh[0]!.document_uuid,
      collectionId: gh[0]!.collection_id,
      hits: gh,
      best: Math.max(...gh.map((x) => x.score)),
    }))
  }, [hits])

  function toggleDoc(id: number) {
    setExpandedDocs((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // 청크 1건 렌더. showDoc=평면 뷰(문서명/컬렉션 표시), bare=그룹 카드 안쪽(자체 테두리 없음).
  function renderChunk(h: ChunkHit, opts: { rank?: number; showDoc?: boolean; bare?: boolean } = {}) {
    return (
      <div key={h.chunk_id} className={opts.bare ? "py-2.5" : "rounded-md border p-3"}>
        <div className="mb-1.5 flex items-center gap-2 text-xs text-muted-foreground">
          {opts.rank != null && <Badge variant="outline" className="h-5">#{opts.rank}</Badge>}
          {chunkHasKeyword(h.text, q) ? (
            <Badge variant="secondary" className="h-5 shrink-0 border-emerald-200 bg-emerald-50 font-normal text-emerald-700"
              title="질의어가 이 청크에 직접 등장합니다(키워드 매칭).">키워드</Badge>
          ) : (
            <Badge variant="outline" className="h-5 shrink-0 font-normal text-muted-foreground"
              title="질의어가 직접 없지만 의미가 유사해 검색된 결과입니다(의미 매칭).">의미</Badge>
          )}
          {opts.showDoc && scope === "federated" && (
            <Badge variant="secondary" className="h-5 font-normal">{collName(h.collection_id)}</Badge>
          )}
          {opts.showDoc && <FileText className="size-3.5" />}
          {opts.showDoc && <span className="font-medium text-foreground">{h.document_name}</span>}
          {opts.showDoc && <ImageTypeBadges types={h.document_image_types} />}
          <span>seq {h.seq}</span>
          <EvidencePageButton chunkId={h.chunk_id} documentName={h.document_name} />
          <span className="ml-auto">{reranked ? "rerank" : "score"} {h.score.toFixed(4)}</span>
        </div>
        <p className="whitespace-pre-wrap text-sm text-muted-foreground">{h.text}</p>
        <ChunkImageRefs refs={h.image_refs} />
      </div>
    )
  }
  // 단일이면 컬렉션 1개, 통합이면 선택된 다수
  const canRun = scope === "single" ? !!collectionId : selectedIds.length > 0

  useEffect(() => {
    listCollections({ page_size: 100 })
      .then((res) => {
        setCollections(res.items)
        if (res.items.length) setCollectionId(String(res.items[0]!.id))
      })
      .catch(() => {})
    listPipelines()
      .then(setPipelines)
      .catch(() => {})
  }, [])

  // 파이프라인 선택 시 검색 방식·리랭크는 파이프라인 활성 버전 설정이 결정한다(요청 필드 무시).
  const usingPipeline = pipelineId !== ""

  const reset = () => {
    setHits([])
    setAnswer("")
    setCitations([])
    setAnswered(null)
    setContributions([])
    setReranked(false)
  }

  const toggleId = (id: number) =>
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))

  const runSearch = useCallback(async () => {
    if (!canRun || !q.trim()) return
    setLoading("search")
    reset()
    try {
      const filters = rowsToFilters(filterRows)
      const f = filters.length ? { filters } : {}
      const p = pipelineId ? { pipeline_id: Number(pipelineId) } : {}
      if (scope === "federated") {
        const res = await searchFederated({ query: q, collection_ids: selectedIds, mode, rerank, ...f, ...p })
        setHits(res.hits)
        setContributions(res.contributions)
        setReranked(res.reranked)
      } else {
        const res = await search(Number(collectionId), { query: q, mode, rerank, ...f, ...p })
        setHits(res.hits)
        setReranked(res.reranked)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "검색 실패")
    } finally {
      setLoading(null)
    }
  }, [scope, collectionId, selectedIds, canRun, q, mode, rerank, pipelineId, filterRows])

  const runAnswer = useCallback(async () => {
    if (!canRun || !q.trim()) return
    setLoading("answer")
    reset()
    try {
      const filters = rowsToFilters(filterRows)
      const f = filters.length ? { filters } : {}
      const p = pipelineId ? { pipeline_id: Number(pipelineId) } : {}
      if (scope === "federated") {
        const res = await queryFederated({ query: q, collection_ids: selectedIds, mode, rerank, ...f, ...p })
        setAnswer(res.answer)
        setCitations(res.citations)
        setHits(res.hits)
        setContributions(res.contributions)
        setReranked(res.reranked)
        setAnswered({ query: q, traceId: null })
      } else {
        const res: QueryResult = await query(Number(collectionId), { query: q, mode, rerank, ...f, ...p })
        setAnswer(res.answer)
        setCitations(res.citations)
        setHits(res.hits)
        setReranked(rerank) // 단일 답변 응답엔 reranked 플래그가 없어 요청 플래그로 근사
        setAnswered({ query: q, traceId: res.trace_id })
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "답변 생성 실패")
    } finally {
      setLoading(null)
    }
  }, [scope, collectionId, selectedIds, canRun, q, mode, rerank, pipelineId, filterRows])

  return (
    <div className="flex flex-col gap-4">
        <Card>
          <CardContent className="flex flex-col gap-4 pt-6">
            <div className="grid gap-4 sm:grid-cols-[auto_1fr_auto_auto_auto] sm:items-end">
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">검색 범위</Label>
                <Select value={scope} onValueChange={(v) => setScope(v as Scope)}>
                  <SelectTrigger className="w-36">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="single">단일</SelectItem>
                    <SelectItem value="federated">통합(여러 KB)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">지식베이스</Label>
                {scope === "single" ? (
                  <Select value={collectionId} onValueChange={setCollectionId}>
                    <SelectTrigger>
                      <SelectValue placeholder="컬렉션 선택" />
                    </SelectTrigger>
                    <SelectContent>
                      {collections.map((c) => (
                        <SelectItem key={c.id} value={String(c.id)}>
                          {c.name} ({c.document_count})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <div className="flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border p-1.5">
                    {collections.map((c) => {
                      const on = selectedIds.includes(c.id)
                      return (
                        <button
                          key={c.id}
                          type="button"
                          onClick={() => toggleId(c.id)}
                          className={`rounded-full border px-2.5 py-0.5 text-xs transition-colors ${
                            on
                              ? "border-primary bg-primary text-primary-foreground"
                              : "border-input text-muted-foreground hover:bg-accent"
                          }`}
                        >
                          {c.name}
                        </button>
                      )
                    })}
                    {collections.length === 0 && (
                      <span className="px-1 text-xs text-muted-foreground">컬렉션 없음</span>
                    )}
                  </div>
                )}
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">검색 방식</Label>
                <Select value={mode} onValueChange={(v) => setMode(v as SearchMode)} disabled={usingPipeline}>
                  <SelectTrigger className="w-36">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="hybrid">하이브리드</SelectItem>
                    <SelectItem value="vector">벡터</SelectItem>
                    <SelectItem value="lexical">렉시컬</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">파이프라인</Label>
                <Select
                  value={pipelineId || "__none__"}
                  onValueChange={(v) => setPipelineId(v === "__none__" ? "" : v)}
                >
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
              <label className="flex items-center gap-2 pb-2 text-sm">
                <Checkbox checked={rerank} onCheckedChange={(v) => setRerank(!!v)} disabled={usingPipeline} />
                리랭크
              </label>
            </div>
            {usingPipeline && (
              <p className="-mt-1 text-xs text-muted-foreground">
                파이프라인 적용 중 — 검색 방식·리랭크·생성 설정은 선택한 파이프라인의 활성 버전을 따릅니다(위 검색 방식·리랭크 선택은 무시됨).
              </p>
            )}
            {scope === "federated" && (
              <p className="-mt-1 text-xs text-muted-foreground">
                선택한 지식베이스를 각자 임베딩으로 검색해 RRF로 병합합니다
                {rerank ? " · 병합 후보를 리랭커로 재정렬" : ""}. ({selectedIds.length}개 선택)
              </p>
            )}

            <Textarea
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="질문을 입력하세요..."
              className="min-h-20"
            />
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">
                메타데이터 필터{scope === "federated" ? " (모든 선택 KB에 동일 적용)" : ""}
              </Label>
              <MetadataFilterBar rows={filterRows} onChange={setFilterRows} />
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={runSearch} disabled={!!loading || !canRun}>
                <Search className="size-4" />
                {loading === "search" ? "검색 중..." : "검색만"}
              </Button>
              <Button onClick={runAnswer} disabled={!!loading || !canRun}>
                <Sparkles className="size-4" />
                {loading === "answer" ? "생성 중..." : "답변 생성"}
              </Button>
            </div>
          </CardContent>
        </Card>

        {answer && (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">답변</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{answer}</p>
              {citations.length > 0 && (
                <div className="border-t pt-3">
                  <p className="mb-2 text-xs font-medium text-muted-foreground">출처</p>
                  <div className="flex flex-col gap-2">
                    {citations.map((c) => (
                      <div key={c.marker} className="flex gap-2 text-xs">
                        <Badge variant="secondary" className="h-5 shrink-0">
                          [{c.marker}]
                        </Badge>
                        <div className="min-w-0">
                          <span className="font-medium">{c.document_name}</span>
                          <p className="truncate text-muted-foreground">{c.text}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {answered && scope === "single" && (
                <div className="border-t pt-3">
                  <FeedbackButtons
                    query={answered.query}
                    answer={answer}
                    collectionId={collectionId ? Number(collectionId) : null}
                    traceId={answered.traceId}
                  />
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {contributions.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm font-medium">
                <Layers className="size-4" /> 컬렉션별 기여
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-1.5 text-xs">
              {contributions.map((c) => (
                <div key={c.collection_id} className="flex items-center gap-2">
                  <span className="font-medium text-foreground">{c.name}</span>
                  <span className="font-mono text-muted-foreground">{c.embedding_model}</span>
                  {c.status === "ok" ? (
                    <Badge variant="secondary" className="h-5 font-normal">
                      후보 {c.candidates} · 최종 {c.in_final}
                    </Badge>
                  ) : (
                    <Badge variant="destructive" className="h-5 font-normal">
                      실패{c.error ? `: ${c.error}` : ""}
                    </Badge>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        {hits.length > 0 && (
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle className="text-sm font-medium">
                  검색 결과 — 문서 {groups.length} · 청크 {hits.length}
                </CardTitle>
                <div className="flex items-center gap-1.5">
                  <Badge variant="outline" className="h-5 font-normal">
                    {mode === "hybrid" ? "하이브리드" : mode === "vector" ? "벡터" : "렉시컬"}
                  </Badge>
                  {scope === "single" && mode !== "lexical" && selectedMetric && (
                    <Badge variant="secondary" className="h-5 font-normal">
                      거리: {selectedMetric}
                    </Badge>
                  )}
                  {scope === "federated" && (
                    <Badge variant="secondary" className="h-5 font-normal">
                      통합 · RRF
                    </Badge>
                  )}
                  <label className="ml-1 flex cursor-pointer select-none items-center gap-1.5 text-xs text-muted-foreground">
                    <Checkbox checked={groupByDoc} onCheckedChange={(v) => setGroupByDoc(!!v)} />
                    문서로 묶기
                  </label>
                </div>
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {groupByDoc
                ? groups.map((g, gi) => {
                    const open = expandedDocs.has(g.documentId)
                    const rest = g.hits.slice(1)
                    return (
                      <div key={g.documentId} className="overflow-hidden rounded-md border">
                        <div className="flex items-center gap-2 border-b bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                          <Badge variant="outline" className="h-5">#{gi + 1}</Badge>
                          {scope === "federated" && (
                            <Badge variant="secondary" className="h-5 shrink-0 font-normal">{collName(g.collectionId)}</Badge>
                          )}
                          <FileText className="size-3.5 shrink-0" />
                          <span className="truncate font-medium text-foreground">{g.documentName}</span>
                          <Badge variant="secondary" className="h-5 shrink-0 font-normal">청크 {g.hits.length}</Badge>
                          <ImageTypeBadges types={g.hits[0]!.document_image_types} />
                          {g.documentUuid && (
                            <button
                              onClick={() => setInspectDoc({ uuid: g.documentUuid, name: g.documentName, text: g.hits[0]!.text })}
                              className="shrink-0 text-primary underline-offset-2 hover:underline"
                            >
                              문서 전체 보기
                            </button>
                          )}
                          <span className="ml-auto shrink-0 tabular-nums">최고 score {g.best.toFixed(4)}</span>
                        </div>
                        <div className="divide-y px-3">
                          {renderChunk(g.hits[0]!, { bare: true })}
                          {open && rest.map((h) => renderChunk(h, { bare: true }))}
                        </div>
                        {rest.length > 0 && (
                          <button
                            onClick={() => toggleDoc(g.documentId)}
                            className="w-full border-t px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted/40"
                          >
                            {open ? "접기" : `이 문서의 나머지 청크 ${rest.length}개 보기`}
                          </button>
                        )}
                      </div>
                    )
                  })
                : hits.map((h, i) => renderChunk(h, { rank: i + 1, showDoc: true }))}
            </CardContent>
          </Card>
        )}

        <DocumentInspectDialog
          documentId={inspectDoc?.uuid ?? null}
          documentName={inspectDoc?.name ?? ""}
          highlightText={inspectDoc?.text}
          open={inspectDoc !== null}
          onOpenChange={(o) => !o && setInspectDoc(null)}
        />
    </div>
  )
}

// ---------------------------------------------------------------------------
// 사용법
// ---------------------------------------------------------------------------

function PlaygroundUsageTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={Search}>Playground — 검색·답변을 직접 실험</Heading>
        <p className="text-muted-foreground">
          Playground는 질문을 넣어 <span className="font-medium text-foreground">검색 결과와 생성 답변을 즉석에서
          확인·튜닝</span>하는 곳입니다. 검색 방식·리랭크·필터를 바꿔 가며 무엇이 올라오는지 눈으로 보고, 운영에 반영하기
          전에 설정을 다듬습니다. 여기서 바꾸는 값은 <span className="font-medium text-foreground">질의 시점</span> 설정이라
          재인덱싱이 필요 없습니다.
        </p>
      </section>

      <section>
        <Sub icon={Sparkles}>① 검색만 vs 답변 생성</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">검색만</span> — 질의에 맞는 청크와 점수만 가져옵니다. 검색 품질 자체를 점검할 때 쓰십시오(LLM 비용 없음).</>,
            <><span className="font-medium text-foreground">답변 생성</span> — 검색한 근거로 LLM이 인용([n]) 포함 답변을 만듭니다. 검색+생성 전체를 확인합니다.</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={ListFilter}>② 검색 옵션</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">검색 범위</span> — 단일(KB 하나) / 통합(여러 KB를 각자 임베딩으로 검색해 RRF 병합).</>,
            <><span className="font-medium text-foreground">검색 방식</span> — 하이브리드(의미+키워드) / 벡터(의미) / 렉시컬(키워드). 확신이 없으면 하이브리드를 쓰십시오.</>,
            <><span className="font-medium text-foreground">리랭크</span> — 1차 결과를 한 번 더 정밀 재정렬해 상위 정확도를 높입니다(선택).</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={Filter}>③ 메타데이터 필터</Sub>
        <p className="text-muted-foreground">
          문서 메타데이터(작성일·카테고리 등)로 검색 범위를 좁힙니다. 통합 검색에서는 선택한 모든 지식베이스에 동일하게
          적용됩니다. 원하는 문서군만 대상으로 두면 정확도가 올라갑니다.
        </p>
      </section>

      <section>
        <Sub icon={FileText}>④ 결과 읽는 법</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">키워드 / 의미</span> 배지 — 질의어가 청크에 직접 등장하면 &lsquo;키워드&rsquo;, 뜻으로만 유사하면 &lsquo;의미&rsquo;입니다(표시 전용, 랭킹엔 영향 없음).</>,
            <><span className="font-medium text-foreground">score / rerank</span> — 표시된 점수가 1차 검색 점수인지 리랭커 점수인지 라벨로 구분됩니다.</>,
            <><span className="font-medium text-foreground">문서로 묶기</span> — 같은 문서의 여러 청크를 한 카드로 묶어 봅니다. <span className="font-medium text-foreground">문서 전체 보기</span>로 원문을 확인하십시오.</>,
            <><span className="font-medium text-foreground">컬렉션별 기여</span>(통합) — 각 KB가 후보를 몇 개 내고 최종에 몇 개 들어갔는지 보여줍니다.</>,
          ]}
        />
      </section>

      <Callout>
        답변 아래 <span className="font-medium text-foreground">👍/👎</span>로 품질을 기록하면 <Link href="/dashboard/feedback" className="text-primary hover:underline">피드백</Link>에
        쌓입니다. 좋은 설정을 찾았다면 <Link href="/dashboard/pipelines" className="text-primary hover:underline">파이프라인</Link>에
        버전으로 저장하고, <Link href="/dashboard/evaluation" className="text-primary hover:underline">평가</Link>로 골든셋
        점수를 비교해 확정하십시오. 멀티턴 대화로 써 보려면 <Link href="/dashboard/chat" className="text-primary hover:underline">Chat</Link>을
        이용하십시오.
      </Callout>
    </TabShell>
  )
}
