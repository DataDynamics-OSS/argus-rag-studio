// 이미지 추출 및 분석 — 문서를 업로드하면 안의 이미지를 먼저 추출해 화면 하단에 깔고(대기 상태),
// 추출이 끝난 뒤 한 장씩 VLM 으로 분석하며 카드 상태를 분석중→완료로 갱신한다(SSE 스트리밍).
// 여러 파일을 한꺼번에 올리면 순서대로(한 번에 하나씩) 처리한다. 추출 원본·썸네일·분석 결과는
// 분류 버킷에 저장되어 '이력' 탭에서 다시 볼 수 있다. 설정 > 이미지 추출 및 분류가 켜져 있어야 동작.
"use client"

import { UrlTabs } from "@/components/url-tabs"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Clock,
  Download,
  Link2,
  Loader2,
  RefreshCw,
  ScanSearch,
  Table2,
  Trash2,
  Type,
  X,
} from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import { Checkbox } from "@workspace/ui/components/checkbox"
import { Dialog, DialogContent, DialogTitle } from "@workspace/ui/components/dialog"
import { Input } from "@workspace/ui/components/input"
import { TabsContent, TabsList, TabsTrigger } from "@workspace/ui/components/tabs"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { DashboardHeader } from "@/components/dashboard-header"
import {
  analyzeRunStream,
  deleteRun,
  deleteRunImages,
  downloadRunSource,
  extractDocumentStream,
  extractUrlStream,
  getConfig,
  getRun,
  listRuns,
} from "@/features/image-recognition/api"
import type {
  RecognitionItem,
  RecognitionStreamEvent,
  RunDetail,
  RunImageItem,
  RunListItem,
} from "@/features/image-recognition/data/schema"
import {
  IMAGE_TYPE_LABEL,
  ImageTypeBadges,
} from "@/features/search/components/image-type-badges"

const ACCEPT =
  ".pdf,.png,.jpg,.jpeg,.webp,.bmp,.tiff,.tif,.gif,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.hwp,.hwpx,.html,.htm"

// 분석 탭 단계: 대기 → 추출중 → (추출완료)선택대기 → 분석중 → 완료.
type Phase = "idle" | "extracting" | "ready" | "analyzing" | "done"
// 추출된 이미지 1장(미리보기·선택용) — run 식별자와 선택 여부 포함.
type PreviewItem = RecognitionItem & { runId: string; selected: boolean }

// 이력 페이지당 건수.
const HISTORY_PAGE_SIZE = 50

// 이력 목록 컬럼 그리드(헤더·행 공용): 선택 | 파일명 | 유형 | 상태 | 이미지 | 분석 | 크기 | 생성일시
const HISTORY_GRID =
  "grid grid-cols-[1.5rem_minmax(0,1fr)_6rem_6rem_4rem_4rem_5rem_11rem] items-center gap-3"

