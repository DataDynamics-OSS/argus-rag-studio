"use client"

/**
 * 원본·파싱 비교 다이얼로그 — 왼쪽에 원본 파일(파일 보기), 오른쪽에 파싱 결과를 나란히 띄워
 * 파싱이 제대로 됐는지 원본과 대조한다.
 *
 * 파일 보기는 s3 브라우저의 FileViewerContent(pdf/이미지/오피스→PDF/HWP/텍스트)를 재사용하되,
 * admin 전용 s3browse 대신 문서 범위 엔드포인트(로그인 사용자)에 연결한다.
 */

import { useCallback, useEffect, useMemo, useState } from "react"
import { Loader2 } from "lucide-react"
import { Badge } from "@workspace/ui/components/badge"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { toast } from "sonner"
import { CodeViewer } from "@/components/code-viewer"
import { FileViewerContent } from "@/components/local-filesystem-browser/file-viewer-dialog"
import type { FilesystemFile } from "@/components/local-filesystem-browser/types"
import { getDocument, getDocumentFileBytes, getDocumentOfficePdf } from "@/features/documents/api"
import {
  DocumentImageList,
  type DocImageItem,
} from "@/features/search/components/image-type-badges"
import { parsePreviewDocument } from "@/features/ingestion/api"
import type { ParsePreview } from "@/features/ingestion/data/schema"

// 문서 metadata_json 에서 이미지 분류 items 를 안전하게 꺼낸다(없으면 빈 배열).
function readImageItems(metadataJson: string | null | undefined): DocImageItem[] {
  if (!metadataJson) return []
  try {
    const meta = JSON.parse(metadataJson)
    const items = meta?.image_classification?.items
    return Array.isArray(items) ? (items as DocImageItem[]) : []
  } catch {
    return []
  }
}

export function DocumentInspectDialog({
  documentId,
  documentName,
  open,
  onOpenChange,
  highlightText,
}: {
  documentId: string | null // 문서 UUID(document_id)
  documentName: string
  open: boolean
  onOpenChange: (open: boolean) => void
  highlightText?: string // 파싱 결과에서 이 청크 텍스트로 스크롤 + 하이라이트(검색 결과 진입 시)
}) {
  // ── 우측: 파싱 미리보기 ────────────────────────────────────────────────────
  const [parse, setParse] = useState<ParsePreview | null>(null)
  const [parsing, setParsing] = useState(false)
  // 문서에서 식별된 이미지(분류 결과 — metadata_json 에 저장됨).
  const [imageItems, setImageItems] = useState<DocImageItem[]>([])

  const loadParse = useCallback(async (id: string) => {
    setParsing(true)
    try {
      setParse(await parsePreviewDocument(id))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "파싱 미리보기 실패")
      setParse(null)
    } finally {
      setParsing(false)
    }
  }, [])

  // 이미지 분류 결과 로드(있으면 표시, 없거나 실패해도 조용히 비움 — 부가 정보).
  const loadImages = useCallback(async (id: string) => {
    try {
      const doc = await getDocument(id)
      setImageItems(readImageItems(doc.metadata_json))
    } catch {
      setImageItems([])
    }
  }, [])

  useEffect(() => {
    if (open && documentId != null) {
      void loadParse(documentId)
      void loadImages(documentId)
    }
    if (!open) {
      setParse(null)
      setImageItems([])
    }
  }, [open, documentId, loadParse, loadImages])

  // ── 좌측: 파일 보기 — 문서 범위 엔드포인트에 연결한 데이터소스 콜백 ──────────
  const entry: FilesystemFile | null = useMemo(
    () =>
      documentId
        ? { kind: "file", key: documentName, name: documentName, size: 0, lastModified: "" }
        : null,
    [documentId, documentName],
  )

  // 콜백은 path 인자를 무시하고 문서 UUID 로 직접 호출한다.
  const getBytes = useCallback(
    async () => (documentId ? getDocumentFileBytes(documentId) : new ArrayBuffer(0)),
    [documentId],
  )
  const getOfficePdf = useCallback(
    async () => (documentId ? getDocumentOfficePdf(documentId) : null),
    [documentId],
  )
  const getDownloadUrl = useCallback(async () => {
    // 폴백 경로(이미지/영상 등은 getBytes 를 우선 사용하므로 거의 호출되지 않음).
    if (!documentId) return ""
    const buf = await getDocumentFileBytes(documentId)
    return URL.createObjectURL(new Blob([buf]))
  }, [documentId])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] w-[96vw] max-w-[1200px] flex-col">
        <DialogHeader>
          <DialogTitle className="truncate" title={documentName}>
            원본 · 파싱 비교 — {documentName}
          </DialogTitle>
          <DialogDescription>
            왼쪽 원본 파일과 오른쪽 파싱 결과(저장·임베딩 없이 재파싱)를 나란히 비교합니다.
          </DialogDescription>
        </DialogHeader>

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 md:grid-cols-2">
          {/* 좌: 원본 파일 */}
          <div className="flex min-h-0 flex-col overflow-hidden rounded-md border">
            <div className="border-b bg-muted/40 px-3 py-1.5 text-xs font-medium text-muted-foreground">
              원본 파일
            </div>
            <div className="min-h-0 flex-1 overflow-auto p-2">
              <FileViewerContent
                entry={entry}
                active={open}
                getDownloadUrl={getDownloadUrl}
                getBytes={getBytes}
                getOfficePdf={getOfficePdf}
                highlight={highlightText}
              />
            </div>
          </div>

          {/* 우: 파싱 결과 */}
          <div className="flex min-h-0 flex-col overflow-hidden rounded-md border">
            <div className="flex flex-wrap items-center gap-2 border-b bg-muted/40 px-3 py-1.5 text-xs">
              <span className="font-medium text-muted-foreground">파싱 결과</span>
              {parse && (
                <>
                  <Badge variant="secondary">전략: {parse.strategy}</Badge>
                  <span className="text-muted-foreground tabular-nums">
                    {parse.char_count.toLocaleString()}자 · {parse.elapsed_ms}ms
                  </span>
                  {parse.truncated && (
                    <Badge variant="outline" className="text-amber-600">
                      일부만 표시(잘림)
                    </Badge>
                  )}
                </>
              )}
            </div>
            <div className="min-h-0 flex-1 overflow-hidden p-2">
              {parsing ? (
                <div className="flex h-full items-center justify-center">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : !parse ? (
                <p className="py-8 text-center text-sm text-muted-foreground">결과가 없습니다.</p>
              ) : (
                <CodeViewer
                  code={parse.text}
                  language="markdown"
                  height="100%"
                  wordWrap="on"
                  border
                  copyLabel="파싱 결과"
                  highlight={highlightText}
                />
              )}
            </div>
          </div>
        </div>

        {/* 이 문서에서 식별된 이미지(도표/차트 등) — 분류가 켜져 있던 문서만 표시 */}
        {imageItems.length > 0 && (
          <div className="shrink-0 overflow-hidden rounded-md border">
            <div className="border-b bg-muted/40 px-3 py-1.5 text-xs font-medium text-muted-foreground">
              이 문서에서 식별된 이미지 ({imageItems.length})
            </div>
            <div className="max-h-32 overflow-auto p-2">
              <DocumentImageList items={imageItems} />
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
