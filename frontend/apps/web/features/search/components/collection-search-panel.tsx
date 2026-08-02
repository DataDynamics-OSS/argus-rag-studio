/**
 * 지식베이스 상세 화면용 검색 테스트 패널.
 *
 * 질의를 입력해 `/collections/{id}/search` 를 호출하고 검색된 청크를 보여준다.
 * rerank 플래그를 보내지 않으므로 백엔드는 컬렉션의 rerank_provider 설정을 그대로
 * 적용한다(provider != "none" 이면 리랭크). 따라서 메타데이터에서 리랭커를 바꾼 뒤
 * 이 패널에서 바로 결과 순서 변화를 확인할 수 있다.
 *
 * 청크 본문은 Markdown 으로 보이면 렌더링하고, 평문이면 질의어를 노란색으로 강조한다.
 */
"use client"

import { Fragment, useMemo, useState, type ReactNode } from "react"
import { FileSearch, FileText, Search } from "lucide-react"
import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"

import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import { Checkbox } from "@workspace/ui/components/checkbox"
import { Input } from "@workspace/ui/components/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@workspace/ui/components/tooltip"
import { toast } from "sonner"
import { EvidencePageButton } from "@/features/search/components/evidence-page-button"
import { ChunkImageRefs, ImageTypeBadges } from "@/features/search/components/image-type-badges"
import {
  MetadataFilterBar,
  rowsToFilters,
  type FilterRow,
} from "@/features/search/components/metadata-filter-bar"
import { DocumentInspectDialog } from "@/features/documents/components/document-inspect-dialog"
import { search } from "@/features/search/api"
import type { ChunkHit, SearchMode, SearchResult } from "@/features/search/data/schema"

const MODE_LABEL: Record<SearchMode, string> = {
  hybrid: "하이브리드",
  vector: "벡터",
  lexical: "렉시컬",
}

// score 의미 설명. 리랭크 적용 시에는 표시 점수 = 리랭커 점수(순서와 일치).
function scoreDesc(reranked: boolean): string {
  if (reranked) {
    return (
      "리랭커 점수 — cross-encoder/LLM 이 (질의, 청크)를 직접 채점한 최종 관련도입니다.\n" +
      "표시 점수 기준으로 정렬돼 있어 순서와 점수가 일치합니다(높을수록 관련 높음).\n" +
      "점수 범위는 리랭커 모델에 따라 다릅니다(음수일 수 있음)."
    )
  }
  return (
    "관련도 점수 — 높을수록 질의와 더 유사·관련된 청크입니다.\n" +
    "검색 방식별 의미: 벡터=거리 기반 유사도, 렉시컬=텍스트 일치도(ts_rank), " +
    "하이브리드=RRF 융합 점수."
  )
}