// 생성일시 → "yyyy-mm-dd hh:mm:ss"(브라우저 로컬 기준).
function formatDateTime(iso: string | null): string {
  if (!iso) return "-"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "-"
  const p = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

// 파일 크기(byte) → 사람이 읽는 단위.
function formatSize(bytes: number): string {
  if (!bytes || bytes <= 0) return "-"
  const units = ["B", "KB", "MB", "GB"]
  let n = bytes
  let i = 0
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${i === 0 ? n : n.toFixed(1)} ${units[i]}`
}

// 경량 진행 막대. indeterminate=true 면 진행률 미상(가져오는 중) 표시.
function ProgressBar({
  value,
  max,
  indeterminate,
}: {
  value: number
  max: number
  indeterminate?: boolean
}) {
  const pct = indeterminate ? 100 : max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
      <div
        className={`h-full rounded-full bg-primary transition-all ${indeterminate ? "animate-pulse" : ""}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

// 페이지 번호 목록(현재 페이지 주변 + 처음/끝). 지식베이스 페이저와 동일 규칙.
function getPageNumbers(current: number, totalPages: number): (number | "...")[] {
  if (totalPages <= 7) return Array.from({ length: totalPages }, (_, i) => i + 1)
  if (current <= 4) return [1, 2, 3, 4, 5, "...", totalPages]
  if (current >= totalPages - 3)
    return [1, "...", totalPages - 4, totalPages - 3, totalPages - 2, totalPages - 1, totalPages]
  return [1, "...", current - 1, current, current + 1, "...", totalPages]
}

// 이력 상세의 이미지(presigned URL + 결과) → 카드/라이트박스가 쓰는 RecognitionItem 으로 변환.
function runImageToItem(it: RunImageItem): RecognitionItem {
  const analyzed = !!it.type
  return {
    index: it.index,
    page: it.page,
    locator: it.locator,
    width: it.width,
    height: it.height,
    thumbnail: it.thumb_url,
    original: it.original_url,
    status: analyzed ? "done" : "pending",
    result: analyzed
      ? {
          type: it.type,
          confidence: it.confidence,
          summary: it.summary,
          ocr_text: it.ocr_text,
          details: it.details,
        }
      : undefined,
  }
}

export default function ImageRecognitionPage() {
  const [zoom, setZoom] = useState<RecognitionItem | null>(null)
  const [historyRefresh, setHistoryRefresh] = useState(0)

  return (
    <>
      <DashboardHeader title="이미지 추출 및 분석" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <p className="text-sm text-muted-foreground">
          문서를 업로드하면 안의 이미지를 추출해 아래에 먼저 보여주고, 이어서 한 장씩{" "}
          <b>유형(도표·차트·사진 등)과 내용</b>을 분석합니다(분석 중/완료 상태 표시). 여러 파일을
          한꺼번에 올리면 <b>순서대로</b> 처리하며, 결과는 <b>이력</b> 탭에서 다시 볼 수 있습니다.
          PDF·이미지·Word·Excel·PowerPoint·HWP/HWPX·HTML 지원. (설정 &gt; 이미지 추출 및 분류가 켜져
          있어야 합니다.)
        </p>

        <UrlTabs defaultValue="analyze">
          <TabsList>
            <TabsTrigger value="analyze">분석</TabsTrigger>
            <TabsTrigger value="history">이력</TabsTrigger>
          </TabsList>

          <TabsContent value="analyze" className="mt-4">
            <AnalyzeTab onZoom={setZoom} onBatchDone={() => setHistoryRefresh((k) => k + 1)} />
          </TabsContent>

          <TabsContent value="history" className="mt-4">
            <HistoryTab refreshKey={historyRefresh} onZoom={setZoom} />
          </TabsContent>
        </UrlTabs>
      </div>

      {/* 확대 라이트박스(분석·이력 공용) */}
      <Dialog open={zoom !== null} onOpenChange={(o) => !o && setZoom(null)}>
        <DialogContent className="flex max-h-[92vh] w-[92vw] max-w-[900px] flex-col gap-2">
          {zoom && (
            <>
              <DialogTitle className="sr-only">이미지 상세 — {zoom.locator}</DialogTitle>
              <div className="flex items-center gap-2 text-sm">
                <StatusBadge item={zoom} />
                <span className="text-xs text-muted-foreground">
                  {zoom.locator} · {zoom.width}×{zoom.height}
                </span>
                <button
                  className="ml-auto text-muted-foreground hover:text-foreground"
                  onClick={() => setZoom(null)}
                  aria-label="닫기"
                >
                  <X className="size-4" />
                </button>
              </div>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={zoom.original || zoom.thumbnail}
                alt={zoom.result?.summary || zoom.locator}
                className="min-h-0 flex-1 rounded border object-contain"
              />
              {zoom.status === "error" ? (
                <p className="text-sm text-destructive">분석 실패: {zoom.error}</p>
              ) : zoom.result ? (
                <div className="max-h-[34vh] space-y-3 overflow-auto">
                  {zoom.result.summary && (
                    <ContentSection title="내용 설명">
                      <p className="text-sm text-muted-foreground">{zoom.result.summary}</p>
                    </ContentSection>
                  )}
                  {zoom.result.ocr_text && (
                    <ContentSection title="이미지 내 텍스트 (OCR)">
                      <pre className="whitespace-pre-wrap break-words rounded bg-muted/40 p-2 text-xs text-foreground">
                        {zoom.result.ocr_text}
                      </pre>
                    </ContentSection>
                  )}
                  {zoom.result.details && (
                    <ContentSection title="구조화 데이터 (표·수식)">
                      <pre className="whitespace-pre-wrap break-words rounded bg-muted/40 p-2 font-mono text-xs text-foreground">
                        {zoom.result.details}
                      </pre>
                    </ContentSection>
                  )}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {zoom.status === "analyzing" ? "분석 중입니다..." : "분석 대기 중입니다."}
                </p>
              )}
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}

// ── 분석 탭 — 업로드 + 순차 처리 + 스트리밍 결과 ─────────────────────────────
function AnalyzeTab({
  onZoom,
  onBatchDone,
}: {
  onZoom: (item: RecognitionItem) => void
  onBatchDone: () => void
}) {
  const [items, setItems] = useState<PreviewItem[]>([])
  const [runMeta, setRunMeta] = useState<Record<string, { filename: string; source_kind: string }>>({})
  const [phase, setPhase] = useState<Phase>("idle")
  const [extractProg, setExtractProg] = useState<{ done: number; total: number }>({ done: 0, total: 0 })
  const [analyzeProg, setAnalyzeProg] = useState<{ done: number; total: number }>({ done: 0, total: 0 })
  const [dragOver, setDragOver] = useState(false)
  const [urlPanelOpen, setUrlPanelOpen] = useState(false)
  const [urlValue, setUrlValue] = useState("")
  const [dropSmall, setDropSmall] = useState(true)
  const [smallImageKb, setSmallImageKb] = useState(10)
  const inputRef = useRef<HTMLInputElement>(null)

  // '작은 이미지 제거' 기준 크기(KB) — 설정값을 라벨에 표시.
  useEffect(() => {
    getConfig()
      .then((c) => setSmallImageKb(c.small_image_min_kb))
      .catch(() => {})
  }, [])

  const busy = phase === "extracting" || phase === "analyzing"
  const selectable = phase === "ready" || phase === "done"
  const selectedCount = items.filter((it) => it.selected).length

  // 추출 스트림(업로드/URL 공용) 소비 — start/image 이벤트로 미리보기 그리드를 한 장씩 채운다.
  const consumeExtract = useCallback(
    (start: (onEvent: (e: RecognitionStreamEvent) => void) => Promise<void>) =>
      start((ev) => {
        if (ev.type === "start") {
          setRunMeta((prev) => ({
            ...prev,
            [ev.run_id]: { filename: ev.filename, source_kind: ev.source_kind },
          }))
          setExtractProg((p) => ({ done: p.done, total: p.total + (ev.total || 0) }))
        } else if (ev.type === "image") {
          setItems((prev) => [
            ...prev,
            {
              runId: ev.run_id, index: ev.index, page: ev.page, locator: ev.locator,
              width: ev.width, height: ev.height, thumbnail: ev.thumbnail, original: ev.original,
              status: "pending", selected: true,
            },
          ])
          setExtractProg((p) => ({ done: p.done + 1, total: p.total }))
        } else if (ev.type === "error") {
          toast.error(ev.detail)
        }
      }),
    [],
  )

  // 업로드(여러 파일 순차) → 추출(다운로드). 분석은 별도 '분석' 버튼.
  const extractFiles = useCallback(
    async (files: File[]) => {
      const batchId =
        typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : String(Date.now())
      setPhase("extracting")
      setItems([])
      setRunMeta({})
      setExtractProg({ done: 0, total: 0 })
      try {
        for (const f of files) {
          await consumeExtract((onEvent) => extractDocumentStream(f, onEvent, { batchId }))
        }
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "이미지 추출 실패")
      } finally {
        setPhase("ready")
        onBatchDone()
      }
    },
    [consumeExtract, onBatchDone],
  )

  const extractUrl = useCallback(async () => {
    const url = urlValue.trim()
    if (!url) {
      toast.error("URL을 입력하세요.")
      return
    }
    setUrlPanelOpen(false)
    setPhase("extracting")
    setItems([])
    setRunMeta({})
    setExtractProg({ done: 0, total: 0 })
    try {
      await consumeExtract((onEvent) => extractUrlStream(url, dropSmall, onEvent))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "URL 가져오기 실패")
    } finally {
      setPhase("ready")
      onBatchDone()
    }
  }, [urlValue, dropSmall, consumeExtract, onBatchDone])

  const onPick = (files: FileList | null) => {
    const list = files ? Array.from(files) : []
    if (list.length) void extractFiles(list)
  }

  // 이미지 목록 초기화 — 추출/분석 결과를 모두 비운다.
  const clearItems = useCallback(() => {
    setItems([])
    setRunMeta({})
    setExtractProg({ done: 0, total: 0 })
    setAnalyzeProg({ done: 0, total: 0 })
  }, [])

  // 선택한 이미지를 run별로 묶어 분석(선택분만). 진행률 표시.
  const runAnalyze = useCallback(async () => {
    const sel = items.filter((it) => it.selected)
    if (sel.length === 0) {
      toast.error("분석할 이미지를 선택하세요.")
      return
    }
    const byRun: Record<string, number[]> = {}
    for (const it of sel) (byRun[it.runId] ||= []).push(it.index)
    setPhase("analyzing")
    setAnalyzeProg({ done: 0, total: sel.length })
    let done = 0
    try {
      for (const [runId, indices] of Object.entries(byRun)) {
        await analyzeRunStream(runId, indices, (ev) => {
          if (ev.type === "analyzing") {
            setItems((prev) =>
              prev.map((it) =>
                it.runId === runId && it.index === ev.index ? { ...it, status: "analyzing" } : it,
              ),
            )
          } else if (ev.type === "item") {
            setItems((prev) =>
              prev.map((it) =>
                it.runId === runId && it.index === ev.index
                  ? { ...it, status: ev.ok ? "done" : "error", result: ev.result, error: ev.error }
                  : it,
              ),
            )
            done += 1
            setAnalyzeProg({ done, total: sel.length })
          } else if (ev.type === "error") {
            toast.error(ev.detail)
          }
        })
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "이미지 분석 실패")
    } finally {
      setPhase("done")
      onBatchDone()
    }
  }, [items, onBatchDone])

  const toggleItem = useCallback((runId: string, index: number, on: boolean) => {
    setItems((prev) =>
      prev.map((it) => (it.runId === runId && it.index === index ? { ...it, selected: on } : it)),
    )
  }, [])
  const toggleAll = useCallback((on: boolean) => {
    setItems((prev) => prev.map((it) => ({ ...it, selected: on })))
  }, [])

  // run(파일/URL)별로 묶어 표시(삽입 순서 유지).
  const groups = useMemo(() => {
    const order: string[] = []
    const map = new Map<string, PreviewItem[]>()
    for (const it of items) {
      if (!map.has(it.runId)) {
        map.set(it.runId, [])
        order.push(it.runId)
      }
      map.get(it.runId)!.push(it)
    }
    return order.map((rid) => ({ runId: rid, meta: runMeta[rid], items: map.get(rid)! }))
  }, [items, runMeta])

  // 분석 완료 유형 집계.
  const countsByType = useMemo(() => {
    const c: Record<string, number> = {}
    for (const it of items) {
      if (it.status === "done" && it.result) c[it.result.type] = (c[it.result.type] ?? 0) + 1
    }
    return c
  }, [items])

  const allSelected = items.length > 0 && items.every((it) => it.selected)

  return (
    <div className="space-y-4">
      {/* URL에서 이미지 가져오기 — 업로드 영역 위, 우측 정렬 */}
      <div className="space-y-2">
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={() => setUrlPanelOpen((v) => !v)} disabled={busy}>
            <Link2 className="size-4" /> URL에서 이미지 가져오기
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={clearItems}
            disabled={busy || items.length === 0}
          >
            <Trash2 className="size-4" /> 초기화
          </Button>
        </div>
        {urlPanelOpen && (
          <div className="flex flex-col gap-2 rounded-md border bg-muted/30 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Input
                type="url"
                inputMode="url"
                placeholder="https://example.com/page"
                value={urlValue}
                onChange={(e) => setUrlValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !busy) void extractUrl()
                }}
                disabled={busy}
                className="min-w-[16rem] flex-1"
              />
              <label className="flex shrink-0 items-center gap-1.5 text-sm text-muted-foreground">
                <Checkbox
                  checked={dropSmall}
                  onCheckedChange={(v) => setDropSmall(v === true)}
                  disabled={busy}
                />
                작은 이미지 제거 ({smallImageKb}KB)
              </label>
              <Button size="sm" onClick={() => extractUrl()} disabled={busy || !urlValue.trim()}>
                {busy ? <Loader2 className="size-4 animate-spin" /> : <Link2 className="size-4" />}
                가져오기
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              웹페이지(HTML)의 이미지를 받는 대로 한 장씩 가져옵니다. 가져온 뒤 분석할 이미지를 선택해
              아래 <b>분석</b> 버튼을 누르세요.
            </p>
          </div>
        )}
      </div>

      {/* 업로드 영역 */}
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragOver(false)
          if (!busy) onPick(e.dataTransfer.files)
        }}
        className={`flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-4 py-10 text-center transition-colors ${
          dragOver ? "border-primary bg-primary/5" : "border-muted-foreground/30"
        }`}
      >
        <ScanSearch className="size-7 text-muted-foreground" />
        <div className="text-sm">
          파일을 끌어다 놓거나{" "}
          <button
            type="button"
            className="font-medium text-primary underline-offset-2 hover:underline disabled:opacity-50"
            onClick={() => inputRef.current?.click()}
            disabled={busy}
          >
            파일 선택
          </button>{" "}
          (여러 개 가능)
        </div>
        <div className="text-xs text-muted-foreground">
          PDF · 이미지 · Word · Excel · PPT · HWP/HWPX · HTML
        </div>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          multiple
          className="hidden"
          onChange={(e) => onPick(e.target.files)}
        />
      </div>

      {/* 추출 진행 표시 */}
      {phase === "extracting" && (
        <div className="space-y-1">
          <ProgressBar
            value={extractProg.done}
            max={extractProg.total}
            indeterminate={extractProg.total === 0}
          />
          <p className="text-xs text-muted-foreground tabular-nums">
            이미지를 가져오는 중입니다... {extractProg.done}
            {extractProg.total > 0 ? `/${extractProg.total}` : ""}장
          </p>
        </div>
      )}

      {/* 결과(추출 후) — 선택 + 분석 */}
      {items.length > 0 && (
        <div className="space-y-3">
          {/* 툴바: 전체선택 + 분석 버튼 + 진행/집계 */}
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1.5 text-sm">
              <Checkbox
                checked={allSelected ? true : selectedCount > 0 ? "indeterminate" : false}
                onCheckedChange={(v) => toggleAll(v === true)}
                disabled={!selectable}
              />
              전체 선택
            </label>
            <span className="text-xs text-muted-foreground tabular-nums">
              {items.length}개 추출 · {selectedCount}개 선택
            </span>
            <ImageTypeBadges types={countsByType} />
            <Button
              size="sm"
              className="ml-auto"
              onClick={() => runAnalyze()}
              disabled={busy || selectedCount === 0}
            >
              {phase === "analyzing" ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <ScanSearch className="size-4" />
              )}
              분석{selectedCount > 0 ? ` (${selectedCount})` : ""}
            </Button>
          </div>

          {phase === "analyzing" && (
            <div className="space-y-1">
              <ProgressBar value={analyzeProg.done} max={analyzeProg.total} />
              <p className="text-xs text-muted-foreground tabular-nums">
                분석 {analyzeProg.done}/{analyzeProg.total}
              </p>
            </div>
          )}

          {groups.map((g) => (
            <div key={g.runId} className="space-y-2">
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                {g.meta?.source_kind && (
                  <Badge variant="outline" className="h-5 font-normal">
                    {g.meta.source_kind}
                  </Badge>
                )}
                <span className="truncate" title={g.meta?.filename}>
                  {g.meta?.filename}
                </span>
              </div>
              <ImageCardGrid
                items={g.items}
                itemKey={(it) => `${it.runId}-${it.index}`}
                isSelected={(it) => it.selected}
                onToggle={(it, on) => toggleItem(it.runId, it.index, on)}
                onZoom={(it) => onZoom(it)}
                selectable={selectable}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── 이력 탭 — 과거 실행 목록 + 상세(저장된 원본·썸네일·분석) ──────────────────
function HistoryTab({
  refreshKey,
  onZoom,
}: {
  refreshKey: number
  onZoom: (item: RecognitionItem) => void
}) {
  const [runs, setRuns] = useState<RunListItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [detailItems, setDetailItems] = useState<RecognitionItem[] | null>(null)
  const [detailMeta, setDetailMeta] = useState<RunDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  // 상세에서 재분석할 이미지 선택(인덱스) + 진행 상태.
  const [detailSelected, setDetailSelected] = useState<Set<number>>(new Set())
  const [detailAnalyzing, setDetailAnalyzing] = useState(false)
  const [detailAnalyzeProg, setDetailAnalyzeProg] = useState<{ done: number; total: number } | null>(null)
  const [deleteChoiceOpen, setDeleteChoiceOpen] = useState(false) // 상세 삭제: 이력 vs 선택 이미지
  const [confirmBulkOpen, setConfirmBulkOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteProgress, setDeleteProgress] = useState<{ done: number; total: number } | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  const totalPages = Math.max(1, Math.ceil(total / HISTORY_PAGE_SIZE))

  const load = useCallback(async (p: number) => {
    setLoading(true)
    try {
      const res = await listRuns({ page: p, page_size: HISTORY_PAGE_SIZE })
      setRuns(res.items)
      setTotal(res.total)
      setSelectedIds(new Set()) // 페이지 로드 시 선택 초기화
      // 삭제 등으로 현재 페이지가 비면 이전 페이지로 보정(다음 렌더에서 재조회).
      const tp = Math.max(1, Math.ceil(res.total / HISTORY_PAGE_SIZE))
      if (p > tp) setPage(tp)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "이력 조회 실패")
    } finally {
      setLoading(false)
    }
  }, [])

  // 분석 batch 완료(refreshKey 변경) 시 최신이 있는 1페이지로.
  useEffect(() => {
    setPage(1)
  }, [refreshKey])

  useEffect(() => {
    void load(page)
  }, [load, page, refreshKey])

  const openDetail = useCallback(async (runId: string) => {
    setSelected(runId)
    setDetailLoading(true)
    setDetailItems(null)
    setDetailSelected(new Set())
    try {
      const d = await getRun(runId)
      setDetailMeta(d)
      setDetailItems(d.items.map(runImageToItem))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "이력 상세 조회 실패")
      setSelected(null)
    } finally {
      setDetailLoading(false)
    }
  }, [])

  // 상세 카드 선택 토글 / 전체 선택·해제.
  const toggleDetailOne = useCallback((index: number, on: boolean) => {
    setDetailSelected((prev) => {
      const next = new Set(prev)
      if (on) next.add(index)
      else next.delete(index)
      return next
    })
  }, [])
  const detailSelectAll = useCallback(() => {
    setDetailSelected(new Set((detailItems ?? []).map((it) => it.index)))
  }, [detailItems])
  const detailDeselectAll = useCallback(() => setDetailSelected(new Set()), [])

  // 선택한 이미지를 재분석(버킷 원본 재읽기) — 진행률 표시 후 상세·이력 갱신.
  const reanalyzeDetail = useCallback(async () => {
    if (!selected || detailSelected.size === 0) {
      toast.error("재분석할 이미지를 선택하세요.")
      return
    }
    const indices = Array.from(detailSelected)
    setDetailAnalyzing(true)
    setDetailAnalyzeProg({ done: 0, total: indices.length })
    let done = 0
    try {
      await analyzeRunStream(selected, indices, (ev) => {
        if (ev.type === "analyzing") {
          setDetailItems((prev) =>
            prev
              ? prev.map((it) => (it.index === ev.index ? { ...it, status: "analyzing" } : it))
              : prev,
          )
        } else if (ev.type === "item") {
          setDetailItems((prev) =>
            prev
              ? prev.map((it) =>
                  it.index === ev.index
                    ? { ...it, status: ev.ok ? "done" : "error", result: ev.result, error: ev.error }
                    : it,
                )
              : prev,
          )
          done += 1
          setDetailAnalyzeProg({ done, total: indices.length })
        } else if (ev.type === "error") {
          toast.error(ev.detail)
        }
      })
      toast.success("재분석을 완료했습니다.")
      setDetailSelected(new Set())
      void load(page) // 이력 목록 분석수·유형 갱신
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "재분석 실패")
    } finally {
      setDetailAnalyzing(false)
      setDetailAnalyzeProg(null)
    }
  }, [selected, detailSelected, load, page])

  // 상세 삭제 선택지 ① 이력 전체 삭제.
  const deleteWholeRun = useCallback(async () => {
    if (!selected) return
    setDeleting(true)
    try {
      await deleteRun(selected)
      toast.success("이력과 파일을 삭제했습니다.")
      setDeleteChoiceOpen(false)
      setSelected(null)
      setDetailItems(null)
      void load(page)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "이력 삭제 실패")
    } finally {
      setDeleting(false)
    }
  }, [selected, load, page])

  // 상세 삭제 선택지 ② 선택한 이미지만 삭제(이력 유지).
  const deleteSelectedImages = useCallback(async () => {
    if (!selected || detailSelected.size === 0) return
    const indices = Array.from(detailSelected)
    setDeleting(true)
    try {
      await deleteRunImages(selected, indices)
      toast.success(`이미지 ${indices.length}개를 삭제했습니다.`)
      setDetailItems((prev) => (prev ? prev.filter((it) => !detailSelected.has(it.index)) : prev))
      setDetailSelected(new Set())
      setDeleteChoiceOpen(false)
      void load(page) // 이력 목록 개수 갱신
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "이미지 삭제 실패")
    } finally {
      setDeleting(false)
    }
  }, [selected, detailSelected, load, page])

  // 선택 토글 / 전체선택(현재 페이지 기준).
  const toggleOne = useCallback((runId: string, on: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (on) next.add(runId)
      else next.delete(runId)
      return next
    })
  }, [])
  const toggleAll = useCallback(
    (on: boolean) => {
      setSelectedIds(on ? new Set(runs.map((r) => r.run_id)) : new Set())
    },
    [runs],
  )

  // 선택한 여러 건 일괄 삭제(분류 버킷 객체 + 이력 레코드).
  const confirmBulkRemove = useCallback(async () => {
    const ids = Array.from(selectedIds)
    if (ids.length === 0) return
    setDeleting(true)
    setDeleteProgress({ done: 0, total: ids.length })
    let failed = 0
    try {
      // 순차 삭제 — 진행률을 한 건씩 갱신(진행 막대 표시).
      for (let i = 0; i < ids.length; i++) {
        try {
          await deleteRun(ids[i]!)
        } catch {
          failed += 1
        }
        setDeleteProgress({ done: i + 1, total: ids.length })
      }
      if (failed > 0) toast.error(`${failed}건 삭제 실패`)
      if (failed < ids.length) toast.success(`${ids.length - failed}건의 이력과 파일을 삭제했습니다.`)
      setConfirmBulkOpen(false)
      setSelectedIds(new Set())
      void load(page)
    } finally {
      setDeleting(false)
      setDeleteProgress(null)
    }
  }, [selectedIds, load, page])

  // 상세 보기 / 목록 보기 — 삭제 확인 다이얼로그는 두 화면 공용.
  return (
    <>
      {selected ? (
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setSelected(null)}>
            ← 목록
          </Button>
          {detailMeta && (
            <span className="truncate text-sm font-medium" title={detailMeta.source_url || detailMeta.filename}>
              {detailMeta.filename}
            </span>
          )}
          {detailMeta && <RunStatusBadge status={detailMeta.status} />}
          {detailMeta && (
            <div className="ml-auto flex items-center gap-1">
              {detailMeta.source_download_url && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-primary hover:text-primary"
                  onClick={() => {
                    void downloadRunSource(detailMeta.run_id, detailMeta.source_filename).catch(
                      (err) =>
                        toast.error(err instanceof Error ? err.message : "원본 파일 다운로드 실패"),
                    )
                  }}
                  title="원본 파일 다운로드"
                >
                  <Download className="size-4" /> 원본 파일
                </Button>
              )}
              <Button
                size="sm"
                onClick={() => reanalyzeDetail()}
                disabled={detailAnalyzing || detailSelected.size === 0}
              >
                {detailAnalyzing ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <ScanSearch className="size-4" />
                )}
                분석{detailSelected.size > 0 ? ` (${detailSelected.size})` : ""}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={detailSelectAll}
                disabled={detailAnalyzing || !detailItems?.length}
              >
                전체 선택
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={detailDeselectAll}
                disabled={detailAnalyzing || detailSelected.size === 0}
              >
                전체 해제
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive hover:text-destructive"
                onClick={() => setDeleteChoiceOpen(true)}
                disabled={detailAnalyzing}
              >
                <Trash2 className="size-4" /> 삭제{detailSelected.size > 0 ? ` (${detailSelected.size})` : ""}
              </Button>
            </div>
          )}
        </div>

        {detailAnalyzeProg && (
          <div className="space-y-1">
            <ProgressBar value={detailAnalyzeProg.done} max={detailAnalyzeProg.total} />
            <p className="text-xs text-muted-foreground tabular-nums">
              재분석 {detailAnalyzeProg.done}/{detailAnalyzeProg.total}
            </p>
          </div>
        )}

        {detailLoading ? (
          <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
            <Loader2 className="size-5 animate-spin" /> 불러오는 중입니다...
          </div>
        ) : detailItems && detailItems.length > 0 ? (
          <ImageCardGrid
            items={detailItems}
            itemKey={(it) => String(it.index)}
            isSelected={(it) => detailSelected.has(it.index)}
            onToggle={(it, on) => toggleDetailOne(it.index, on)}
            onZoom={(it) => onZoom(it)}
            selectable={!detailAnalyzing}
            hideLocator
          />
        ) : (
          <p className="rounded-md border border-dashed px-3 py-10 text-center text-sm text-muted-foreground">
            저장된 이미지가 없습니다.
          </p>
        )}
      </div>
      ) : (
      <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-sm text-muted-foreground">
          총 {total}건{selectedIds.size > 0 ? ` · ${selectedIds.size}건 선택` : ""}
        </span>
        <Button
          variant="destructive"
          size="sm"
          className="ml-auto"
          onClick={() => setConfirmBulkOpen(true)}
          disabled={loading || selectedIds.size === 0}
        >
          <Trash2 className="size-4" /> 삭제{selectedIds.size > 0 ? ` (${selectedIds.size})` : ""}
        </Button>
        <Button variant="outline" size="sm" onClick={() => load(page)} disabled={loading}>
          <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} /> 새로고침
        </Button>
      </div>

      {loading && runs.length === 0 ? (
        <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
          <Loader2 className="size-5 animate-spin" /> 불러오는 중입니다...
        </div>
      ) : runs.length === 0 ? (
        <p className="rounded-md border border-dashed px-3 py-10 text-center text-sm text-muted-foreground">
          저장된 실행 이력이 없습니다. 분석 탭에서 문서를 업로드하면 여기에 기록됩니다.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <div className="min-w-[60rem] divide-y">
            {/* 헤더 — 전체선택 + 컬럼 라벨 */}
            <div className={`${HISTORY_GRID} bg-muted/40 px-3 py-2 text-xs font-medium text-muted-foreground`}>
              <Checkbox
                checked={
                  runs.length > 0 && runs.every((r) => selectedIds.has(r.run_id))
                    ? true
                    : selectedIds.size > 0
                      ? "indeterminate"
                      : false
                }
                onCheckedChange={(v) => toggleAll(v === true)}
                aria-label="전체 선택"
              />
              <span>파일명</span>
              <span className="text-center">유형</span>
              <span className="text-center">상태</span>
              <span className="text-center">이미지</span>
              <span className="text-center">분석</span>
              <span className="text-center">크기</span>
              <span className="text-center">생성일시</span>
            </div>
            {runs.map((r) => {
              const checked = selectedIds.has(r.run_id)
              return (
                <div
                  key={r.run_id}
                  className={`${HISTORY_GRID} cursor-pointer px-3 py-2 text-sm hover:bg-muted/30 ${checked ? "bg-primary/5" : ""}`}
                  onClick={() => openDetail(r.run_id)}
                >
                  <div onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                      checked={checked}
                      onCheckedChange={(v) => toggleOne(r.run_id, v === true)}
                      aria-label={`${r.filename} 선택`}
                    />
                  </div>
                  <span className="truncate font-medium" title={r.source_url || r.filename}>
                    {r.filename}
                  </span>
                  <span className="min-w-0 text-center">
                    {r.source_kind && (
                      <Badge variant="outline" className="h-5 max-w-full truncate font-normal">
                        {r.source_kind}
                      </Badge>
                    )}
                  </span>
                  <span className="flex min-w-0 justify-center">
                    <RunStatusBadge status={r.status} />
                  </span>
                  <span className="text-center text-xs text-muted-foreground tabular-nums">
                    {r.extracted_count}
                  </span>
                  <span className="text-center text-xs text-muted-foreground tabular-nums">
                    {r.analyzed_count}
                  </span>
                  <span className="text-right text-xs text-muted-foreground tabular-nums">
                    {formatSize(r.size_bytes)}
                  </span>
                  <span className="text-center text-xs text-muted-foreground tabular-nums">
                    {formatDateTime(r.created_at)}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {totalPages > 1 && (
        <HistoryPager
          page={page}
          totalPages={totalPages}
          disabled={loading}
          onChange={setPage}
        />
      )}
      </div>
      )}

      <ConfirmDialog
        open={confirmBulkOpen}
        onOpenChange={(o) => {
          if (!o && !deleting) setConfirmBulkOpen(false)
        }}
        title="선택한 이력 삭제"
        destructive
        isLoading={deleting}
        confirmText={`삭제 (${selectedIds.size})`}
        handleConfirm={confirmBulkRemove}
        desc={
          <span>
            선택한 <b>{selectedIds.size}건</b>의 실행 이력을 삭제하면 분류 버킷에 저장된 업로드
            원본 파일·추출 이미지·썸네일·분석 결과가 <b>모두 함께 삭제</b>됩니다. 이 작업은 되돌릴 수
            없습니다.
          </span>
        }
      >
        {deleteProgress && (
          <div className="space-y-1">
            <ProgressBar value={deleteProgress.done} max={deleteProgress.total} />
            <p className="text-xs text-muted-foreground tabular-nums">
              {deleteProgress.done}/{deleteProgress.total} 삭제 중...
            </p>
          </div>
        )}
      </ConfirmDialog>

      {/* 상세 삭제 선택 — 선택 이미지가 있으면 둘 중 선택, 없으면 이력 전체만 */}
      <Dialog open={deleteChoiceOpen} onOpenChange={(o) => !o && !deleting && setDeleteChoiceOpen(false)}>
        <DialogContent className="flex w-[92vw] max-w-[440px] flex-col gap-3">
          <DialogTitle>삭제</DialogTitle>
          <p className="text-sm text-muted-foreground">
            {detailSelected.size > 0
              ? `선택한 이미지 ${detailSelected.size}개만 삭제할지, 이력 전체를 삭제할지 선택하세요. 이 작업은 되돌릴 수 없습니다.`
              : "이 이력(추출 이미지·원본 파일·분석 결과 전체)을 삭제합니다. 이 작업은 되돌릴 수 없습니다."}
          </p>
          <div className="flex flex-col gap-2">
            {detailSelected.size > 0 && (
              <Button
                variant="destructive"
                onClick={() => void deleteSelectedImages()}
                disabled={deleting}
              >
                <Trash2 className="size-4" /> 선택한 이미지 삭제 ({detailSelected.size})
              </Button>
            )}
            <Button variant="destructive" onClick={() => void deleteWholeRun()} disabled={deleting}>
              <Trash2 className="size-4" /> 이력 전체 삭제(이미지 모두 포함)
            </Button>
            <Button variant="outline" onClick={() => setDeleteChoiceOpen(false)} disabled={deleting}>
              취소
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}

// 이력 목록 페이저 — 번호 버튼 + 처음/이전/다음/끝(지식베이스 페이저와 동일 룩).
function HistoryPager({
  page,
  totalPages,
  disabled,
  onChange,
}: {
  page: number
  totalPages: number
  disabled?: boolean
  onChange: (p: number) => void
}) {
  const go = (p: number) => onChange(Math.min(Math.max(1, p), totalPages))
  return (
    <div className="flex items-center justify-end gap-2 px-2 pt-1">
      <div className="flex w-[90px] items-center justify-center text-sm font-medium tabular-nums">
        {page} / {totalPages} 페이지
      </div>
      <Button variant="outline" className="size-8 p-0" onClick={() => go(1)} disabled={disabled || page <= 1}>
        <span className="sr-only">첫 페이지로</span>
        <ChevronsLeft className="h-4 w-4" />
      </Button>
      <Button variant="outline" className="size-8 p-0" onClick={() => go(page - 1)} disabled={disabled || page <= 1}>
        <span className="sr-only">이전 페이지</span>
        <ChevronLeft className="h-4 w-4" />
      </Button>
      {getPageNumbers(page, totalPages).map((n, i) =>
        n === "..." ? (
          <span key={`e-${i}`} className="px-1 text-sm text-muted-foreground">
            ...
          </span>
        ) : (
          <Button
            key={n}
            variant={page === n ? "default" : "outline"}
            className="h-8 min-w-8 px-2"
            onClick={() => go(n)}
            disabled={disabled}
          >
            {n}
          </Button>
        ),
      )}
      <Button
        variant="outline"
        className="size-8 p-0"
        onClick={() => go(page + 1)}
        disabled={disabled || page >= totalPages}
      >
        <span className="sr-only">다음 페이지</span>
        <ChevronRight className="h-4 w-4" />
      </Button>
      <Button
        variant="outline"
        className="size-8 p-0"
        onClick={() => go(totalPages)}
        disabled={disabled || page >= totalPages}
      >
        <span className="sr-only">마지막 페이지로</span>
        <ChevronsRight className="h-4 w-4" />
      </Button>
    </div>
  )
}

// 실행 상태 뱃지 — extracted/analyzing/running/succeeded/failed.
function RunStatusBadge({ status }: { status: string }) {
  if (status === "extracted") {
    return (
      <Badge variant="outline" className="h-5 shrink-0 gap-1 font-normal text-muted-foreground">
        <Clock className="size-3" /> 추출됨
      </Badge>
    )
  }
  if (status === "running" || status === "analyzing") {
    return (
      <Badge variant="outline" className="h-5 shrink-0 gap-1 font-normal text-primary">
        <Loader2 className="size-3 animate-spin" /> 분석 중
      </Badge>
    )
  }
  if (status === "failed") {
    return (
      <Badge variant="outline" className="h-5 shrink-0 gap-1 font-normal text-destructive">
        <AlertCircle className="size-3" /> 실패
      </Badge>
    )
  }
  return (
    <Badge variant="secondary" className="h-5 shrink-0 gap-1 font-normal">
      <CheckCircle2 className="size-3 text-emerald-600" /> 완료
    </Badge>
  )
}

// 라이트박스 내용 섹션 — 제목 + 본문(설명/OCR/구조화).
function ContentSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{title}</div>
      {children}
    </div>
  )
}

// 분석 상태 뱃지 — 대기/분석중/완료(유형+신뢰도)/실패.
function StatusBadge({ item }: { item: RecognitionItem }) {
  if (item.status === "pending") {
    return (
      <Badge variant="outline" className="h-5 gap-1 font-normal text-muted-foreground">
        <Clock className="size-3" /> 대기
      </Badge>
    )
  }
  if (item.status === "analyzing") {
    return (
      <Badge variant="outline" className="h-5 gap-1 font-normal text-primary">
        <Loader2 className="size-3 animate-spin" /> 분석 중
      </Badge>
    )
  }
  if (item.status === "error") {
    return (
      <Badge variant="outline" className="h-5 gap-1 font-normal text-destructive">
        <AlertCircle className="size-3" /> 분석 실패
      </Badge>
    )
  }
  // done
  return (
    <span className="flex items-center gap-1.5">
      <Badge variant="secondary" className="h-5 gap-1 font-normal">
        <CheckCircle2 className="size-3 text-emerald-600" />
        {item.result ? (IMAGE_TYPE_LABEL[item.result.type] ?? item.result.type) : "완료"}
      </Badge>
      {item.result && (
        <span className="text-xs text-muted-foreground tabular-nums">
          {Math.round(item.result.confidence * 100)}%
        </span>
      )}
    </span>
  )
}

// 이미지 카드 그리드 — 분석 탭·이력 상세 공용. 선택(체크박스)·확대·잠금(hideLocator)을 받는다.
function ImageCardGrid<T extends RecognitionItem>({
  items,
  itemKey,
  isSelected,
  onToggle,
  onZoom,
  selectable,
  hideLocator,
}: {
  items: T[]
  itemKey: (it: T) => string
  onZoom: (it: T) => void
  isSelected?: (it: T) => boolean
  onToggle?: (it: T, on: boolean) => void
  selectable?: boolean
  hideLocator?: boolean
}) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {items.map((it) => (
        <ImageCard
          key={itemKey(it)}
          item={it}
          onZoom={() => onZoom(it)}
          hideLocator={hideLocator}
          selectable={selectable}
          selected={isSelected?.(it)}
          onToggle={(on) => onToggle?.(it, on)}
        />
      ))}
    </div>
  )
}

