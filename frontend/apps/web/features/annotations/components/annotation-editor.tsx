"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Check, Download, Eye, Loader2, Menu, Minus, Plus, Maximize, Save, ScanText, Scissors, Upload, X } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Badge } from "@workspace/ui/components/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@workspace/ui/components/dropdown-menu"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@workspace/ui/components/tabs"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@workspace/ui/components/tooltip"
import { toast } from "sonner"
import { CodeViewer } from "@/components/code-viewer"
import type { AnnotationDetail, AnnotationMeta, Box, DetectedBox } from "../data/schema"
import {
  detectBoxes,
  exportCrops,
  exportImage,
  fetchExportJson,
  getImage,
  getImageBlobUrl,
  parseAihubJson,
  saveBoxes,
  updateImage,
  uploadThumbnail,
} from "../api"
import { makeThumbnailBlob } from "../lib/thumbnail"
import { AnnotationGuide } from "./annotation-guide"
import { BoxList } from "./box-list"
import { ImageInfo } from "./image-info"
import { MetadataForm } from "./metadata-form"

const MIN_BOX = 4 // 이미지 픽셀 기준 최소 박스 크기
const AUTOSAVE_MS = 2000 // 자동 저장 디바운스 주기
const SAVED_FLASH_MS = 2000 // "자동 저장됨" 표시 유지 시간

type DragMode = "create" | "move" | "resize"
interface DragState {
  mode: DragMode
  seq: number | null
  startImgX: number
  startImgY: number
  orig: Box | null
}

