"use client"

// 라벨링 작업화면 — 좌측에 폴더 내 이미지를 세로 카드 목록(썸네일)으로 쌓고,
// 카드를 클릭하면 우측에 해당 이미지의 어노테이션 편집기를 보여준다.
// 탐색기에서 이미지를 클릭하거나 폴더 선택 후 '라벨링' 버튼으로 진입한다.

import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { ChevronLeft, ChevronRight, Home, Images, Loader2 } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Badge } from "@workspace/ui/components/badge"
import { AnnotationEditor } from "./annotation-editor"
import { ImageThumb } from "./explorer/image-thumb"
import { useIncrementalImages } from "../hooks/use-incremental-images"
import { LoadMore } from "./load-more"

const STATUS_LABEL: Record<string, string> = {
  draft: "업로드",
  in_progress: "작업중",
  completed: "완료",
}

export function LabelingWorkspace({
  folder,
  initialImageId,
  onFilenameChange,
}: {
  folder: string
  initialImageId?: string
  /** 현재 편집 중인 이미지 파일명을 상위(헤더)로 전달. 선택 해제 시 null. */
  onFilenameChange?: (filename: string | null) => void
}) {
  const router = useRouter()
  // 좌측 이미지 목록 — 증분 로딩(무한 스크롤 + 더 보기)
  const {
    items: images,
    total: imageTotal,
    loading,
    loadingMore,
    hasMore,
    reload,
    loadMore,
  } = useIncrementalImages(60)
  const [selected, setSelected] = useState<string | null>(initialImageId ?? null)
  const [listWidth, setListWidth] = useState(200) // 좌측 카드 목록 너비(px)

  const containerRef = useRef<HTMLDivElement>(null)

  // 폴더 이미지 로드(1페이지부터).
  useEffect(() => {
    void reload({ folder })
  }, [folder, reload])

  // 라벨링 대상만(읽기전용 크롭 오브젝트는 제외 — 좌측 목록·기본 선택에서 빠진다).
  const labelImages = images.filter((i) => !i.readonly)

  // 선택 이미지가 없을 때만 로드된 첫 이미지를 기본 선택. 딥링크(initialImageId)는
  // 1페이지 밖일 수 있어도 편집기가 id 로 직접 로드하므로 그대로 둔다.
  useEffect(() => {
    if (!selected && labelImages.length > 0) setSelected(labelImages[0]!.image_id)
  }, [labelImages, selected])

  // 선택 변경 시 URL 동기화(새로고침/공유 시 유지). 히스토리는 쌓지 않는다.
  useEffect(() => {
    if (!selected) return
    const q = new URLSearchParams()
    if (folder) q.set("folder", folder)
    q.set("image", selected)
    router.replace(`/dashboard/annotations/labeling?${q.toString()}`, { scroll: false })
  }, [selected, folder, router])

  // 선택 이미지 파일명을 상위(헤더)로 전달 — 목록에 있으면 즉시,
  // 딥링크처럼 목록 밖이면 편집기 로드(onLoaded)에서 확정한다.
  useEffect(() => {
    if (!onFilenameChange) return
    if (!selected) {
      onFilenameChange(null)
      return
    }
    const hit = images.find((i) => i.image_id === selected)
    if (hit) onFilenameChange(hit.filename)
  }, [selected, images, onFilenameChange])

  // 좌(목록)·우(편집기) 너비 조절 — separator 드래그
  const startResize = useCallback((e: React.PointerEvent) => {
    e.preventDefault()
    const onMove = (ev: PointerEvent) => {
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect) return
      const raw = ev.clientX - rect.left
      const max = Math.max(200, rect.width - 480) // 우측 편집기 최소 480px
      setListWidth(Math.max(200, Math.min(raw, max)))
    }
    const onUp = () => {
      window.removeEventListener("pointermove", onMove)
      window.removeEventListener("pointerup", onUp)
      document.body.style.cursor = ""
      document.body.style.userSelect = ""
    }
    window.addEventListener("pointermove", onMove)
    window.addEventListener("pointerup", onUp)
    document.body.style.cursor = "col-resize"
    document.body.style.userSelect = "none"
  }, [])

  const segments = folder ? folder.split("/") : []

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* 상단 바 — 탐색기로 돌아가기 + 폴더 브레드크럼 */}
      <div className="flex items-center gap-2 border-b px-4 py-2">
        <Button asChild variant="ghost" size="sm">
          <Link href="/dashboard/annotations/explorer">
            <ChevronLeft className="mr-1 h-4 w-4" /> 탐색기로
          </Link>
        </Button>
        <div className="flex min-w-0 items-center gap-1 text-sm text-muted-foreground">
          <Home className="h-3.5 w-3.5" />
          <span>루트</span>
          {segments.map((seg, i) => (
            <span key={i} className="inline-flex min-w-0 items-center gap-1">
              <ChevronRight className="h-3.5 w-3.5" />
              <span className="truncate">{seg}</span>
            </span>
          ))}
        </div>
        <Badge variant="outline" className="ml-auto shrink-0">
          이미지 {images.length}{imageTotal > images.length ? ` / ${imageTotal}` : ""}
        </Badge>
      </div>

      <div ref={containerRef} className="flex flex-1 overflow-hidden">
        {/* 좌측 세로 카드 목록(썸네일) */}
        <div
          className="flex shrink-0 flex-col overflow-hidden border-r"
          style={{ width: listWidth }}
        >
          <div className="flex-1 overflow-y-auto p-2">
            {loading ? (
              <div className="flex h-40 items-center justify-center">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : labelImages.length === 0 ? (
              <p className="px-2 py-12 text-center text-sm text-muted-foreground">
                이 폴더에 이미지가 없습니다.
              </p>
            ) : (
              <div className="flex flex-col gap-2">
                {labelImages.map((img) => {
                  const isSel = img.image_id === selected
                  return (
                    <button
                      key={img.image_id}
                      type="button"
                      onClick={() => setSelected(img.image_id)}
                      className={`group flex w-full flex-col overflow-hidden rounded-lg border text-left transition-colors ${
                        isSel
                          ? "border-primary ring-1 ring-primary"
                          : "hover:border-primary/60 hover:bg-muted/40"
                      }`}
                    >
                      <div className="aspect-video bg-muted">
                        <ImageThumb
                          imageId={img.image_id}
                          alt={img.filename}
                          hasThumbnail={img.has_thumbnail}
                        />
                      </div>
                      <div className="space-y-1 p-2">
                        <p className="truncate text-xs font-medium" title={img.filename}>
                          {img.filename}
                        </p>
                        <div className="flex items-center justify-between">
                          <Badge
                            variant={img.status === "completed" ? "default" : "outline"}
                            className="px-1 py-0 text-[10px]"
                          >
                            {STATUS_LABEL[img.status] ?? img.status}
                          </Badge>
                          <span className="text-[10px] tabular-nums text-muted-foreground">
                            박스 {img.box_count}
                          </span>
                        </div>
                      </div>
                    </button>
                  )
                })}
                <LoadMore hasMore={hasMore} loading={loadingMore} onLoadMore={loadMore} />
              </div>
            )}
          </div>
        </div>

        {/* 드래그 separator */}
        <div
          onPointerDown={startResize}
          role="separator"
          aria-orientation="vertical"
          title="드래그하여 영역 크기 조절"
          className="group relative flex w-2 shrink-0 cursor-col-resize items-stretch justify-center"
        >
          <div className="w-px bg-border transition-colors group-hover:bg-muted-foreground/40" />
        </div>

        {/* 우측 어노테이션 편집기 — 선택 변경 시 remount(key)로 깨끗이 재로딩 */}
        <div className="flex min-w-0 flex-1 overflow-hidden">
          {selected ? (
            <AnnotationEditor
              key={selected}
              imageId={selected}
              onLoaded={(d) => onFilenameChange?.(d.filename)}
            />
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 text-muted-foreground">
              <Images className="h-8 w-8" />
              <p className="text-sm">왼쪽에서 이미지를 선택하세요.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
