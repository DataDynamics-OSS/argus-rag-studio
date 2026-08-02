// 소스 경로 피커 — 등록된 스토리지 소스 내부를 탐색해 파일 1개를 고르는 다이얼로그.
// 인테이크 '소스에서 가져오기'가 사용. 백엔드 GET /storage-sources/{id}/list 를 폴더 단위로 호출한다.
"use client"

import { useCallback, useEffect, useState } from "react"
import { ChevronRight, File, Folder, HardDrive, RefreshCw } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { toast } from "sonner"
import { listSourceDirectory } from "../api"
import type { SourceEntry } from "../data/schema"

function fmtSize(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function SourcePathPicker({
  open,
  onOpenChange,
  sourceId,
  sourceName,
  onSelect,
  folderMode = false,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  sourceId: string
  sourceName: string
  onSelect: (path: string) => void
  folderMode?: boolean // true 면 파일 대신 "현재 폴더"를 선택(폴더 일괄 인테이크의 prefix 지정용)
}) {
  const [prefix, setPrefix] = useState("")
  const [entries, setEntries] = useState<SourceEntry[]>([])
  const [truncated, setTruncated] = useState(false)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (p: string) => {
    setLoading(true)
    try {
      const res = await listSourceDirectory(sourceId, p)
      setEntries(res.entries)
      setTruncated(res.truncated)
      setPrefix(p)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "경로 조회 실패")
    } finally {
      setLoading(false)
    }
  }, [sourceId])

  // 열릴 때마다 루트부터 다시 탐색(소스가 바뀌었을 수 있음).
  useEffect(() => {
    if (open) load("")
  }, [open, load])

  const crumbs = prefix ? prefix.split("/") : []

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><HardDrive className="size-4" /> {sourceName}</DialogTitle>
          <DialogDescription>
            {folderMode
              ? "폴더를 클릭해 안으로 들어간 뒤, 아래 '이 폴더 선택'을 누르십시오."
              : "가져올 파일을 선택하십시오. 폴더를 클릭하면 안으로 들어갑니다."}
          </DialogDescription>
        </DialogHeader>

        {/* 경로(브레드크럼) */}
        <div className="flex flex-wrap items-center gap-1 text-sm">
          <button type="button" className="font-medium text-primary hover:underline" onClick={() => load("")}>루트</button>
          {crumbs.map((seg, i) => (
            <span key={i} className="flex items-center gap-1">
              <ChevronRight className="size-3.5 text-muted-foreground" />
              <button
                type="button"
                className="text-primary hover:underline"
                onClick={() => load(crumbs.slice(0, i + 1).join("/"))}
              >
                {seg}
              </button>
            </span>
          ))}
          <Button variant="ghost" size="sm" className="ml-auto h-7 px-2" onClick={() => load(prefix)} disabled={loading}>
            <RefreshCw className="size-3.5" />
          </Button>
        </div>

        <div className="max-h-80 overflow-y-auto rounded-md border">
          {loading ? (
            <p className="py-8 text-center text-sm text-muted-foreground">불러오는 중...</p>
          ) : entries.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">비어 있는 폴더입니다.</p>
          ) : (
            <ul className="divide-y">
              {entries.map((e) => (
                <li key={e.path}>
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-muted/50"
                    onClick={() => {
                      if (e.is_dir) load(e.path)
                      else if (!folderMode) {
                        onSelect(e.path)
                        onOpenChange(false)
                      }
                    }}
                  >
                    {e.is_dir
                      ? <Folder className="size-4 shrink-0 text-muted-foreground" />
                      : <File className="size-4 shrink-0 text-muted-foreground" />}
                    <span className="flex-1 truncate">{e.name}</span>
                    {!e.is_dir && <span className="text-xs tabular-nums text-muted-foreground">{fmtSize(e.size)}</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {truncated && (
          <p className="text-xs text-muted-foreground">항목이 많아 일부만 표시했습니다(최대 1000개).</p>
        )}
        {folderMode && (
          <div className="flex items-center justify-between gap-2">
            <span className="truncate font-mono text-xs text-muted-foreground">{prefix || "(루트)"}</span>
            <Button size="sm" onClick={() => { onSelect(prefix); onOpenChange(false) }}>
              <Folder className="size-4" /> 이 폴더 선택
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