export function AnnotationEditor({
  imageId,
  onLoaded,
}: {
  imageId: string
  /** 이미지 상세를 로드한 직후 호출 — 상위(헤더 등)에서 파일명 표시에 사용. */
  onLoaded?: (detail: AnnotationDetail) => void
}) {
  const [detail, setDetail] = useState<AnnotationDetail | null>(null)
  const [imgUrl, setImgUrl] = useState<string>("")
  const [boxes, setBoxes] = useState<Box[]>([])
  const [meta, setMeta] = useState<AnnotationMeta>({})
  const [selectedSeq, setSelectedSeq] = useState<number | null>(null)
  const [editingSeq, setEditingSeq] = useState<number | null>(null) // 더블클릭 인라인 편집 중인 박스
  const [editingText, setEditingText] = useState("")
  const [editingCand, setEditingCand] = useState<number | null>(null) // 더블클릭 편집 중인 후보 index
  const [editingCandText, setEditingCandText] = useState("")
  const [scale, setScale] = useState(1)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [justSaved, setJustSaved] = useState(false) // 저장 직후 잠깐 표시
  const [draft, setDraft] = useState<Box | null>(null)
  const [detecting, setDetecting] = useState(false) // 자동 인식 진행 중
  const [candidates, setCandidates] = useState<DetectedBox[]>([]) // 자동 인식 후보(미확정)
  const [splitting, setSplitting] = useState(false) // 이미지 분할(크롭 내보내기) 진행 중
  const [jsonOpen, setJsonOpen] = useState(false)
  const [jsonText, setJsonText] = useState("")
  const [jsonLoading, setJsonLoading] = useState(false)
  const [panelWidth, setPanelWidth] = useState(320) // 우측 메타데이터 패널 너비(px)

  const importInputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<DragState | null>(null)
  const boxesRef = useRef<Box[]>([])
  const metaRef = useRef<AnnotationMeta>({})
  const boxSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const metaSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const savedFlashTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const thumbDoneRef = useRef(false) // 썸네일 백필 1회 가드

  // 저장 완료 시점에 "자동 저장됨"을 잠깐 표시하고 일정 시간 뒤 사라지게 한다.
  const markSaved = useCallback(() => {
    setJustSaved(true)
    if (savedFlashTimer.current) clearTimeout(savedFlashTimer.current)
    savedFlashTimer.current = setTimeout(() => setJustSaved(false), SAVED_FLASH_MS)
  }, [])

  // 최신 boxes/meta 를 ref 로 동기화(이벤트 핸들러/디바운스에서 stale 값 방지)
  useEffect(() => {
    boxesRef.current = boxes
  }, [boxes])
  useEffect(() => {
    metaRef.current = meta
  }, [meta])

  // ── 초기 로드 ────────────────────────────────────────────────────────────
  useEffect(() => {
    let revoked = ""
    ;(async () => {
      try {
        const d = await getImage(imageId)
        setDetail(d)
        onLoaded?.(d)
        setBoxes(d.boxes)
        setMeta(d.meta ?? {})
        const url = await getImageBlobUrl(imageId)
        revoked = url
        setImgUrl(url)
        // 초기 스케일: 가로 880px 에 맞춤
        if (d.width > 0) setScale(Math.min(1, 880 / d.width))
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "로드 실패")
      } finally {
        setLoading(false)
      }
    })()
    return () => {
      if (revoked) URL.revokeObjectURL(revoked)
    }
  }, [imageId])

  // ── 썸네일 백필 — 진입 시 썸네일이 없으면 로드된 이미지로 생성·업로드(1회) ──
  const hasThumb = detail?.has_thumbnail
  useEffect(() => {
    if (thumbDoneRef.current || !imgUrl || hasThumb !== false) return
    thumbDoneRef.current = true
    const img = new Image()
    img.onload = async () => {
      try {
        const blob = await makeThumbnailBlob(img)
        await uploadThumbnail(imageId, blob)
        setDetail((p) => (p ? { ...p, has_thumbnail: true } : p))
      } catch {
        thumbDoneRef.current = false // 실패 시 재시도 허용
      }
    }
    img.onerror = () => {
      thumbDoneRef.current = false
    }
    img.src = imgUrl
  }, [imgUrl, imageId, hasThumb])

  // ── 자동 저장(디바운스) ───────────────────────────────────────────────────
  const scheduleBoxSave = useCallback(() => {
    if (boxSaveTimer.current) clearTimeout(boxSaveTimer.current)
    boxSaveTimer.current = setTimeout(async () => {
      try {
        setSaving(true)
        const d = await saveBoxes(imageId, boxesRef.current)
        setDetail(d)
        markSaved()
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "저장 실패")
      } finally {
        setSaving(false)
      }
    }, AUTOSAVE_MS)
  }, [imageId, markSaved])

  const scheduleMetaSave = useCallback(() => {
    if (metaSaveTimer.current) clearTimeout(metaSaveTimer.current)
    metaSaveTimer.current = setTimeout(async () => {
      try {
        setSaving(true)
        await updateImage(imageId, { meta: metaRef.current })
        markSaved()
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "메타 저장 실패")
      } finally {
        setSaving(false)
      }
    }, AUTOSAVE_MS)
  }, [imageId, markSaved])

  useEffect(
    () => () => {
      if (boxSaveTimer.current) clearTimeout(boxSaveTimer.current)
      if (metaSaveTimer.current) clearTimeout(metaSaveTimer.current)
      if (savedFlashTimer.current) clearTimeout(savedFlashTimer.current)
    },
    []
  )

  // ── 좌표 변환 ─────────────────────────────────────────────────────────────
  const toImg = useCallback(
    (clientX: number, clientY: number) => {
      const rect = stageRef.current?.getBoundingClientRect()
      if (!rect) return { x: 0, y: 0 }
      const w = detail?.width ?? 0
      const h = detail?.height ?? 0
      const x = Math.round((clientX - rect.left) / scale)
      const y = Math.round((clientY - rect.top) / scale)
      return {
        x: Math.max(0, Math.min(x, w)),
        y: Math.max(0, Math.min(y, h)),
      }
    },
    [scale, detail]
  )

  const nextSeq = useCallback(
    () => (boxesRef.current.length ? Math.max(...boxesRef.current.map((b) => b.seq)) + 1 : 1),
    []
  )

  // ── 박스 변경 헬퍼 ─────────────────────────────────────────────────────────
  const mutateBoxes = useCallback(
    (next: Box[]) => {
      setBoxes(next)
      scheduleBoxSave()
    },
    [scheduleBoxSave]
  )

  const updateText = useCallback(
    (seq: number, data: string) => mutateBoxes(boxesRef.current.map((b) => (b.seq === seq ? { ...b, data } : b))),
    [mutateBoxes]
  )

  const deleteBox = useCallback(
    (seq: number) => {
      mutateBoxes(boxesRef.current.filter((b) => b.seq !== seq))
      setSelectedSeq((s) => (s === seq ? null : s))
      setEditingSeq((e) => (e === seq ? null : e))
    },
    [mutateBoxes]
  )

  // ── 박스 텍스트 인라인 편집(더블클릭) ──────────────────────────────────────
  const beginEdit = useCallback((box: Box) => {
    setSelectedSeq(box.seq)
    setEditingSeq(box.seq)
    setEditingText(box.data)
  }, [])

  const commitEdit = useCallback(() => {
    if (editingSeq == null) return
    updateText(editingSeq, editingText.trim())
    setEditingSeq(null)
  }, [editingSeq, editingText, updateText])

  const cancelEdit = useCallback(() => setEditingSeq(null), [])

  const renumber = useCallback(() => {
    const ordered = [...boxesRef.current].sort((a, b) => a.seq - b.seq)
    mutateBoxes(ordered.map((b, i) => ({ ...b, seq: i + 1 })))
  }, [mutateBoxes])

  const onMetaChange = useCallback(
    (m: AnnotationMeta) => {
      setMeta(m)
      metaRef.current = m
      scheduleMetaSave()
    },
    [scheduleMetaSave]
  )

  // 박스를 그릴 때마다 작성일(Images.data_captured)을 오늘 날짜(YYYY.MM.DD)로 갱신.
  const stampCapturedDate = useCallback(() => {
    const d = new Date()
    const ymd = `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(
      d.getDate()
    ).padStart(2, "0")}`
    const prev = metaRef.current
    if ((prev.Images as Record<string, unknown> | undefined)?.data_captured === ymd) return
    const next: AnnotationMeta = {
      ...prev,
      Images: { ...(prev.Images as Record<string, unknown> | undefined), data_captured: ymd },
    }
    metaRef.current = next
    setMeta(next)
    scheduleMetaSave()
  }, [scheduleMetaSave])

  // ── 자동 인식(검출 서버 OCR) — 후보를 받아 검수 후 추가 ─────────────────────
  const handleDetect = useCallback(async () => {
    try {
      setDetecting(true)
      const found = await detectBoxes(imageId)
      if (!found.length) {
        toast.info("인식된 텍스트 영역이 없습니다.")
        return
      }
      setCandidates(found)
      toast.success(`자동 인식 ${found.length}개 — 검토 후 추가하세요.`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "자동 인식 실패")
    } finally {
      setDetecting(false)
    }
  }, [imageId])

  // 후보 전체를 실제 박스로 추가(기존 박스 뒤에 seq 이어붙임) 후 자동저장.
  const acceptCandidates = useCallback(() => {
    if (!candidates.length) return
    let seq = nextSeq()
    const added: Box[] = candidates.map((c) => ({
      seq: seq++,
      data: c.data,
      x1: c.x1,
      y1: c.y1,
      x2: c.x2,
      y2: c.y2,
    }))
    mutateBoxes([...boxesRef.current, ...added])
    setCandidates([])
    setEditingCand(null)
    stampCapturedDate()
    toast.success(`박스 ${added.length}개 추가됨`)
  }, [candidates, nextSeq, mutateBoxes, stampCapturedDate])

  // ── 후보 개별 검수 — 단어별 삭제(hover X)·텍스트 편집(더블클릭) ───────────────
  const deleteCand = useCallback((i: number) => {
    setCandidates((prev) => prev.filter((_, idx) => idx !== i))
    setEditingCand((e) => (e === i ? null : e))
  }, [])

  const beginEditCand = useCallback((i: number, c: DetectedBox) => {
    setEditingCand(i)
    setEditingCandText(c.data)
  }, [])

  const commitEditCand = useCallback(() => {
    if (editingCand == null) return
    const text = editingCandText.trim()
    setCandidates((prev) => prev.map((c, idx) => (idx === editingCand ? { ...c, data: text } : c)))
    setEditingCand(null)
  }, [editingCand, editingCandText])

  const cancelEditCand = useCallback(() => setEditingCand(null), [])

  // ── 포인터 인터랙션(생성/이동/리사이즈) ────────────────────────────────────
  const beginStageDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return
    const { x, y } = toImg(e.clientX, e.clientY)
    dragRef.current = { mode: "create", seq: null, startImgX: x, startImgY: y, orig: null }
    setDraft({ seq: -1, data: "", x1: x, y1: y, x2: x, y2: y })
    setSelectedSeq(null)
  }

  const beginBoxDown = (e: React.PointerEvent, box: Box, mode: DragMode) => {
    e.stopPropagation()
    if (e.button !== 0) return
    const { x, y } = toImg(e.clientX, e.clientY)
    dragRef.current = { mode, seq: box.seq, startImgX: x, startImgY: y, orig: { ...box } }
    setSelectedSeq(box.seq)
  }

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const drag = dragRef.current
      if (!drag) return
      const { x, y } = toImg(e.clientX, e.clientY)
      if (drag.mode === "create") {
        setDraft({ seq: -1, data: "", x1: drag.startImgX, y1: drag.startImgY, x2: x, y2: y })
        return
      }
      if (!drag.orig) return
      const dx = x - drag.startImgX
      const dy = y - drag.startImgY
      const w = detail?.width ?? 0
      const h = detail?.height ?? 0
      setBoxes((prev) =>
        prev.map((b) => {
          if (b.seq !== drag.seq) return b
          const o = drag.orig!
          if (drag.mode === "move") {
            const bw = o.x2 - o.x1
            const bh = o.y2 - o.y1
            let nx1 = o.x1 + dx
            let ny1 = o.y1 + dy
            nx1 = Math.max(0, Math.min(nx1, w - bw))
            ny1 = Math.max(0, Math.min(ny1, h - bh))
            return { ...b, x1: nx1, y1: ny1, x2: nx1 + bw, y2: ny1 + bh }
          }
          // resize (우하단 핸들)
          return {
            ...b,
            x2: Math.max(o.x1 + MIN_BOX, Math.min(o.x2 + dx, w)),
            y2: Math.max(o.y1 + MIN_BOX, Math.min(o.y2 + dy, h)),
          }
        })
      )
    }

    const onUp = () => {
      const drag = dragRef.current
      dragRef.current = null
      if (!drag) return
      if (drag.mode === "create") {
        setDraft((d) => {
          if (d) {
            const x1 = Math.min(d.x1, d.x2)
            const y1 = Math.min(d.y1, d.y2)
            const x2 = Math.max(d.x1, d.x2)
            const y2 = Math.max(d.y1, d.y2)
            if (x2 - x1 >= MIN_BOX && y2 - y1 >= MIN_BOX) {
              const seq = nextSeq()
              const created: Box = { seq, data: "", x1, y1, x2, y2 }
              mutateBoxes([...boxesRef.current, created])
              setSelectedSeq(seq)
              stampCapturedDate()
            }
          }
          return null
        })
      } else {
        // 이동/리사이즈 종료 → 저장
        mutateBoxes(boxesRef.current)
      }
    }

    window.addEventListener("pointermove", onMove)
    window.addEventListener("pointerup", onUp)
    return () => {
      window.removeEventListener("pointermove", onMove)
      window.removeEventListener("pointerup", onUp)
    }
  }, [toImg, detail, nextSeq, mutateBoxes, stampCapturedDate])

  // ── 키보드: 선택 박스 삭제 / 미세 이동 ─────────────────────────────────────
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (selectedSeq == null) return
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === "INPUT" || tag === "TEXTAREA") return
      if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault()
        deleteBox(selectedSeq)
        return
      }
      const step = e.shiftKey ? 10 : 1
      const delta: Record<string, [number, number]> = {
        ArrowLeft: [-step, 0],
        ArrowRight: [step, 0],
        ArrowUp: [0, -step],
        ArrowDown: [0, step],
      }
      const d = delta[e.key]
      if (d) {
        e.preventDefault()
        const w = detail?.width ?? 0
        const h = detail?.height ?? 0
        mutateBoxes(
          boxesRef.current.map((b) => {
            if (b.seq !== selectedSeq) return b
            const bw = b.x2 - b.x1
            const bh = b.y2 - b.y1
            const nx1 = Math.max(0, Math.min(b.x1 + d[0], w - bw))
            const ny1 = Math.max(0, Math.min(b.y1 + d[1], h - bh))
            return { ...b, x1: nx1, y1: ny1, x2: nx1 + bw, y2: ny1 + bh }
          })
        )
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [selectedSeq, deleteBox, mutateBoxes, detail])

  const setStatus = async (status: string) => {
    try {
      // 완료 전환 시: 디바운스 대기 중인 박스·메타를 먼저 저장해야 백엔드가 최신 상태로
      // 라벨 JSON(이미지 옆 사이드카)을 만든다.
      if (status === "completed") await flushSaves()
      const d = await updateImage(imageId, { status })
      setDetail((prev) => (prev ? { ...prev, status: d.status } : prev))
      toast.success(status === "completed" ? "완료 — 라벨 JSON을 저장했습니다." : "상태가 변경되었습니다.")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "상태 변경 실패")
    }
  }

  // ── 디바운스 자동저장을 즉시 반영(미리보기/가져오기 전 최신화) ──────────────
  const flushSaves = useCallback(async () => {
    if (boxSaveTimer.current) {
      clearTimeout(boxSaveTimer.current)
      boxSaveTimer.current = null
    }
    if (metaSaveTimer.current) {
      clearTimeout(metaSaveTimer.current)
      metaSaveTimer.current = null
    }
    const d = await saveBoxes(imageId, boxesRef.current)
    await updateImage(imageId, { meta: metaRef.current })
    setDetail(d)
    markSaved()
  }, [imageId, markSaved])

  // 저장 버튼 — 디바운스를 기다리지 않고 즉시 저장.
  const handleManualSave = useCallback(async () => {
    try {
      setSaving(true)
      await flushSaves()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "저장 실패")
    } finally {
      setSaving(false)
    }
  }, [flushSaves])

  // 이미지 분할 — 각 bbox 를 잘라 학습 데이터(크롭 PNG + JSONL)로 내보낸다.
  // 디바운스 대기 중인 박스를 먼저 저장(flush)해 서버가 최신 박스로 크롭하게 한다.
  const handleSplit = useCallback(async () => {
    if (boxesRef.current.length === 0) return
    try {
      setSplitting(true)
      await flushSaves()
      const r = await exportCrops(imageId)
      toast.success(
        `이미지 분할 완료 — 크롭 ${r.crops}개 저장` +
          (r.skipped_boxes ? ` (${r.skipped_boxes}개 건너뜀)` : "")
      )
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "이미지 분할 실패")
    } finally {
      setSplitting(false)
    }
  }, [imageId, flushSaves])

  // ── JSON 가져오기(현재 이미지에 bbox·메타 적용) ────────────────────────────
  const handleImportFile = async (file: File) => {
    try {
      const { boxes: imported, meta: importedMeta } = parseAihubJson(await file.text())
      setBoxes(imported)
      boxesRef.current = imported
      setMeta(importedMeta)
      metaRef.current = importedMeta
      setSelectedSeq(null)
      scheduleBoxSave()
      scheduleMetaSave()
      toast.success(`JSON 가져오기 완료 — 박스 ${imported.length}개`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "JSON 가져오기 실패")
    }
  }

  // ── JSON 보기(현재 상태를 AI-Hub 포맷으로 미리보기) ────────────────────────
  const openJsonView = async () => {
    setJsonOpen(true)
    setJsonLoading(true)
    try {
      await flushSaves()
      setJsonText(await fetchExportJson(imageId))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "JSON 조회 실패")
      setJsonText("")
    } finally {
      setJsonLoading(false)
    }
  }

  // ── 좌(캔버스)·우(메타) 영역 너비 조절 — separator 드래그 ──────────────────
  const startResize = useCallback((e: React.PointerEvent) => {
    e.preventDefault()
    const onMove = (ev: PointerEvent) => {
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect) return
      // 패널 왼쪽 모서리가 커서를 따라오도록 너비 계산(우측 패딩 16px 보정).
      const raw = rect.right - ev.clientX - 16
      const max = Math.max(280, rect.width - 315) // 좌측 캔버스 최소 315px 보장
      setPanelWidth(Math.max(280, Math.min(raw, max)))
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

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }
  if (!detail) {
    return <div className="p-6 text-sm text-muted-foreground">이미지를 찾을 수 없습니다.</div>
  }

  const dispW = detail.width * scale
  const dispH = detail.height * scale

  return (
    <div ref={containerRef} className="relative flex flex-1 overflow-hidden p-4">
      {/* 캔버스 영역 */}
      <div className="flex flex-1 flex-col overflow-hidden rounded-lg border bg-muted/30">
        <div className="flex items-center gap-2 border-b bg-background px-3 py-2">
          <span className="truncate text-sm font-medium" title={detail.filename}>
            {detail.filename}
          </span>
          <Badge variant="outline" className="shrink-0">
            {detail.width}×{detail.height}
          </Badge>
          <TooltipProvider delayDuration={150}>
            <Tooltip>
              {/* disabled 버튼은 포인터 이벤트를 받지 못해 span 으로 감싸 툴팁을 띄운다. */}
              <TooltipTrigger asChild>
                <span className="ml-auto inline-flex shrink-0">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8"
                    onClick={handleDetect}
                    disabled={detecting || candidates.length > 0}
                  >
                    {detecting ? (
                      <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                    ) : (
                      <ScanText className="mr-1 h-4 w-4" />
                    )}
                    자동 인식
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent
                side="bottom"
                className="max-w-xs items-start whitespace-normal text-left leading-relaxed"
              >
                <div className="space-y-1.5">
                  <p className="font-medium">AI Agent 자동 인식</p>
                  <p>
                    AI 에이전트가 이미지에서 텍스트 영역(bbox)을 검출해 후보로 제시합니다.
                    검토 후 &lsquo;전체 추가&rsquo;로 확정하세요.
                  </p>
                  <div className="space-y-0.5 border-t border-background/20 pt-1.5">
                    <p className="font-medium">제약 조건</p>
                    <ul className="list-disc space-y-0.5 pl-4">
                      <li>
                        긴 글·문단이 많은 이미지는 인식률이 현저히 떨어집니다 — 짧은 텍스트
                        영역에 적합합니다.
                      </li>
                      <li>저해상도·기울어짐·표/도형 위 텍스트는 정확도가 낮을 수 있습니다.</li>
                      <li>후보는 자동 저장되지 않으며 반드시 사람이 검수해야 합니다.</li>
                    </ul>
                  </div>
                </div>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <div className="flex items-center gap-1">
            <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => setScale((s) => Math.max(0.1, +(s - 0.1).toFixed(2)))}>
              <Minus className="h-4 w-4" />
            </Button>
            <span className="w-12 text-center text-xs tabular-nums">{Math.round(scale * 100)}%</span>
            <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => setScale((s) => Math.min(3, +(s + 0.1).toFixed(2)))}>
              <Plus className="h-4 w-4" />
            </Button>
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8"
              title="가로 맞춤"
              onClick={() => setScale(detail.width > 0 ? Math.min(1, 880 / detail.width) : 1)}
            >
              <Maximize className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {candidates.length > 0 && (
          <div className="flex items-center gap-2 border-b bg-amber-50 px-3 py-2 text-sm dark:bg-amber-950/30">
            <ScanText className="h-4 w-4 shrink-0 text-amber-600" />
            <span className="truncate">
              자동 인식 후보 <b>{candidates.length}</b>개 — 검토 후 추가하세요.
            </span>
            <div className="ml-auto flex shrink-0 gap-2">
              <Button size="sm" variant="outline" className="h-7" onClick={() => setCandidates([])}>
                취소
              </Button>
              <Button size="sm" className="h-7" onClick={acceptCandidates}>
                전체 추가
              </Button>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-auto p-4">
          <div
            ref={stageRef}
            onPointerDown={beginStageDown}
            className="relative select-none"
            style={{ width: dispW, height: dispH, touchAction: "none" }}
          >
            {imgUrl && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={imgUrl}
                alt={detail.filename}
                draggable={false}
                className="pointer-events-none absolute inset-0 h-full w-full"
              />
            )}

            {boxes.map((b) => {
              const selected = b.seq === selectedSeq
              const editing = b.seq === editingSeq
              return (
                <div
                  key={b.seq}
                  onPointerDown={(e) => beginBoxDown(e, b, "move")}
                  onDoubleClick={(e) => {
                    e.stopPropagation()
                    beginEdit(b)
                  }}
                  className={`group absolute cursor-move ${
                    selected ? "border-2 border-primary bg-primary/10" : "border border-emerald-500/80 bg-emerald-500/5 hover:bg-emerald-500/15"
                  }`}
                  style={{
                    left: b.x1 * scale,
                    top: b.y1 * scale,
                    width: (b.x2 - b.x1) * scale,
                    height: (b.y2 - b.y1) * scale,
                  }}
                >
                  {editing ? (
                    // 더블클릭 인라인 편집 — Enter 저장, Esc 취소, 포커스 해제 시 저장.
                    <input
                      autoFocus
                      value={editingText}
                      onChange={(e) => setEditingText(e.target.value)}
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={(e) => e.stopPropagation()}
                      onDoubleClick={(e) => e.stopPropagation()}
                      onBlur={commitEdit}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault()
                          commitEdit()
                        } else if (e.key === "Escape") {
                          e.preventDefault()
                          cancelEdit()
                        }
                      }}
                      placeholder="텍스트 입력"
                      className="absolute -top-6 left-0 z-20 w-40 rounded border border-primary bg-background px-1 py-0.5 text-[11px] leading-tight text-foreground shadow-sm outline-none"
                    />
                  ) : (
                    <span className="absolute -top-4 left-0 rounded bg-foreground px-1 text-[10px] leading-tight text-background">
                      {b.seq}
                      {b.data ? `·${b.data}` : ""}
                    </span>
                  )}
                  {/* 마우스 오버 시 X — 바로 삭제. opacity 로 토글해 박스↔X 사이 간격에서 hover 가 끊기지 않게. */}
                  <button
                    type="button"
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={(e) => {
                      e.stopPropagation()
                      deleteBox(b.seq)
                    }}
                    title="삭제"
                    className="pointer-events-none absolute -right-2 -top-2 z-20 flex h-4 w-4 items-center justify-center rounded-full bg-destructive text-destructive-foreground opacity-0 shadow transition-opacity group-hover:pointer-events-auto group-hover:opacity-100"
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                  {selected && (
                    <span
                      onPointerDown={(e) => beginBoxDown(e, b, "resize")}
                      className="absolute -bottom-1.5 -right-1.5 h-3 w-3 cursor-nwse-resize rounded-sm border border-background bg-primary"
                    />
                  )}
                </div>
              )
            })}

            {/* 자동 인식 후보 — 호박색 점선(미확정). 단어별로 hover X 삭제·더블클릭 편집 후 '전체 추가'. */}
            {candidates.map((c, i) => {
              const editing = i === editingCand
              return (
                <div
                  key={`cand-${i}`}
                  onPointerDown={(e) => e.stopPropagation()}
                  onDoubleClick={(e) => {
                    e.stopPropagation()
                    e.preventDefault()
                    beginEditCand(i, c)
                  }}
                  className="group absolute cursor-pointer border border-dashed border-amber-500 bg-amber-400/10"
                  style={{
                    left: c.x1 * scale,
                    top: c.y1 * scale,
                    width: (c.x2 - c.x1) * scale,
                    height: (c.y2 - c.y1) * scale,
                  }}
                >
                  {editing ? (
                    <input
                      autoFocus
                      value={editingCandText}
                      onChange={(e) => setEditingCandText(e.target.value)}
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={(e) => e.stopPropagation()}
                      onDoubleClick={(e) => e.stopPropagation()}
                      onBlur={commitEditCand}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault()
                          commitEditCand()
                        } else if (e.key === "Escape") {
                          e.preventDefault()
                          cancelEditCand()
                        }
                      }}
                      placeholder="텍스트 입력"
                      className="absolute -top-6 left-0 z-20 w-40 rounded border border-amber-500 bg-background px-1 py-0.5 text-[11px] leading-tight text-foreground shadow-sm outline-none"
                    />
                  ) : (
                    <span className="absolute -top-4 left-0 rounded bg-amber-600 px-1 text-[10px] leading-tight text-white">
                      {c.data ? c.data : "?"}
                    </span>
                  )}
                  {/* 마우스 오버 시 X — 후보 바로 삭제 */}
                  <button
                    type="button"
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={(e) => {
                      e.stopPropagation()
                      deleteCand(i)
                    }}
                    title="삭제"
                    className="pointer-events-none absolute -right-2 -top-2 z-20 flex h-4 w-4 items-center justify-center rounded-full bg-destructive text-destructive-foreground opacity-0 shadow transition-opacity group-hover:pointer-events-auto group-hover:opacity-100"
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                </div>
              )
            })}

            {draft && (
              <div
                className="absolute border-2 border-dashed border-primary bg-primary/10"
                style={{
                  left: Math.min(draft.x1, draft.x2) * scale,
                  top: Math.min(draft.y1, draft.y2) * scale,
                  width: Math.abs(draft.x2 - draft.x1) * scale,
                  height: Math.abs(draft.y2 - draft.y1) * scale,
                }}
              />
            )}
          </div>
        </div>
      </div>

      {/* 드래그 separator — 흐린 회색 얇은 선(가운데 1px), 좌우 폭에 넉넉한 히트 영역 */}
      <div
        onPointerDown={startResize}
        role="separator"
        aria-orientation="vertical"
        title="드래그하여 영역 크기 조절"
        className="group relative flex w-3 shrink-0 cursor-col-resize items-stretch justify-center"
      >
        <div className="w-px bg-border transition-colors group-hover:bg-muted-foreground/40" />
      </div>

      {/* 우측 패널 */}
      <div
        className="flex shrink-0 flex-col gap-3 overflow-hidden"
        style={{ width: panelWidth }}
      >
        <div className="flex items-center gap-2">
          <Select value={detail.status} onValueChange={setStatus}>
            <SelectTrigger className="h-8 flex-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="draft">업로드</SelectItem>
              <SelectItem value="in_progress">작업중</SelectItem>
              <SelectItem value="completed">완료</SelectItem>
            </SelectContent>
          </Select>

          <Button
            size="sm"
            className="h-8 shrink-0"
            onClick={handleManualSave}
            disabled={saving}
          >
            {saving ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-1 h-4 w-4" />
            )}
            저장
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="outline" className="h-8 shrink-0">
                <Menu className="mr-1 h-4 w-4" /> 액션
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuItem onClick={() => exportImage(imageId, detail.filename)}>
                <Download className="mr-2 h-4 w-4" /> Export
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => importInputRef.current?.click()}>
                <Upload className="mr-2 h-4 w-4" /> Import
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              {/* 이미지 분할 — bbox 가 있어야 활성. 각 박스를 잘라 학습용 크롭으로 저장. */}
              <DropdownMenuItem
                onClick={handleSplit}
                disabled={boxes.length === 0 || splitting}
              >
                <Scissors className="mr-2 h-4 w-4" /> 이미지 분할
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={openJsonView}>
                <Eye className="mr-2 h-4 w-4" /> JSON 보기
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          {/* 저장 표시 — 메뉴 버튼 오른쪽. 저장 중/직후에만 보이고 이후 사라진다. */}
          <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
            {saving ? (
              <>
                <Loader2 className="h-3 w-3 animate-spin" /> 저장 중…
              </>
            ) : justSaved ? (
              <>
                <Check className="h-3 w-3 text-emerald-600" /> 자동 저장됨
              </>
            ) : null}
          </span>

          <input
            ref={importInputRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) handleImportFile(file)
              e.target.value = "" // 같은 파일 재선택 허용
            }}
          />
        </div>

        <Tabs defaultValue="boxes" className="min-h-0 flex-1">
          <TabsList className="w-full">
            <TabsTrigger value="boxes">박스</TabsTrigger>
            <TabsTrigger value="meta">메타데이터</TabsTrigger>
            <TabsTrigger value="image">이미지</TabsTrigger>
            <TabsTrigger value="guide">작성지침</TabsTrigger>
          </TabsList>
          <TabsContent
            value="boxes"
            className="min-h-0 overflow-y-auto rounded-lg border p-3"
          >
            <BoxList
              boxes={boxes}
              selectedSeq={selectedSeq}
              onSelect={setSelectedSeq}
              onChangeText={updateText}
              onDelete={deleteBox}
              onRenumber={renumber}
            />
          </TabsContent>
          <TabsContent
            value="meta"
            className="min-h-0 overflow-y-auto rounded-lg border p-3"
          >
            <MetadataForm meta={meta} onChange={onMetaChange} />
          </TabsContent>
          <TabsContent
            value="image"
            className="min-h-0 overflow-y-auto rounded-lg border p-3"
          >
            <ImageInfo detail={detail} imgUrl={imgUrl} />
          </TabsContent>
          <TabsContent
            value="guide"
            className="min-h-0 overflow-y-auto rounded-lg border p-3"
          >
            <AnnotationGuide />
          </TabsContent>
        </Tabs>
      </div>

      <Dialog open={jsonOpen} onOpenChange={setJsonOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>AI-Hub JSON 미리보기</DialogTitle>
            <DialogDescription>{detail.filename}</DialogDescription>
          </DialogHeader>
          {jsonLoading ? (
            <div className="flex h-72 items-center justify-center">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <CodeViewer
              code={jsonText}
              language="json"
              height="60vh"
              wordWrap="on"
              border
              copyLabel="JSON"
            />
          )}
        </DialogContent>
      </Dialog>

      {/* 이미지 분할 진행 오버레이 — 서버 단일 호출이라 진행 단위를 알 수 없어 부정형(펄스) 바. */}
      {splitting && (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-background/70">
          <div className="w-80 max-w-[90%] space-y-3 rounded-lg border bg-background p-4 shadow-lg">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
              이미지 분할 중
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
              <div className="h-full w-full animate-pulse rounded-full bg-primary/60" />
            </div>
            <p className="text-xs text-muted-foreground">
              bbox 영역을 잘라 학습 데이터(크롭 이미지 + JSONL)로 저장하고 있습니다…
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
