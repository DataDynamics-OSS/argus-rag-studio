"use client"

/**
 * 청킹 전/후 비교 다이얼로그 — 왼쪽에 청킹 전 전문, 오른쪽에 청킹 후 청크 목록을 나란히 둔다.
 * 청크를 클릭하면 왼쪽 전문에서 해당 구간을 하이라이트해(오버랩까지) 어디가 어느 청크인지 보여준다.
 * 전략·크기·오버랩을 바꾸면 저장·임베딩 없이 라이브로 다시 청킹해 결과를 비교할 수 있다.
 */

import { useCallback, useEffect, useRef, useState } from "react"
import { FileSearch, Loader2 } from "lucide-react"
import { Badge } from "@workspace/ui/components/badge"
import { Input } from "@workspace/ui/components/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { toast } from "sonner"
import { chunkPreviewDocument } from "@/features/ingestion/api"
import type { ChunkPreview } from "@/features/ingestion/data/schema"
import { DocumentInspectDialog } from "@/features/documents/components/document-inspect-dialog"
import { listParseStrategies } from "@/features/collections/api"
import type { ParseStrategyInfo } from "@/features/collections/data/schema"

// 파싱 전략 엔드포인트 조회 실패 시 폴백(설치 여부는 표시 안 함).
const PARSE_FALLBACK: ParseStrategyInfo[] = [
  { strategy: "auto", label: "auto", description: "", available: true },
  { strategy: "text", label: "text", description: "", available: true },
  { strategy: "layout", label: "layout", description: "", available: true },
  { strategy: "docai", label: "docai", description: "", available: true },
  { strategy: "vlm", label: "vlm", description: "", available: true },
  { strategy: "rhwp", label: "rhwp", description: "", available: true },
]

const STRATEGIES = [
  { value: "recursive", label: "recursive" },
  { value: "sentence", label: "sentence" },
  { value: "paragraph", label: "paragraph" },
  { value: "section", label: "section" },
  { value: "markdown", label: "markdown" },
  { value: "fixed", label: "fixed" },
  { value: "semantic", label: "semantic (임베딩 필요)" },
]

type Form = {
  parseStrategy: string
  strategy: string
  chunkSize: number
  chunkOverlap: number
  chunkUnit: string
}

