"use client"

// 이미지 탐색기 — Windows 탐색기 스타일. 좌측 폴더 트리 + 우측 폴더 내 이미지 그리드.
// 폴더는 MinIO 어노테이션 버킷의 가상 prefix. 이미지 클릭 시 에디터로 이동한다.

import { useCallback, useEffect, useRef, useState } from "react"
import { useUrlState } from "@/hooks/use-tab-state"
import { useRouter } from "next/navigation"
import {
  ChevronDown,
  ChevronRight,
  FileText,
  Folder,
  FolderPlus,
  FolderUp,
  GalleryThumbnails,
  Home,
  ImagePlus,
  LayoutGrid,
  List,
  Loader2,
  Tags,
  Trash2,
  UploadCloud,
} from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Badge } from "@workspace/ui/components/badge"
import { Checkbox } from "@workspace/ui/components/checkbox"
import { Input } from "@workspace/ui/components/input"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { toast } from "sonner"
import { ConfirmDialog } from "@/components/confirm-dialog"
import {
  convertDocument,
  createFolder,
  deleteFolder,
  deleteImage,
  getConvertConfig,
  getObjectBlobUrl,
  listFolders,
  uploadImage,
  uploadThumbnail,
} from "../../api"
import type { AnnotationImage } from "../../data/schema"
import { useIncrementalImages } from "../../hooks/use-incremental-images"
import { LoadMore } from "../load-more"
import { makeThumbnailBlob } from "../../lib/thumbnail"
import { renderHwpToPngs } from "../../lib/hwp-to-images"
import { ImageThumb } from "./image-thumb"
import { ImageInfo } from "./image-info"

type ViewMode = "grid" | "card" | "list"

const STATUS_LABEL: Record<string, string> = {
  draft: "업로드",
  in_progress: "작업중",
  completed: "완료",
}

/** 폴더 경로에서 표시용 이름(마지막 세그먼트). */
function leaf(path: string): string {
  return path.split("/").filter(Boolean).pop() ?? path
}

type DroppedFile = { file: File; rel?: string }

/** DirectoryReader.readEntries 는 한 번에 최대 ~100개만 반환 — 비어질 때까지 반복. */
function readAll(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  return new Promise((resolve, reject) => {
    const out: FileSystemEntry[] = []
    const step = () =>
      reader.readEntries((batch) => {
        if (batch.length === 0) resolve(out)
        else {
          out.push(...batch)
          step()
        }
      }, reject)
    step()
  })
}

/** 드롭된 FileSystemEntry 를 재귀 순회해 {file, 상대경로} 목록으로 모은다(폴더 구조 유지). */
async function collectEntry(entry: FileSystemEntry, prefix: string, out: DroppedFile[]): Promise<void> {
  if (entry.isFile) {
    const file = await new Promise<File>((res, rej) =>
      (entry as FileSystemFileEntry).file(res, rej)
    )
    out.push({ file, rel: prefix + entry.name })
  } else if (entry.isDirectory) {
    const entries = await readAll((entry as FileSystemDirectoryEntry).createReader())
    for (const e of entries) await collectEntry(e, `${prefix}${entry.name}/`, out)
  }
}