// 이미지 카드 — 썸네일(분석중엔 오버레이) + 상태 뱃지 + 요약/OCR·데이터 표시.
// selectable 이면 좌상단에 분석 대상 선택 체크박스를 표시한다.
function ImageCard({
  item,
  onZoom,
  selectable,
  selected,
  onToggle,
  hideLocator,
}: {
  item: RecognitionItem
  onZoom: () => void
  selectable?: boolean
  selected?: boolean
  onToggle?: (on: boolean) => void
  hideLocator?: boolean
}) {
  const summary = item.result?.summary
  return (
    <div
      className={`relative flex flex-col overflow-hidden rounded-md border text-black ${
        selectable && selected ? "ring-2 ring-primary" : ""
      }`}
    >
      {/* 선택 체크박스 — 버튼 중첩(button in button) 방지를 위해 카드 컨테이너의 오버레이로 둔다. */}
      {selectable && (
        <div className="absolute left-1.5 top-1.5 z-10 rounded bg-background/80 p-0.5">
          <Checkbox
            checked={!!selected}
            onCheckedChange={(v) => onToggle?.(v === true)}
            aria-label="분석 대상 선택"
          />
        </div>
      )}
      <button
        type="button"
        onClick={onZoom}
        className="relative flex aspect-[4/3] items-center justify-center overflow-hidden bg-muted/30"
        title="크게 보기"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={item.thumbnail}
          alt={summary || item.locator}
          className={`h-full w-full object-contain transition-opacity ${
            item.status === "pending" || item.status === "analyzing" ? "opacity-60" : ""
          }`}
        />
        {item.status === "analyzing" && (
          <div className="absolute inset-0 flex items-center justify-center gap-1.5 bg-background/40 text-xs font-medium text-primary backdrop-blur-[1px]">
            <Loader2 className="size-4 animate-spin" /> 분석 중
          </div>
        )}
        {!selectable && item.status === "pending" && (
          <div className="absolute right-1.5 top-1.5">
            <Badge variant="outline" className="h-4 gap-0.5 bg-background/80 px-1 text-[10px] font-normal">
              <Clock className="size-2.5" /> 대기
            </Badge>
          </div>
        )}
      </button>
      <div className="flex flex-col gap-1 p-2">
        {(item.status !== "pending" || !hideLocator) && (
          <div className="flex items-center gap-1.5 text-xs">
            {item.status !== "pending" && <StatusBadge item={item} />}
            {!hideLocator && (
              <span className="ml-auto truncate text-[11px] text-muted-foreground" title={item.locator}>
                {item.locator}
              </span>
            )}
          </div>
        )}
        {item.status === "error" ? (
          <p className="line-clamp-2 text-xs text-destructive" title={item.error}>
            {item.error || "분석에 실패했습니다."}
          </p>
        ) : summary ? (
          <p className="line-clamp-2 text-xs text-muted-foreground" title={summary}>
            {summary}
          </p>
        ) : null}
        {item.result && (item.result.ocr_text || item.result.details) && (
          <div className="flex flex-wrap items-center gap-1">
            {item.result.ocr_text && (
              <Badge variant="outline" className="h-4 gap-0.5 px-1 text-[10px] font-normal">
                <Type className="size-2.5" /> 텍스트
              </Badge>
            )}
            {item.result.details && (
              <Badge variant="outline" className="h-4 gap-0.5 px-1 text-[10px] font-normal">
                <Table2 className="size-2.5" /> 데이터
              </Badge>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