export function ChunkCompareDialog({
  documentId,
  documentName,
  open,
  onOpenChange,
}: {
  documentId: string | null
  documentName: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [data, setData] = useState<ChunkPreview | null>(null)
  const [loading, setLoading] = useState(false)
  const [form, setForm] = useState<Form | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [parseStrats, setParseStrats] = useState<ParseStrategyInfo[]>([])
  // 청크 → 원본 뷰어에서 해당 위치로 이동(하이라이트). null 이면 닫힘.
  const [inspectText, setInspectText] = useState<string | null>(null)

  // 파싱 전략 목록(가용성 포함) 1회 로드 — 실패 시 폴백.
  useEffect(() => {
    listParseStrategies()
      .then((r) => setParseStrats(r.strategies))
      .catch(() => setParseStrats(PARSE_FALLBACK))
  }, [])
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const markRef = useRef<HTMLElement | null>(null)

  const fetchPreview = useCallback(
    async (id: string, overrides?: Partial<Form>) => {
      setLoading(true)
      try {
        const d = await chunkPreviewDocument(id, overrides)
        setData(d)
        // 최초 1회 컨트롤을 컬렉션 기본값으로 채운다(이후 편집은 사용자 값 유지).
        setForm((prev) =>
          prev ?? {
            parseStrategy: d.parse_strategy,
            strategy: d.chunk_strategy,
            chunkSize: d.chunk_size,
            chunkOverlap: d.chunk_overlap,
            chunkUnit: d.chunk_unit,
          },
        )
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "청킹 미리보기 실패")
        setData(null)
      } finally {
        setLoading(false)
      }
    },
    [],
  )

  // 열릴 때 기본 설정으로 로드, 닫히면 정리
  useEffect(() => {
    if (open && documentId != null) {
      setForm(null)
      setSelected(null)
      void fetchPreview(documentId)
    }
    if (!open) {
      setData(null)
      setForm(null)
      setSelected(null)
    }
  }, [open, documentId, fetchPreview])

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  // 선택 청크가 바뀌면 왼쪽 전문에서 하이라이트 위치로 스크롤
  useEffect(() => {
    if (selected != null) markRef.current?.scrollIntoView({ block: "center", behavior: "smooth" })
  }, [selected])

  // 컨트롤 변경 → 디바운스 후 override 로 재청킹
  const applyForm = useCallback(
    (patch: Partial<Form>) => {
      setForm((prev) => {
        if (!prev) return prev
        const next = { ...prev, ...patch }
        if (timer.current) clearTimeout(timer.current)
        timer.current = setTimeout(() => {
          if (documentId) void fetchPreview(documentId, next)
        }, 450)
        return next
      })
    },
    [documentId, fetchPreview],
  )

  const sel = selected != null ? data?.chunks.find((c) => c.seq === selected) : undefined
  const hasSpan = sel && sel.char_start != null && sel.char_end != null
  const avg = data && data.chunk_total ? Math.round(data.char_count / data.chunk_total) : 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[92vh] w-[97vw] max-w-[1280px] flex-col">
        <DialogHeader>
          <DialogTitle className="truncate" title={documentName}>
            청킹 전 · 후 비교 — {documentName}
          </DialogTitle>
          <DialogDescription>
            왼쪽은 청킹 전 전문, 오른쪽은 청킹 후 청크입니다. 청크를 클릭하면 전문에서 해당 구간을 표시합니다.
          </DialogDescription>
        </DialogHeader>

        {/* 컨트롤 — 라이브 재청킹 */}
        <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/30 px-3 py-2 text-xs">
          <span className="text-muted-foreground">파싱</span>
          <Select
            value={form?.parseStrategy ?? ""}
            onValueChange={(v) => applyForm({ parseStrategy: v })}
          >
            <SelectTrigger className="h-7 w-40"><SelectValue placeholder="—" /></SelectTrigger>
            <SelectContent>
              {(parseStrats.length ? parseStrats : PARSE_FALLBACK).map((s) => (
                <SelectItem key={s.strategy} value={s.strategy}>
                  {s.label}
                  {s.available === false ? " (미설치)" : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="ml-2 text-muted-foreground">청킹</span>
          <Select value={form?.strategy ?? ""} onValueChange={(v) => applyForm({ strategy: v })}>
            <SelectTrigger className="h-7 w-44"><SelectValue placeholder="—" /></SelectTrigger>
            <SelectContent>
              {STRATEGIES.map((s) => (
                <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="ml-2 text-muted-foreground">크기</span>
          <Input
            type="number"
            min={1}
            value={form?.chunkSize ?? 0}
            onChange={(e) => applyForm({ chunkSize: Math.max(1, Number(e.target.value) || 1) })}
            className="h-7 w-24"
          />
          <span className="ml-2 text-muted-foreground">오버랩</span>
          <Input
            type="number"
            min={0}
            value={form?.chunkOverlap ?? 0}
            onChange={(e) => applyForm({ chunkOverlap: Math.max(0, Number(e.target.value) || 0) })}
            className="h-7 w-24"
          />
          <Select value={form?.chunkUnit ?? "char"} onValueChange={(v) => applyForm({ chunkUnit: v })}>
            <SelectTrigger className="h-7 w-24"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="char">char</SelectItem>
              <SelectItem value="token">token</SelectItem>
            </SelectContent>
          </Select>
          <div className="ml-auto flex items-center gap-2 text-muted-foreground">
            {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {data && (
              <span className="tabular-nums">
                전문 {data.char_count.toLocaleString()}자 · 청크 {data.chunk_total}개 · 평균{" "}
                {avg.toLocaleString()}자
              </span>
            )}
            {data?.truncated && (
              <Badge variant="outline" className="text-amber-600">전문 일부(잘림)</Badge>
            )}
          </div>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 md:grid-cols-2">
          {/* 좌: 청킹 전 전문 */}
          <div className="flex min-h-0 flex-col overflow-hidden rounded-md border">
            <div className="border-b bg-muted/40 px-3 py-1.5 text-xs font-medium text-muted-foreground">
              청킹 전 (전문)
            </div>
            <div className="min-h-0 flex-1 overflow-auto p-3">
              {!data ? (
                <div className="flex h-full items-center justify-center">
                  {loading ? (
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  ) : (
                    <p className="text-sm text-muted-foreground">결과가 없습니다.</p>
                  )}
                </div>
              ) : (
                <pre className="whitespace-pre-wrap break-words font-sans text-xs leading-relaxed text-black">
                  {hasSpan ? (
                    <>
                      {data.body.slice(0, sel!.char_start!)}
                      <mark
                        ref={markRef}
                        className="rounded bg-primary/25 ring-1 ring-primary/40"
                      >
                        {data.body.slice(sel!.char_start!, sel!.char_end!)}
                      </mark>
                      {data.body.slice(sel!.char_end!)}
                    </>
                  ) : (
                    data.body
                  )}
                </pre>
              )}
            </div>
          </div>

          {/* 우: 청킹 후 청크 */}
          <div className="flex min-h-0 flex-col overflow-hidden rounded-md border">
            <div className="border-b bg-muted/40 px-3 py-1.5 text-xs font-medium text-muted-foreground">
              청킹 후 (청크 {data?.chunks.length ?? 0}개)
            </div>
            <div className="min-h-0 flex-1 space-y-2 overflow-auto p-2">
              {data?.chunks.map((c) => {
                const isSel = c.seq === selected
                return (
                  <button
                    key={c.seq}
                    type="button"
                    onClick={() => setSelected(isSel ? null : c.seq)}
                    className={`block w-full rounded-md border p-2 text-left transition-colors ${
                      isSel ? "border-primary bg-primary/5 ring-1 ring-primary" : "hover:bg-muted/50"
                    }`}
                  >
                    <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                      <Badge variant="outline" className="px-1 py-0">#{c.seq}</Badge>
                      {c.section_path && <span className="truncate">{c.section_path}</span>}
                      <span className="ml-auto tabular-nums">
                        {c.char_count ?? "?"}자{c.token_count != null ? ` · ${c.token_count}tok` : ""}
                      </span>
                      {/* 카드 자체가 button 이라 중첩 버튼 대신 span — 클릭 전파를 막아 선택 토글과 분리 */}
                      <span
                        role="button"
                        tabIndex={0}
                        onClick={(e) => { e.stopPropagation(); setInspectText(c.text) }}
                        onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); setInspectText(c.text) } }}
                        className="inline-flex shrink-0 items-center gap-1 text-primary underline-offset-2 hover:underline"
                        title="원본에서 이 청크 위치로 이동(하이라이트)"
                      >
                        <FileSearch className="size-3.5" />
                        원본에서 보기
                      </span>
                    </div>
                    {/* 선택한 청크는 전문, 나머지는 3줄 미리보기(클릭해 펼침). */}
                    <p
                      className={`whitespace-pre-wrap break-words text-xs leading-relaxed text-black ${
                        isSel ? "" : "line-clamp-3"
                      }`}
                    >
                      {c.text}
                    </p>
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      </DialogContent>

      {/* 청크 → 원본 위치 이동(HWP=SVG 페이지, PDF·오피스=pdf.js 페이지에 하이라이트+스크롤) */}
      <DocumentInspectDialog
        documentId={documentId}
        documentName={documentName}
        highlightText={inspectText ?? undefined}
        open={inspectText != null}
        onOpenChange={(o) => !o && setInspectText(null)}
      />
    </Dialog>
  )
}