// 청크 본문이 Markdown 으로 보이는지 추정(헤딩·표·목록·코드·강조·링크).
function looksLikeMarkdown(t: string): boolean {
  return (
    /(^|\n)\s{0,3}#{1,6}\s/.test(t) ||
    /(^|\n)\s*[-*+]\s+/.test(t) ||
    /(^|\n)\s*\d+\.\s+/.test(t) ||
    /\|[^\n]*\|[^\n]*\|/.test(t) ||
    /```/.test(t) ||
    /\*\*[^*\n]+\*\*/.test(t) ||
    /\[[^\]]+\]\([^)]+\)/.test(t)
  )
}

// 평문 청크에서 질의어를 노란색 배경으로 강조.
function highlightText(text: string, query: string): ReactNode {
  const terms = Array.from(
    new Set(
      query
        .toLowerCase()
        .split(/\s+/)
        .map((t) => t.trim())
        .filter((t) => t.length >= 2),
    ),
  )
  if (terms.length === 0) return text
  const escaped = terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
  const re = new RegExp(`(${escaped.join("|")})`, "gi")
  const lower = new Set(terms)
  return text.split(re).map((part, i) =>
    lower.has(part.toLowerCase()) ? (
      <mark key={i} className="rounded bg-yellow-200 px-0.5 text-black">
        {part}
      </mark>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    ),
  )
}

// Markdown 요소 스타일(typography 플러그인 미사용 → 요소별 직접 지정).
const MD: Components = {
  h1: ({ node, ...p }) => <h1 className="mb-1 mt-2 text-base font-semibold" {...p} />,
  h2: ({ node, ...p }) => <h2 className="mb-1 mt-2 text-sm font-semibold" {...p} />,
  h3: ({ node, ...p }) => <h3 className="mb-1 mt-2 text-sm font-semibold" {...p} />,
  h4: ({ node, ...p }) => <h4 className="mb-1 mt-2 text-sm font-semibold" {...p} />,
  p: ({ node, ...p }) => <p className="my-1 leading-relaxed" {...p} />,
  ul: ({ node, ...p }) => <ul className="my-1 list-disc pl-5" {...p} />,
  ol: ({ node, ...p }) => <ol className="my-1 list-decimal pl-5" {...p} />,
  li: ({ node, ...p }) => <li className="my-0.5" {...p} />,
  a: ({ node, ...p }) => (
    <a className="text-primary underline" target="_blank" rel="noreferrer" {...p} />
  ),
  code: ({ node, ...p }) => <code className="rounded bg-muted px-1 py-0.5 text-xs" {...p} />,
  pre: ({ node, ...p }) => (
    <pre className="my-1 overflow-x-auto rounded bg-muted p-2 text-xs" {...p} />
  ),
  table: ({ node, ...p }) => (
    <div className="my-1 overflow-x-auto">
      <table className="w-full border-collapse text-xs" {...p} />
    </div>
  ),
  th: ({ node, ...p }) => (
    <th className="border bg-muted/60 px-2 py-1 text-left font-medium" {...p} />
  ),
  td: ({ node, ...p }) => <td className="border px-2 py-1 align-top" {...p} />,
  blockquote: ({ node, ...p }) => (
    <blockquote className="my-1 border-l-2 pl-3 text-muted-foreground" {...p} />
  ),
}

// score + 설명 툴팁
function ScoreTip({ score, reranked }: { score: number; reranked: boolean }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="ml-auto shrink-0 cursor-help tabular-nums underline decoration-dotted decoration-muted-foreground/50 underline-offset-2">
          {reranked ? "rerank" : "score"} {score.toFixed(4)}
        </span>
      </TooltipTrigger>
      <TooltipContent side="left" className="max-w-xs whitespace-pre-wrap">
        {scoreDesc(reranked)}
      </TooltipContent>
    </Tooltip>
  )
}

// 청크 본문 — Markdown 이면 렌더, 평문이면 질의어 강조.
function ChunkText({ text, query }: { text: string; query: string }) {
  return looksLikeMarkdown(text) ? (
    <div className="text-sm leading-relaxed">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD}>
        {text}
      </ReactMarkdown>
    </div>
  ) : (
    <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">
      {highlightText(text, query)}
    </p>
  )
}

// 질의어가 청크 본문에 실제로 등장하는지(키워드 매칭 여부). 표시 전용 — 랭킹/LLM 컨텍스트에 영향 없음.
function chunkHasKeyword(text: string, query: string): boolean {
  const terms = query.toLowerCase().split(/\s+/).map((t) => t.trim()).filter((t) => t.length >= 2)
  if (terms.length === 0) return false
  const lower = text.toLowerCase()
  return terms.some((t) => lower.includes(t))
}

// 키워드/의미 매칭 배지 — 이 청크가 질의어를 직접 포함하는지 알려준다(품질 신호 아님, 정보 표시).
function MatchBadge({ hasKeyword }: { hasKeyword: boolean }) {
  return hasKeyword ? (
    <Badge
      variant="secondary"
      className="h-5 shrink-0 border-emerald-200 bg-emerald-50 font-normal text-emerald-700"
      title="질의어가 이 청크에 직접 등장합니다(키워드 매칭)."
    >
      키워드
    </Badge>
  ) : (
    <Badge
      variant="outline"
      className="h-5 shrink-0 font-normal text-muted-foreground"
      title="질의어가 직접 없지만 의미가 유사해 검색된 결과입니다(의미 매칭). 키워드 포함이 곧 더 관련 높음을 뜻하진 않습니다."
    >
      의미
    </Badge>
  )
}

// 청크 1건(메타 행 + 본문). bare=true 면 그룹 카드 안쪽용(자체 테두리 없음).
function ChunkItem({
  h, query, reranked, rank, showDoc = true, bare = false, onInspect,
}: {
  h: ChunkHit
  query: string
  reranked: boolean
  rank?: number
  showDoc?: boolean
  bare?: boolean
  /** 이 청크를 원본 뷰어에서 열기(해당 페이지로 이동 + 하이라이트). */
  onInspect?: () => void
}) {
  return (
    <div className={bare ? "py-2.5" : "rounded-md border p-3 text-black"}>
      <div className="mb-1.5 flex items-center gap-2 text-xs text-muted-foreground">
        {rank != null && (
          <Badge variant="outline" className="h-5">#{rank}</Badge>
        )}
        <MatchBadge hasKeyword={chunkHasKeyword(h.text, query)} />
        {showDoc && <span className="font-medium text-black">{h.document_name}</span>}
        {showDoc && <ImageTypeBadges types={h.document_image_types} />}
        {h.section_path && <span className="truncate">{h.section_path}</span>}
        <EvidencePageButton chunkId={h.chunk_id} documentName={h.document_name} />
        {onInspect && (
          <button
            onClick={onInspect}
            className="inline-flex shrink-0 items-center gap-1 text-primary underline-offset-2 hover:underline"
            title="원본에서 이 청크 위치로 이동(하이라이트)"
          >
            <FileSearch className="size-3.5" />
            원본에서 보기
          </button>
        )}
        <ScoreTip score={h.score} reranked={reranked} />
      </div>
      <ChunkText text={h.text} query={query} />
      <ChunkImageRefs refs={h.image_refs} />
    </div>
  )
}

export function CollectionSearchPanel({
  collectionId,
  distanceMetric,
  rerankProvider,
}: {
  collectionId: number
  distanceMetric: string
  rerankProvider: string
}) {
  const [q, setQ] = useState("")
  const [mode, setMode] = useState<SearchMode>("hybrid")
  const [filterRows, setFilterRows] = useState<FilterRow[]>([])
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<SearchResult | null>(null)
  const [groupByDoc, setGroupByDoc] = useState(true)
  const [expandedDocs, setExpandedDocs] = useState<Set<number>>(new Set())
  const [inspectDoc, setInspectDoc] = useState<{ uuid: string; name: string; text: string } | null>(null)
  const [minScore, setMinScore] = useState("") // 검색 UI 표시 전용 컷오프(빈값=전체). LLM 컨텍스트엔 영향 없음.

  // 최소 점수 이상만 표시(표시 전용 필터 — 검색·랭킹·LLM 컨텍스트는 그대로).
  const shownHits = useMemo(() => {
    const hits = result?.hits ?? []
    const min = minScore.trim() === "" ? null : Number(minScore)
    if (min == null || Number.isNaN(min)) return hits
    return hits.filter((h) => h.score >= min)
  }, [result, minScore])

  // 같은 문서의 청크를 묶는다. 그룹 순서 = 첫 등장(=최고 랭크) 순서, 각 그룹은 랭크순 유지.
  const groups = useMemo(() => {
    const map = new Map<number, ChunkHit[]>()
    for (const h of shownHits) {
      const arr = map.get(h.document_id)
      if (arr) arr.push(h)
      else map.set(h.document_id, [h])
    }
    return Array.from(map, ([documentId, hits]) => ({
      documentId,
      documentName: hits[0]!.document_name,
      documentUuid: hits[0]!.document_uuid,
      hits,
      best: Math.max(...hits.map((x) => x.score)),
    }))
  }, [shownHits])

  function toggleDoc(id: number) {
    setExpandedDocs((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function runSearch() {
    if (!q.trim()) return
    setLoading(true)
    try {
      // rerank 플래그 미전송 → 컬렉션의 rerank_provider 설정이 적용된다.
      const filters = rowsToFilters(filterRows)
      const res = await search(collectionId, {
        query: q,
        mode,
        ...(filters.length ? { filters } : {}),
      })
      setResult(res)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "검색 실패")
    } finally {
      setLoading(false)
    }
  }

  return (
    <TooltipProvider delayDuration={150}>
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") runSearch()
            }}
            placeholder="질의를 입력해 검색 결과·리랭커 효과를 확인하세요..."
            className="text-black"
          />
          <Select value={mode} onValueChange={(v) => setMode(v as SearchMode)}>
            <SelectTrigger className="w-32 shrink-0">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="hybrid">하이브리드</SelectItem>
              <SelectItem value="vector">벡터</SelectItem>
              <SelectItem value="lexical">렉시컬</SelectItem>
            </SelectContent>
          </Select>
          <Button onClick={runSearch} disabled={loading || !q.trim()} className="shrink-0">
            <Search className="size-4" />
            {loading ? "검색 중..." : "검색"}
          </Button>
        </div>

        <MetadataFilterBar rows={filterRows} onChange={setFilterRows} />

        {result && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <Badge variant="outline" className="h-5 font-normal">
                {MODE_LABEL[result.mode as SearchMode] ?? result.mode}
              </Badge>
              {result.mode !== "lexical" && (
                <Badge variant="secondary" className="h-5 font-normal">
                  거리: {distanceMetric}
                </Badge>
              )}
              <Badge variant={result.reranked ? "default" : "outline"} className="h-5 font-normal">
                리랭크: {result.reranked ? `적용(${rerankProvider})` : "없음"}
              </Badge>
              {(result.filters_applied ?? []).map((f, i) => (
                <Badge key={i} variant="secondary" className="h-5 font-normal">
                  필터: {f.field}{" "}
                  {f.op === "range"
                    ? `${f.gte ?? ""}~${f.lte ?? ""}`
                    : Array.isArray(f.value)
                      ? f.value.join("|")
                      : f.value}
                </Badge>
              ))}
              <span className="text-muted-foreground">
                문서 {groups.length}개 · 청크 {shownHits.length}개
                {shownHits.length < result.hits.length && (
                  <span className="text-amber-600"> (숨김 {result.hits.length - shownHits.length})</span>
                )}
              </span>
              <label className="ml-auto flex select-none items-center gap-1.5 text-muted-foreground">
                최소 점수
                <Input
                  type="number"
                  step="0.01"
                  value={minScore}
                  onChange={(e) => setMinScore(e.target.value)}
                  placeholder="전체"
                  className="h-6 w-20 text-xs"
                  title="이 점수 미만의 결과를 검색 목록에서 숨깁니다. 표시 전용 — RAG 답변(LLM 컨텍스트)에는 영향이 없습니다."
                />
              </label>
              <label className="flex cursor-pointer select-none items-center gap-1.5 text-muted-foreground">
                <Checkbox checked={groupByDoc} onCheckedChange={(v) => setGroupByDoc(!!v)} />
                문서로 묶기
              </label>
            </div>

            {result.hits.length === 0 ? (
              <p className="rounded-md border border-dashed px-3 py-6 text-center text-sm text-muted-foreground">
                검색 결과가 없습니다.
              </p>
            ) : shownHits.length === 0 ? (
              <p className="rounded-md border border-dashed px-3 py-6 text-center text-sm text-muted-foreground">
                최소 점수({minScore}) 이상의 결과가 없습니다. 값을 낮추거나 비워 전체를 보세요.
              </p>
            ) : groupByDoc ? (
              <div className="flex flex-col gap-2">
                {groups.map((g, gi) => {
                  const open = expandedDocs.has(g.documentId)
                  const rest = g.hits.slice(1)
                  return (
                    <div key={g.documentId} className="overflow-hidden rounded-md border">
                      <div className="flex items-center gap-2 border-b bg-muted/30 px-3 py-2 text-xs">
                        <Badge variant="outline" className="h-5">#{gi + 1}</Badge>
                        <span className="truncate font-medium text-black">{g.documentName}</span>
                        <Badge variant="secondary" className="h-5 shrink-0 font-normal">청크 {g.hits.length}</Badge>
                        <ImageTypeBadges types={g.hits[0]!.document_image_types} />
                        {g.documentUuid && (
                          <button
                            onClick={() => setInspectDoc({ uuid: g.documentUuid, name: g.documentName, text: g.hits[0]!.text })}
                            className="inline-flex shrink-0 items-center gap-1 text-primary underline-offset-2 hover:underline"
                          >
                            <FileText className="size-3.5" />
                            문서 전체 보기
                          </button>
                        )}
                        <span className="ml-auto shrink-0 tabular-nums text-muted-foreground">
                          최고 score {g.best.toFixed(4)}
                        </span>
                      </div>
                      <div className="divide-y px-3">
                        <ChunkItem
                          h={g.hits[0]!} query={result.query} reranked={result.reranked} showDoc={false} bare
                          onInspect={g.documentUuid ? () => setInspectDoc({ uuid: g.documentUuid, name: g.documentName, text: g.hits[0]!.text }) : undefined}
                        />
                        {open &&
                          rest.map((h) => (
                            <ChunkItem
                              key={h.chunk_id} h={h} query={result.query} reranked={result.reranked} showDoc={false} bare
                              onInspect={g.documentUuid ? () => setInspectDoc({ uuid: g.documentUuid, name: g.documentName, text: h.text }) : undefined}
                            />
                          ))}
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
                })}
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {shownHits.map((h, i) => (
                  <ChunkItem
                    key={h.chunk_id} h={h} query={result.query} reranked={result.reranked} rank={i + 1}
                    onInspect={h.document_uuid ? () => setInspectDoc({ uuid: h.document_uuid, name: h.document_name, text: h.text }) : undefined}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        <DocumentInspectDialog
          documentId={inspectDoc?.uuid ?? null}
          documentName={inspectDoc?.name ?? ""}
          highlightText={inspectDoc?.text}
          open={inspectDoc !== null}
          onOpenChange={(o) => !o && setInspectDoc(null)}
        />
      </div>
    </TooltipProvider>
  )
}
