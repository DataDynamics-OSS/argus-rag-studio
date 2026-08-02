/**
 * 문서 청크 인스펙터 — 문서별 인제스천 현황(상태·단계·오류)과 생성된 청크 목록을
 * 보여준다. 청크마다 섹션 경로·문자/토큰 수·임베딩 유무·본문 미리보기를 표시해
 * 파싱·청킹·임베딩이 제대로 됐는지 확인할 수 있다.
 */
"use client"

import { useCallback, useEffect, useState } from "react"
import { FileSearch } from "lucide-react"

import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { toast } from "sonner"
import { getDocumentChunks } from "@/features/documents/api"
import { DocumentInspectDialog } from "@/features/documents/components/document-inspect-dialog"
import type { DocumentChunks } from "@/features/documents/data/schema"
import { formatDateTime } from "@/lib/format"

const STATUS_VARIANT: Record<string, "secondary" | "outline" | "default" | "destructive"> = {
  indexed: "secondary",
  registered: "outline",
  processing: "default",
  failed: "destructive",
}
const STAGE_LABEL: Record<string, string> = {
  parse: "파싱",
  chunk: "청킹",
  embed: "임베딩",
  index: "색인",
}

const PAGE_SIZE = 20

export function DocumentChunksDialog({
  documentId,
  documentName,
  indexedAt,
  open,
  onOpenChange,
}: {
  documentId: string | null // 문서 UUID(document_id)
  documentName: string
  indexedAt: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [data, setData] = useState<DocumentChunks | null>(null)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  // 청크 클릭 → 원본 뷰어에서 해당 위치로 이동(하이라이트). null 이면 닫힘.
  const [inspectText, setInspectText] = useState<string | null>(null)

  const load = useCallback(
    async (id: string, p: number) => {
      setLoading(true)
      try {
        setData(await getDocumentChunks(id, { page: p, page_size: PAGE_SIZE }))
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "청크 조회 실패")
      } finally {
        setLoading(false)
      }
    },
    [],
  )

  // 열릴 때 / 문서 바뀔 때 1페이지 로드
  useEffect(() => {
    if (open && documentId != null) {
      setPage(1)
      load(documentId, 1)
    } else {
      setData(null)
    }
  }, [open, documentId, load])

  function goPage(p: number) {
    if (documentId == null) return
    setPage(p)
    load(documentId, p)
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* 전체 스크롤 금지 — 헤더·요약·페이지네이션은 고정하고 청크 목록만 스크롤 */}
      <DialogContent className="flex max-h-[90vh] flex-col sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="truncate">인제스천 현황 · 청크</DialogTitle>
          <DialogDescription className="truncate">{documentName}</DialogDescription>
        </DialogHeader>

        {/* 현황 요약 */}
        {data && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <Badge variant={STATUS_VARIANT[data.status] ?? "outline"}>{data.status}</Badge>
            {data.last_stage && (
              <Badge variant="outline" className="font-normal">
                단계: {STAGE_LABEL[data.last_stage] ?? data.last_stage}
              </Badge>
            )}
            <Badge
              variant={data.embedded === data.total && data.total > 0 ? "default" : "outline"}
              className="font-normal"
            >
              임베딩 {data.embedded}/{data.total}
            </Badge>
            <span className="text-muted-foreground">청크 {data.total}개</span>
            {indexedAt && (
              <span className="text-muted-foreground">· 색인 {formatDateTime(indexedAt)}</span>
            )}
          </div>
        )}

        {/* 실패 사유 */}
        {data?.last_error && (
          <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            <span className="font-medium">오류:</span> {data.last_error}
          </div>
        )}

        {/* 청크 목록 — 이 영역만 스크롤 */}
        {loading && !data ? (
          <p className="py-8 text-center text-sm text-muted-foreground">불러오는 중...</p>
        ) : data && data.items.length === 0 ? (
          <p className="rounded-md border border-dashed px-3 py-8 text-center text-sm text-muted-foreground">
            생성된 청크가 없습니다. (아직 처리 전이거나 실패한 문서)
          </p>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1">
            {data?.items.map((c) => (
              <div key={c.chunk_id} className="rounded-md border p-3 text-black">
                <div className="mb-1.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                  <Badge variant="outline" className="h-5">
                    #{c.seq}
                  </Badge>
                  {c.section_path && <span className="truncate">{c.section_path}</span>}
                  <span className="ml-auto flex shrink-0 items-center gap-1.5">
                    {c.char_count != null && <span className="tabular-nums">{c.char_count}자</span>}
                    {c.token_count != null && (
                      <span className="tabular-nums">{c.token_count}토큰</span>
                    )}
                    <Badge
                      variant={c.has_embedding ? "secondary" : "destructive"}
                      className="h-5 font-normal"
                    >
                      임베딩 {c.has_embedding ? "O" : "X"}
                    </Badge>
                    <button
                      onClick={() => setInspectText(c.text)}
                      className="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline"
                      title="원본에서 이 청크 위치로 이동(하이라이트)"
                    >
                      <FileSearch className="size-3.5" />
                      원본에서 보기
                    </button>
                  </span>
                </div>
                <p className="line-clamp-4 whitespace-pre-wrap break-words text-sm leading-relaxed">
                  {c.text}
                </p>
              </div>
            ))}
          </div>
        )}

        {/* 페이지네이션 */}
        {data && data.total > PAGE_SIZE && (
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {page} / {totalPages} 페이지
            </span>
            <div className="flex gap-1.5">
              <Button
                variant="outline"
                size="sm"
                disabled={loading || page <= 1}
                onClick={() => goPage(page - 1)}
              >
                이전
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={loading || page >= totalPages}
                onClick={() => goPage(page + 1)}
              >
                다음
              </Button>
            </div>
          </div>
        )}
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
