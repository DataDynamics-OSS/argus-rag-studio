// 검색 결과(청크)의 근거 페이지 보기 — 원본 HWP/HWPX 의 해당 페이지를 렌더해 보여준다.
// 백엔드: GET by-chunk/{id}/evidence(페이지 추정) + GET documents/{uuid}/page/{n}(PNG).
"use client"

import { useState } from "react"
import { FileImage, Loader2 } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { toast } from "sonner"
import { getChunkEvidence, getDocumentPageImage } from "@/features/search/api"

const HWP_RE = /\.hwpx?$/i

/** HWP/HWPX 청크에만 노출. 그 외 문서면 null(버튼 안 보임). */
export function EvidencePageButton({
  chunkId,
  documentName,
}: {
  chunkId: string
  documentName: string
}) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [img, setImg] = useState<string | null>(null)
  const [info, setInfo] = useState<{ page: number; total: number } | null>(null)

  if (!HWP_RE.test(documentName)) return null

  function close(o: boolean) {
    setOpen(o)
    if (!o && img) {
      URL.revokeObjectURL(img)
      setImg(null)
      setInfo(null)
    }
  }

  async function load() {
    setOpen(true)
    setLoading(true)
    try {
      const ev = await getChunkEvidence(chunkId)
      if (!ev.available || !ev.page) {
        toast.error(ev.reason || "근거 페이지를 찾을 수 없습니다.")
        setOpen(false)
        return
      }
      setInfo({ page: ev.page, total: ev.total_pages ?? 0 })
      const blob = await getDocumentPageImage(ev.document_uuid, ev.page)
      setImg(URL.createObjectURL(blob))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "근거 페이지 로드 실패")
      setOpen(false)
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={load}
        className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground"
        title="원본 문서의 해당 페이지 보기"
      >
        <FileImage className="size-3" /> 원본 페이지
      </button>
      <Dialog open={open} onOpenChange={close}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle className="truncate text-sm">
              {documentName}
              {info ? ` · p.${info.page}/${info.total}` : ""}
            </DialogTitle>
          </DialogHeader>
          <div className="max-h-[75vh] overflow-auto">
            {loading ? (
              <div className="flex h-40 items-center justify-center">
                <Loader2 className="size-6 animate-spin text-muted-foreground" />
              </div>
            ) : img ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={img} alt="원본 페이지" className="w-full rounded border" />
            ) : null}
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