export function AnnotationExplorer() {
  const router = useRouter()
  const [current, setCurrent] = useUrlState("", "folder") // 선택 폴더("" = 루트) — back=이전 폴더
  const [childrenMap, setChildrenMap] = useState<Record<string, string[]>>({})
  const [expanded, setExpanded] = useState<Set<string>>(new Set([""])) // 루트는 기본 펼침(1depth 노출)
  // 이미지 목록 — 증분 로딩(오프셋 페이지네이션, 무한 스크롤 + 더 보기)
  const {
    items: images,
    total: imageTotal,
    loading: loadingImages,
    loadingMore: loadingMoreImages,
    hasMore: hasMoreImages,
    reload: reloadImages,
    loadMore: loadMoreImages,
  } = useIncrementalImages(60)
  const [busy, setBusy] = useState(false)
  const [treeWidth, setTreeWidth] = useState(256) // 좌측 폴더 트리 너비(px)
  const [dragOver, setDragOver] = useState(false) // 드래그&드롭 하이라이트
  const [view, setView] = useState<ViewMode>("grid") // 보기 모드(기본 GRID)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set()) // 다중 선택된 이미지
  const [hwpEngine, setHwpEngine] = useState<string>("rhwp") // HWP/HWPX 변환 엔진(설정값)
  const [hwpScale, setHwpScale] = useState<number>(2.0) // rhwp 렌더 배율(설정값)
  const [deleteProgress, setDeleteProgress] = useState<{ done: number; total: number } | null>(null) // 일괄 삭제 진행
  // 문서 변환 진행 — pageTotal=0 이면 부정형(서버 단일 호출) 표시.
  const [convertProgress, setConvertProgress] = useState<{
    fileIndex: number
    fileTotal: number
    filename: string
    label: string
    pageDone: number
    pageTotal: number
  } | null>(null)
  const [convertCanceling, setConvertCanceling] = useState(false) // 취소 요청 후 마무리 대기
  // 파일/폴더 업로드 진행
  const [uploadProgress, setUploadProgress] = useState<{ done: number; total: number; filename: string } | null>(null)

  // 새 폴더 다이얼로그
  const [folderDialogOpen, setFolderDialogOpen] = useState(false)
  const [folderName, setFolderName] = useState("")
  const [folderCreating, setFolderCreating] = useState(false)

  // 확인(삭제) 다이얼로그 — 내용·동작을 동적으로 채운다.
  const [confirm, setConfirm] = useState<{
    title: string
    desc: string
    onConfirm: () => void | Promise<void>
  } | null>(null)
  const [confirmLoading, setConfirmLoading] = useState(false)

  const runConfirm = useCallback(async () => {
    if (!confirm) return
    setConfirmLoading(true)
    try {
      await confirm.onConfirm()
      setConfirm(null)
    } finally {
      setConfirmLoading(false)
    }
  }, [confirm])

  const fileRef = useRef<HTMLInputElement>(null)
  const folderRef = useRef<HTMLInputElement>(null)
  const docRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const convertAbortRef = useRef<AbortController | null>(null) // 문서 변환 취소

  const cancelConvert = useCallback(() => {
    setConvertCanceling(true)
    convertAbortRef.current?.abort()
  }, [])

  // 좌(폴더)·우(이미지) 너비 조절 — separator 드래그
  const startResize = useCallback((e: React.PointerEvent) => {
    e.preventDefault()
    const onMove = (ev: PointerEvent) => {
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect) return
      const raw = ev.clientX - rect.left
      const max = Math.max(180, rect.width - 360) // 우측 이미지 영역 최소 360px
      setTreeWidth(Math.max(180, Math.min(raw, max)))
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

  // 라벨링 작업화면으로 이동 — 폴더(+선택 이미지)를 쿼리로 전달.
  const goLabeling = useCallback(
    (folder: string, imageId?: string) => {
      const q = new URLSearchParams()
      if (folder) q.set("folder", folder)
      if (imageId) q.set("image", imageId)
      router.push(`/dashboard/annotations/labeling?${q.toString()}`)
    },
    [router]
  )

  // 읽기전용 오브젝트(분할 크롭 등) 미리보기 라이트박스
  const [preview, setPreview] = useState<{ url: string; name: string } | null>(null)
  const openPreview = useCallback(async (img: AnnotationImage) => {
    if (!img.object_key) return
    try {
      const url = await getObjectBlobUrl(img.object_key)
      setPreview({ url, name: img.filename })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "미리보기 실패")
    }
  }, [])
  // 카드/행 클릭 — 라벨링 대상이면 작업화면으로, 읽기전용 크롭이면 미리보기.
  const onImageClick = useCallback(
    (img: AnnotationImage) => {
      if (img.readonly) void openPreview(img)
      else goLabeling(img.folder, img.image_id)
    },
    [goLabeling, openPreview]
  )

  const loadChildren = useCallback(async (folder: string) => {
    try {
      const kids = await listFolders(folder)
      setChildrenMap((m) => ({ ...m, [folder]: kids }))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "폴더 조회 실패")
    }
  }, [])

  const loadImages = useCallback(
    (folder: string) => {
      setSelectedIds(new Set()) // 폴더 전환·재로딩 시 선택 초기화
      return reloadImages({ folder })
    },
    [reloadImages]
  )

  // 최초: 루트 폴더·이미지 로드
  useEffect(() => {
    void loadChildren("")
    void loadImages("")
  }, [loadChildren, loadImages])

  // 문서 변환 설정(HWP 엔진) 로드 — 실패 시 기본값(rhwp) 유지.
  useEffect(() => {
    void getConvertConfig()
      .then((c) => {
        setHwpEngine(c.hwp_engine || "rhwp")
        if (c.hwp_scale) setHwpScale(c.hwp_scale)
      })
      .catch(() => {
        /* 조회 실패 시 클라이언트(rhwp) 기본 */
      })
  }, [])

  const selectFolder = useCallback(
    (folder: string) => {
      setCurrent(folder)
      void loadImages(folder)
      if (childrenMap[folder] === undefined) void loadChildren(folder)
    },
    [childrenMap, loadChildren, loadImages]
  )

  const toggleExpand = useCallback(
    (folder: string) => {
      setExpanded((prev) => {
        const next = new Set(prev)
        if (next.has(folder)) next.delete(folder)
        else {
          next.add(folder)
          if (childrenMap[folder] === undefined) void loadChildren(folder)
        }
        return next
      })
    },
    [childrenMap, loadChildren]
  )

  // ── 액션 ──────────────────────────────────────────────────────────────────
  const openNewFolder = () => {
    setFolderName("")
    setFolderDialogOpen(true)
  }

  const submitNewFolder = async () => {
    const name = folderName.trim()
    if (!name) return
    const path = current ? `${current}/${name}` : name
    setFolderCreating(true)
    try {
      await createFolder(path)
      await loadChildren(current)
      setExpanded((p) => new Set(p).add(current))
      toast.success(`폴더 생성: ${name}`)
      setFolderDialogOpen(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "폴더 생성 실패")
    } finally {
      setFolderCreating(false)
    }
  }

  // 공통 업로더 — {file, 상대경로?} 목록을 현재 폴더에 업로드.
  const uploadList = useCallback(
    async (items: DroppedFile[]) => {
      const imgs = items.filter((i) => i.file.type.startsWith("image/"))
      if (imgs.length === 0) {
        toast.error("업로드할 이미지 파일이 없습니다.")
        return
      }
      setBusy(true)
      setUploadProgress({ done: 0, total: imgs.length, filename: "" })
      let ok = 0
      try {
        for (let i = 0; i < imgs.length; i++) {
          const { file, rel } = imgs[i]!
          setUploadProgress({ done: i, total: imgs.length, filename: rel || file.name })
          const r = await uploadImage(file, { folder: current, relativePath: rel })
          ok++
          // 썸네일 자동 생성(실패해도 업로드는 성공 — 편집기 진입 시 백필).
          try {
            const thumb = await makeThumbnailBlob(file)
            await uploadThumbnail(r.image_id, thumb)
          } catch {
            /* 썸네일 생성/업로드 실패 무시 */
          }
          setUploadProgress({ done: i + 1, total: imgs.length, filename: rel || file.name })
        }
        toast.success(`${ok}개 이미지를 업로드했습니다.`)
        await Promise.all([loadImages(current), loadChildren(current)])
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "업로드 실패")
      } finally {
        setBusy(false)
        setUploadProgress(null)
        if (fileRef.current) fileRef.current.value = ""
        if (folderRef.current) folderRef.current.value = ""
      }
    },
    [current, loadImages, loadChildren]
  )

  // HWP/HWPX → 클라이언트(rhwp)에서 페이지별 PNG 로 렌더해 일반 이미지 업로드 경로로 올린다.
  // s3browse 미리보기와 동일 엔진. 반환: {pages, created, overwritten}.
  const convertHwpClient = useCallback(
    async (
      file: File,
      onProgress?: (label: string, done: number, total: number) => void,
      signal?: AbortSignal
    ) => {
      const pages = await renderHwpToPngs(await file.arrayBuffer(), {
        scale: hwpScale,
        signal,
        onProgress: (done, total) => onProgress?.("페이지 렌더", done, total),
      })
      const stem = file.name.replace(/\.(hwpx?|HWPX?)$/i, "") || "document"
      const pad = Math.max(3, String(pages.length).length)
      let created = 0
      let overwritten = 0
      for (let i = 0; i < pages.length; i++) {
        if (signal?.aborted) throw new DOMException("Aborted", "AbortError")
        const name = `${stem}_p${String(i + 1).padStart(pad, "0")}.png`
        const pageFile = new File([pages[i]!.blob], name, { type: "image/png" })
        // overwrite=true — 동일 파일명(재변환)이면 서버가 기존 것을 지우고 새로 만든다.
        const r = await uploadImage(pageFile, { folder: current, overwrite: true, signal })
        created++
        if (r.overwritten) overwritten++
        try {
          const thumb = await makeThumbnailBlob(pageFile)
          await uploadThumbnail(r.image_id, thumb)
        } catch {
          /* 썸네일 실패 무시 */
        }
        onProgress?.("업로드", i + 1, pages.length)
      }
      return { pages: pages.length, created, overwritten }
    },
    [current, hwpScale]
  )

  // 문서 변환 — PDF·오피스는 백엔드, HWP/HWPX 는 클라이언트(rhwp)에서 페이지별 이미지로 변환.
  const onPickDocs = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    const list = Array.from(files)
    const ac = new AbortController()
    convertAbortRef.current = ac
    setBusy(true)
    let createdTotal = 0
    let failed = 0
    let canceled = false
    try {
      for (let fi = 0; fi < list.length; fi++) {
        if (ac.signal.aborted) {
          canceled = true
          break
        }
        const file = list[fi]!
        const base = { fileIndex: fi + 1, fileTotal: list.length, filename: file.name }
        try {
          // HWP/HWPX 는 설정에 따라 클라이언트(rhwp) 또는 서버(LibreOffice). 그 외(pdf·오피스)는 서버.
          const isHwp = /\.(hwp|hwpx)$/i.test(file.name)
          const useClient = isHwp && hwpEngine !== "libreoffice"
          let r
          if (useClient) {
            setConvertProgress({ ...base, label: "준비", pageDone: 0, pageTotal: 0 })
            r = await convertHwpClient(
              file,
              (label, done, total) =>
                setConvertProgress({ ...base, label, pageDone: done, pageTotal: total }),
              ac.signal
            )
          } else {
            // 서버 단일 호출 — 페이지 수를 미리 알 수 없어 부정형(pageTotal=0)으로 표시.
            setConvertProgress({ ...base, label: "서버 변환 중", pageDone: 0, pageTotal: 0 })
            r = await convertDocument(file, { folder: current, signal: ac.signal })
          }
          createdTotal += r.created
          toast.success(
            `'${file.name}' — ${r.created}개 페이지 이미지 생성` +
              (r.overwritten ? ` (${r.overwritten}개 덮어씀)` : "")
          )
        } catch (e) {
          // 취소(AbortError)면 실패로 세지 않고 루프 종료
          if (ac.signal.aborted || (e instanceof DOMException && e.name === "AbortError")) {
            canceled = true
            break
          }
          failed++
          toast.error(`'${file.name}' 변환 실패: ${e instanceof Error ? e.message : "오류"}`)
        }
      }
      if (canceled) {
        toast.info(
          createdTotal > 0
            ? `변환을 취소했습니다. (생성된 이미지 ${createdTotal}개는 유지)`
            : "변환을 취소했습니다."
        )
      }
      // 취소 시 서버가 일부 페이지를 이미 만들었을 수 있어, 변환을 시도했으면 항상 새로고침.
      await Promise.all([loadImages(current), loadChildren(current)])
    } finally {
      setBusy(false)
      setConvertProgress(null)
      setConvertCanceling(false)
      convertAbortRef.current = null
      if (docRef.current) docRef.current.value = ""
    }
  }

  const onPickFiles = (files: FileList | null, structured: boolean) => {
    if (!files || files.length === 0) return
    void uploadList(
      Array.from(files).map((file) => ({
        file,
        rel: structured ? file.webkitRelativePath || undefined : undefined,
      }))
    )
  }

  // 드래그&드롭 업로드 — 폴더(디렉터리)면 구조를 유지해 재귀 수집.
  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    if (busy) return
    const dt = e.dataTransfer
    const entries = Array.from(dt.items ?? [])
      .map((it) => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null))
      .filter((x): x is FileSystemEntry => x != null)

    if (entries.length > 0) {
      const collected: DroppedFile[] = []
      for (const ent of entries) await collectEntry(ent, "", collected)
      await uploadList(collected)
    } else if (dt.files.length > 0) {
      await uploadList(Array.from(dt.files).map((file) => ({ file })))
    }
  }

  const doDeleteFolder = async () => {
    if (!current) return
    try {
      await deleteFolder(current)
      const parent = current.split("/").slice(0, -1).join("/")
      toast.success("폴더를 삭제했습니다.")
      await loadChildren(parent)
      selectFolder(parent)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "폴더 삭제 실패")
    }
  }
  const askDeleteFolder = () => {
    if (!current) return
    setConfirm({
      title: "폴더 삭제",
      desc: `'${current}' 폴더와 그 안의 모든 이미지를 삭제할까요?`,
      onConfirm: doDeleteFolder,
    })
  }

  // ── 다중 선택 ────────────────────────────────────────────────────────────
  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  // 선택 대상은 라벨링 이미지(읽기전용 크롭 제외)만.
  const selectable = images.filter((i) => !i.readonly)
  const allSelected = selectable.length > 0 && selectedIds.size === selectable.length
  const toggleSelectAll = useCallback(() => {
    setSelectedIds((prev) =>
      prev.size === selectable.length ? new Set() : new Set(selectable.map((i) => i.image_id))
    )
  }, [selectable])

  // 선택 이미지 일괄 삭제 — 백엔드가 원본·썸네일을 함께 제거한다.
  const doDeleteSelected = async () => {
    const ids = Array.from(selectedIds)
    if (ids.length === 0) return
    setBusy(true)
    setDeleteProgress({ done: 0, total: ids.length })
    const done: string[] = []
    try {
      for (const id of ids) {
        try {
          await deleteImage(id)
          done.push(id)
        } catch {
          /* 개별 실패는 건너뛰고 계속 진행 */
        }
        setDeleteProgress({ done: done.length, total: ids.length })
      }
      setSelectedIds(new Set())
      if (done.length === ids.length) {
        toast.success(`${done.length}개 이미지를 삭제했습니다.`)
      } else {
        toast.error(`${done.length}/${ids.length}개만 삭제되었습니다. 나머지는 실패했습니다.`)
      }
      // 삭제 후 현재 폴더를 1페이지부터 다시 로드(목록·총계 동기화).
      if (done.length > 0) await loadImages(current)
    } finally {
      setBusy(false)
      setDeleteProgress(null)
    }
  }
  const askDeleteSelected = () => {
    if (selectedIds.size === 0) return
    setConfirm({
      title: "선택 이미지 삭제",
      desc: `선택한 ${selectedIds.size}개 이미지를 삭제할까요? 썸네일도 함께 삭제됩니다.`,
      onConfirm: doDeleteSelected,
    })
  }

  // ── 폴더 트리(재귀) ────────────────────────────────────────────────────────
  const renderNode = (folder: string, depth: number) => {
    const kids = childrenMap[folder]
    const isOpen = expanded.has(folder)
    const isSel = current === folder
    return (
      <div key={folder || "__root__"}>
        <div
          className={`flex cursor-pointer items-center gap-1 rounded px-1 py-1 text-sm ${
            isSel ? "bg-primary/10 text-primary" : "hover:bg-muted/60"
          }`}
          style={{ paddingLeft: depth * 12 + 4 }}
          onClick={() => selectFolder(folder)}
        >
          <button
            type="button"
            className="flex h-4 w-4 shrink-0 items-center justify-center text-muted-foreground"
            onClick={(e) => {
              e.stopPropagation()
              toggleExpand(folder)
            }}
          >
            {isOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
          {folder === "" ? <Home className="h-4 w-4 shrink-0" /> : <Folder className="h-4 w-4 shrink-0" />}
          <span className="truncate">{folder === "" ? "루트" : leaf(folder)}</span>
        </div>
        {isOpen && (
          <div>
            {kids === undefined ? (
              <div className="py-1 text-xs text-muted-foreground" style={{ paddingLeft: (depth + 1) * 12 + 8 }}>
                <Loader2 className="inline h-3 w-3 animate-spin" />
              </div>
            ) : kids.length === 0 ? (
              <div
                className="py-1 text-xs text-muted-foreground"
                style={{ paddingLeft: (depth + 1) * 12 + 8 }}
              >
                하위 폴더 없음
              </div>
            ) : (
              kids.map((k) => renderNode(k, depth + 1))
            )}
          </div>
        )}
      </div>
    )
  }

  // 브레드크럼 세그먼트
  const segments = current ? current.split("/") : []

  return (
    <div ref={containerRef} className="flex flex-1 overflow-hidden">
      {/* 좌측 폴더 트리 */}
      <div
        className="flex shrink-0 flex-col overflow-hidden"
        style={{ width: treeWidth }}
      >
        <div className="flex items-center justify-between border-b px-2 py-2">
          <span className="text-sm font-semibold">폴더</span>
          <Button size="sm" variant="ghost" className="h-7 px-2" onClick={openNewFolder}>
            <FolderPlus className="mr-1 h-4 w-4" /> 새 폴더
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto p-1">{renderNode("", 0)}</div>
      </div>

      {/* 드래그 separator — 흐린 회색 얇은 선 + 넉넉한 히트 영역 */}
      <div
        onPointerDown={startResize}
        role="separator"
        aria-orientation="vertical"
        title="드래그하여 영역 크기 조절"
        className="group relative flex w-2 shrink-0 cursor-col-resize items-stretch justify-center"
      >
        <div className="w-px bg-border transition-colors group-hover:bg-muted-foreground/40" />
      </div>

      {/* 우측 이미지 패널 */}
      <div
        className="relative flex min-w-0 flex-1 flex-col overflow-hidden"
        onDragOver={(e) => {
          e.preventDefault()
          if (!dragOver) setDragOver(true)
        }}
        onDragLeave={(e) => {
          // 패널 바깥으로 나갈 때만 해제(자식 진입 시 깜빡임 방지)
          if (e.currentTarget === e.target) setDragOver(false)
        }}
        onDrop={onDrop}
      >
        {/* 툴바 + 브레드크럼 */}
        <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
          <div className="flex min-w-0 items-center gap-1 text-sm">
            <button className="inline-flex items-center gap-1 hover:underline" onClick={() => selectFolder("")}>
              <Home className="h-3.5 w-3.5" /> 루트
            </button>
            {segments.map((seg, i) => {
              const path = segments.slice(0, i + 1).join("/")
              return (
                <span key={path} className="inline-flex items-center gap-1">
                  <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                  <button className="truncate hover:underline" onClick={() => selectFolder(path)}>
                    {seg}
                  </button>
                </span>
              )
            })}
          </div>

          <div className="ml-auto flex items-center gap-2">
            {/* 다중 선택 — 전체 선택 + 선택 삭제 */}
            {images.length > 0 && (
              <label className="flex cursor-pointer items-center gap-1.5 text-sm text-muted-foreground">
                <Checkbox
                  checked={allSelected}
                  onCheckedChange={toggleSelectAll}
                  aria-label="전체 선택"
                />
                전체
              </label>
            )}
            {selectedIds.size > 0 && (
              <Button
                size="sm"
                variant="outline"
                className="text-destructive hover:text-destructive"
                disabled={busy}
                onClick={askDeleteSelected}
              >
                {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Trash2 className="mr-1 h-4 w-4" />}
                선택 삭제 ({selectedIds.size})
              </Button>
            )}
            {/* 보기 전환 — GRID(기본) / CARD / LIST */}
            <div className="flex items-center rounded-md border p-0.5">
              <Button
                size="icon"
                variant={view === "grid" ? "secondary" : "ghost"}
                className="h-7 w-7"
                title="그리드 보기"
                onClick={() => setView("grid")}
              >
                <LayoutGrid className="h-4 w-4" />
              </Button>
              <Button
                size="icon"
                variant={view === "card" ? "secondary" : "ghost"}
                className="h-7 w-7"
                title="카드 보기"
                onClick={() => setView("card")}
              >
                <GalleryThumbnails className="h-4 w-4" />
              </Button>
              <Button
                size="icon"
                variant={view === "list" ? "secondary" : "ghost"}
                className="h-7 w-7"
                title="목록 보기"
                onClick={() => setView("list")}
              >
                <List className="h-4 w-4" />
              </Button>
            </div>
            <Button
              size="sm"
              disabled={images.length === 0}
              title="이 폴더의 이미지를 라벨링"
              onClick={() => goLabeling(current)}
            >
              <Tags className="mr-1 h-4 w-4" /> 라벨링
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => fileRef.current?.click()}>
              {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <ImagePlus className="mr-1 h-4 w-4" />}
              파일 업로드
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => folderRef.current?.click()}>
              <FolderUp className="mr-1 h-4 w-4" /> 폴더 업로드
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              title="문서(PDF·오피스·HWP)를 페이지별 이미지로 변환해 업로드"
              onClick={() => docRef.current?.click()}
            >
              <FileText className="mr-1 h-4 w-4" /> 문서 변환
            </Button>
            {current && (
              <Button
                size="sm"
                variant="outline"
                className="text-destructive hover:text-destructive"
                onClick={askDeleteFolder}
              >
                <Trash2 className="mr-1 h-4 w-4" /> 폴더 삭제
              </Button>
            )}
          </div>

          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            multiple
            hidden
            onChange={(e) => onPickFiles(e.target.files, false)}
          />
          <input
            type="file"
            hidden
            multiple
            // 폴더 통째 업로드(구조 유지). webkitdirectory 는 표준 타입에 없어 ref 로 설정.
            ref={(el) => {
              folderRef.current = el
              if (el) {
                el.setAttribute("webkitdirectory", "")
                el.setAttribute("directory", "")
              }
            }}
            onChange={(e) => onPickFiles(e.target.files, true)}
          />
          <input
            ref={docRef}
            type="file"
            accept=".pdf,.hwp,.hwpx,.doc,.docx,.ppt,.pptx,.xls,.xlsx"
            multiple
            hidden
            onChange={(e) => void onPickDocs(e.target.files)}
          />
        </div>

        {/* 이미지 그리드 */}
        <div className="flex-1 overflow-y-auto p-3">
          {loadingImages ? (
            <div className="flex h-40 items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : images.length === 0 ? (
            <p className="py-12 text-center text-sm text-muted-foreground">
              이 폴더에 이미지가 없습니다. 상단에서 파일·폴더를 업로드하세요.
            </p>
          ) : view === "list" ? (
            /* 목록 보기 — Windows 탐색기 "자세히" 스타일. 작은 썸네일 + 컬럼. */
            <div className="overflow-hidden rounded-lg border">
              <div className="flex items-center gap-3 border-b bg-muted/40 px-3 py-1.5 text-[11px] font-medium text-muted-foreground">
                <span className="flex w-5 shrink-0 items-center">
                  <Checkbox checked={allSelected} onCheckedChange={toggleSelectAll} aria-label="전체 선택" />
                </span>
                <span className="w-8 shrink-0" />
                <span className="min-w-0 flex-1">이름</span>
                <span className="w-16 shrink-0 text-center">상태</span>
                <span className="w-24 shrink-0 text-right">크기</span>
                <span className="w-12 shrink-0 text-right">박스</span>
                <span className="w-7 shrink-0" />
              </div>
              {images.map((img) => (
                <div
                  key={img.image_id}
                  className={`group flex cursor-pointer items-center gap-3 border-b px-3 py-1.5 text-sm last:border-b-0 hover:bg-muted/50 ${
                    selectedIds.has(img.image_id) ? "bg-primary/5" : ""
                  }`}
                  onClick={() => onImageClick(img)}
                >
                  <span
                    className="flex w-5 shrink-0 items-center"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {!img.readonly && (
                      <Checkbox
                        checked={selectedIds.has(img.image_id)}
                        onCheckedChange={() => toggleSelect(img.image_id)}
                        aria-label={`${img.filename} 선택`}
                      />
                    )}
                  </span>
                  <div className="h-8 w-8 shrink-0 overflow-hidden rounded bg-muted">
                    <ImageThumb
                      imageId={img.image_id}
                      alt={img.filename}
                      hasThumbnail={img.has_thumbnail}
                      objectKey={img.object_key ?? undefined}
                    />
                  </div>
                  <span className="min-w-0 flex-1 truncate" title={img.filename}>
                    {img.filename}
                  </span>
                  <span className="w-16 shrink-0 text-center">
                    {img.readonly ? (
                      <Badge variant="secondary" className="px-1 py-0 text-[10px]">
                        크롭
                      </Badge>
                    ) : (
                      <Badge
                        variant={img.status === "completed" ? "default" : "outline"}
                        className="px-1 py-0 text-[10px]"
                      >
                        {STATUS_LABEL[img.status] ?? img.status}
                      </Badge>
                    )}
                  </span>
                  <span className="w-24 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                    {img.readonly ? "—" : `${img.width}×${img.height}`}
                  </span>
                  <span className="w-12 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                    {img.readonly ? "" : img.box_count}
                  </span>
                  <span
                    className="flex w-7 shrink-0 items-center justify-center"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {!img.readonly && <ImageInfo image={img} />}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div
              className={
                view === "grid"
                  ? "grid grid-cols-[repeat(auto-fill,minmax(110px,1fr))] gap-2"
                  : "grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3"
              }
            >
              {images.map((img) => (
                <div
                  key={img.image_id}
                  className={`group relative cursor-pointer overflow-hidden rounded-lg border hover:border-primary ${
                    selectedIds.has(img.image_id) ? "border-primary ring-2 ring-primary" : ""
                  }`}
                  onClick={() => onImageClick(img)}
                >
                  {img.readonly ? (
                    <span className="absolute left-1 top-1 z-10 rounded bg-background/80 px-1 py-0.5 text-[10px] font-medium text-muted-foreground shadow-sm">
                      크롭
                    </span>
                  ) : (
                    <span
                      className={`absolute left-1 top-1 z-10 rounded bg-background/80 p-0.5 shadow-sm transition-opacity ${
                        selectedIds.has(img.image_id) ? "opacity-100" : "opacity-0 group-hover:opacity-100"
                      }`}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Checkbox
                        checked={selectedIds.has(img.image_id)}
                        onCheckedChange={() => toggleSelect(img.image_id)}
                        aria-label={`${img.filename} 선택`}
                      />
                    </span>
                  )}
                  <div className="aspect-square bg-muted">
                    <ImageThumb
                      imageId={img.image_id}
                      alt={img.filename}
                      hasThumbnail={img.has_thumbnail}
                      objectKey={img.object_key ?? undefined}
                    />
                  </div>
                  {view === "grid" ? (
                    <p className="truncate px-1.5 py-1 text-[11px]" title={img.filename}>
                      {img.filename}
                    </p>
                  ) : (
                    <div className="space-y-1 p-2">
                      <p className="truncate text-xs font-medium" title={img.filename}>
                        {img.filename}
                      </p>
                      <div className="flex items-center justify-between">
                        {img.readonly ? (
                          <Badge variant="secondary" className="px-1 py-0 text-[10px]">
                            크롭
                          </Badge>
                        ) : (
                          <>
                            <Badge
                              variant={img.status === "completed" ? "default" : "outline"}
                              className="px-1 py-0 text-[10px]"
                            >
                              {STATUS_LABEL[img.status] ?? img.status}
                            </Badge>
                            <span className="text-[10px] text-muted-foreground tabular-nums">
                              {img.width}×{img.height} · 박스 {img.box_count}
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                  )}
                  {!img.readonly && (
                    <span
                      className="absolute right-1 top-1 flex h-7 w-7 items-center justify-center rounded bg-background/80 opacity-0 shadow-sm transition-opacity group-hover:opacity-100"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <ImageInfo image={img} />
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* 증분 로딩 — 무한 스크롤 sentinel + 더 보기 버튼 */}
          {!loadingImages && images.length > 0 && (
            <>
              <LoadMore hasMore={hasMoreImages} loading={loadingMoreImages} onLoadMore={loadMoreImages} />
              <p className="pb-2 text-center text-xs text-muted-foreground tabular-nums">
                {images.length}{imageTotal > images.length ? ` / ${imageTotal}` : ""} 이미지
              </p>
            </>
          )}
        </div>

        {/* 드래그&드롭 오버레이 */}
        {dragOver && (
          <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center border-2 border-dashed border-primary bg-primary/10">
            <div className="flex flex-col items-center gap-2 text-primary">
              <UploadCloud className="h-8 w-8" />
              <span className="text-sm font-medium">
                여기에 놓아 &lsquo;{current || "루트"}&rsquo; 폴더에 업로드
              </span>
            </div>
          </div>
        )}

        {/* 업로드 진행 오버레이 */}
        {uploadProgress && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/70">
            <div className="w-80 max-w-[90%] space-y-3 rounded-lg border bg-background p-4 shadow-lg">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Loader2 className="h-4 w-4 animate-spin text-primary" />
                업로드 중
                <span className="ml-auto text-xs tabular-nums text-muted-foreground">
                  {uploadProgress.done}/{uploadProgress.total}
                </span>
              </div>
              {uploadProgress.filename && (
                <p className="truncate text-xs text-muted-foreground" title={uploadProgress.filename}>
                  {uploadProgress.filename}
                </p>
              )}
              <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary transition-all duration-200"
                  style={{
                    width: `${uploadProgress.total ? Math.round((uploadProgress.done / uploadProgress.total) * 100) : 0}%`,
                  }}
                />
              </div>
            </div>
          </div>
        )}

        {/* 문서 변환 진행 오버레이 */}
        {convertProgress && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/70">
            <div className="w-80 max-w-[90%] space-y-3 rounded-lg border bg-background p-4 shadow-lg">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Loader2 className="h-4 w-4 animate-spin text-primary" />
                문서 변환 중
                {convertProgress.fileTotal > 1 && (
                  <span className="ml-auto text-xs tabular-nums text-muted-foreground">
                    파일 {convertProgress.fileIndex}/{convertProgress.fileTotal}
                  </span>
                )}
              </div>
              <p className="truncate text-xs text-muted-foreground" title={convertProgress.filename}>
                {convertProgress.filename}
              </p>
              <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                {convertProgress.pageTotal > 0 ? (
                  <div
                    className="h-full rounded-full bg-primary transition-all duration-200"
                    style={{
                      width: `${Math.round((convertProgress.pageDone / convertProgress.pageTotal) * 100)}%`,
                    }}
                  />
                ) : (
                  // 부정형(서버 단일 호출) — 진행 단위를 알 수 없어 펄스 표시
                  <div className="h-full w-full animate-pulse rounded-full bg-primary/60" />
                )}
              </div>
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs tabular-nums text-muted-foreground">
                  {convertProgress.pageTotal > 0
                    ? `${convertProgress.label} ${convertProgress.pageDone}/${convertProgress.pageTotal}`
                    : convertProgress.label}
                </p>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7"
                  disabled={convertCanceling}
                  onClick={cancelConvert}
                >
                  {convertCanceling ? "취소 중..." : "취소"}
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 새 폴더 다이얼로그 */}
      <Dialog open={folderDialogOpen} onOpenChange={setFolderDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>새 폴더</DialogTitle>
          </DialogHeader>
          <Input
            autoFocus
            value={folderName}
            placeholder="폴더 이름"
            disabled={folderCreating}
            onChange={(e) => setFolderName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && folderName.trim() && !folderCreating) {
                e.preventDefault()
                void submitNewFolder()
              }
            }}
          />
          <DialogFooter>
            <Button variant="outline" disabled={folderCreating} onClick={() => setFolderDialogOpen(false)}>
              취소
            </Button>
            <Button disabled={!folderName.trim() || folderCreating} onClick={() => void submitNewFolder()}>
              {folderCreating && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
              생성
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 확인(삭제) 다이얼로그 */}
      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(o) => {
          if (!o) setConfirm(null)
        }}
        title={confirm?.title ?? ""}
        desc={confirm?.desc ?? ""}
        destructive
        confirmText="삭제"
        isLoading={confirmLoading}
        handleConfirm={() => void runConfirm()}
      >
        {deleteProgress && (
          <div className="space-y-1.5">
            <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-all duration-200"
                style={{
                  width: `${deleteProgress.total ? Math.round((deleteProgress.done / deleteProgress.total) * 100) : 0}%`,
                }}
              />
            </div>
            <p className="text-right text-xs tabular-nums text-muted-foreground">
              {deleteProgress.done} / {deleteProgress.total} 삭제 중...
            </p>
          </div>
        )}
      </ConfirmDialog>

      {/* 읽기전용 크롭 미리보기 라이트박스 */}
      <Dialog
        open={preview !== null}
        onOpenChange={(o) => {
          if (!o) {
            if (preview) URL.revokeObjectURL(preview.url)
            setPreview(null)
          }
        }}
      >
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="truncate" title={preview?.name}>
              {preview?.name}
            </DialogTitle>
          </DialogHeader>
          {preview && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={preview.url}
              alt={preview.name}
              className="mx-auto max-h-[70vh] w-auto object-contain"
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
