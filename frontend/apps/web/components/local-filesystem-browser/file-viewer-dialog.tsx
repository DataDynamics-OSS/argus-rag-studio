"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Loader2 } from "lucide-react"

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"

import type { FilesystemEntry } from "./types"
import { getExtension } from "./utils"
import { CsvViewer } from "./csv-viewer"
import { PdfViewer } from "./pdf-viewer"
import { VideoViewer } from "./video-viewer"
import { AudioViewer } from "./audio-viewer"
import { XlsxViewer } from "./xlsx-viewer"
import { DocxViewer } from "./docx-viewer"
import { ParquetViewer } from "./parquet-viewer"
import { PptxViewer } from "./pptx-viewer"
import { HwpViewer } from "./hwp-viewer"
import { CodeViewer } from "@/components/code-viewer"

/** Maximum file size in bytes that the text viewer can display (20 KB). */
const MAX_VIEW_SIZE = 20 * 1024

/** Map exact filenames (without extension) to Monaco Editor language identifiers. */
const filenameToLanguage: Record<string, string> = {
  MLmodel: "yaml",
  Dockerfile: "dockerfile",
  Makefile: "plaintext",
}

/** Map file extensions to Monaco Editor language identifiers. */
const extensionToLanguage: Record<string, string> = {
  py: "python",
  java: "java",
  ipynb: "json",
  c: "c",
  cpp: "cpp",
  h: "c",
  hpp: "cpp",
  html: "html",
  htm: "html",
  css: "css",
  js: "javascript",
  ts: "typescript",
  go: "go",
  rs: "rust",
  sh: "shell",
  bash: "shell",
  zsh: "shell",
  json: "json",
  jsonl: "json",
  yaml: "yaml",
  yml: "yaml",
  xml: "xml",
  ini: "ini",
  conf: "ini",
  config: "ini",
  md: "markdown",
  log: "plaintext",
  env: "plaintext",
  txt: "plaintext",
}

/** Image extensions that should be rendered as an image preview. */
const imageExtensions = new Set([
  "jpg", "jpeg", "png", "gif", "svg", "webp", "bmp", "ico", "tiff",
])

/** CSV/TSV extensions that use the dedicated table viewer. */
const csvExtensions: Record<string, string> = {
  csv: ",",
  tsv: "\t",
}

const pdfExtensions = new Set(["pdf"])
const videoExtensions = new Set(["mp4", "webm", "ogg", "mov", "m4v", "avi", "mkv"])
const audioExtensions = new Set(["mp3", "wav", "m4a", "flac", "aac", "wma"])
const hwpExtensions = new Set(["hwp", "hwpx"])

/** Extensions handled by server-side preview API. */
const serverPreviewExtensions = new Set(["xls", "xlsx", "docx", "pptx", "parquet"])

// 오피스 — LibreOffice 로 PDF 변환해 고충실도 미리보기(우선). 실패/미설치 시 native 폴백.
// 구형 바이너리(doc/ppt/xls)도 포함 — native 폴백이 없으므로 변환 가능할 때만 보인다.
const officePdfExtensions = new Set(["doc", "docx", "ppt", "pptx", "xls", "xlsx"])

// fetch 기반 뷰어 — presigned URL 직접 fetch 가 CORS 로 막히므로 getBytes(동일출처) → blob URL 로 처리.
// 동일출처 인증 fetch(getBytes) → blob URL 로 렌더하는 카테고리.
// 이미지/비디오/오디오 포함 — presigned URL 을 미디어 element 에 직접 쓰면 MinIO CORS/접근
// 제약으로 안 보인다(동일출처 blob URL 로 우회).
const BLOB_FETCH_CATEGORIES = new Set(["pdf", "csv", "image", "video", "audio"])

const IMAGE_MIME: Record<string, string> = {
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  gif: "image/gif",
  svg: "image/svg+xml",
  webp: "image/webp",
  bmp: "image/bmp",
  ico: "image/x-icon",
  tiff: "image/tiff",
}

const VIDEO_MIME: Record<string, string> = {
  mp4: "video/mp4",
  webm: "video/webm",
  ogg: "video/ogg",
  mov: "video/quicktime",
  m4v: "video/x-m4v",
  avi: "video/x-msvideo",
  mkv: "video/x-matroska",
}

const AUDIO_MIME: Record<string, string> = {
  mp3: "audio/mpeg",
  wav: "audio/wav",
  m4a: "audio/mp4",
  flac: "audio/flac",
  aac: "audio/aac",
  ogg: "audio/ogg",
  wma: "audio/x-ms-wma",
}

function blobMime(category: string, ext: string): string {
  if (category === "pdf") return "application/pdf"
  if (category === "csv") return ext === "tsv" ? "text/tab-separated-values" : "text/csv"
  if (category === "image") return IMAGE_MIME[ext] ?? "image/png"
  if (category === "video") return VIDEO_MIME[ext] ?? "video/mp4"
  if (category === "audio") return AUDIO_MIME[ext] ?? "audio/mpeg"
  return "application/octet-stream"
}

type FileCategory =
  | "text"
  | "image"
  | "csv"
  | "pdf"
  | "video"
  | "audio"
  | "xlsx"
  | "docx"
  | "pptx"
  | "parquet"
  | "hwp"
  | null

function getFileCategoryByName(name: string, ext: string): FileCategory {
  if (name in filenameToLanguage) return "text"
  return getFileCategoryByExt(ext)
}

function getFileCategoryByExt(ext: string): FileCategory {
  if (ext in extensionToLanguage) return "text"
  if (imageExtensions.has(ext)) return "image"
  if (ext in csvExtensions) return "csv"
  if (pdfExtensions.has(ext)) return "pdf"
  if (videoExtensions.has(ext)) return "video"
  if (audioExtensions.has(ext)) return "audio"
  if (ext === "xls" || ext === "xlsx") return "xlsx"
  if (ext === "docx") return "docx"
  if (ext === "pptx") return "pptx"
  if (ext === "parquet") return "parquet"
  if (hwpExtensions.has(ext)) return "hwp"
  return null
}

const viewableExtensions = new Set([
  ...Object.keys(extensionToLanguage),
  ...imageExtensions,
  ...Object.keys(csvExtensions),
  ...pdfExtensions,
  ...videoExtensions,
  ...audioExtensions,
  ...serverPreviewExtensions,
  ...hwpExtensions,
  ...officePdfExtensions,
])

/** Check whether a file can be viewed. */
export function isViewableFile(name: string): boolean {
  return name in filenameToLanguage || viewableExtensions.has(getExtension(name))
}

/** Check whether a file is CSV or TSV. */
export function isCsvTsvFile(name: string): boolean {
  return getExtension(name) in csvExtensions
}

const SIZE_UNLIMITED_CATEGORIES = new Set<FileCategory>([
  "image", "csv", "pdf", "video", "audio", "xlsx", "docx", "pptx", "parquet", "hwp",
])

const WIDE_DIALOG_CATEGORIES = new Set<FileCategory>([
  "csv", "xlsx", "parquet", "video", "pdf", "pptx", "hwp",
])

type FileViewerDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  entry: FilesystemEntry | null
  /** Returns a download URL for the given path. */
  getDownloadUrl: (path: string) => Promise<string>
  /** Same-origin authenticated byte fetch (used for text preview to avoid CORS). */
  getBytes?: (path: string) => Promise<ArrayBuffer>
  /** High-fidelity office→PDF (LibreOffice). null = unavailable → native fallback. */
  getOfficePdf?: (path: string) => Promise<ArrayBuffer | null>
  /** Server-side file preview (parquet, xlsx, xls, docx, pptx). */
  previewFile?: (
    path: string,
    options?: { sheet?: string; maxRows?: number },
  ) => Promise<unknown>
}

type FileViewerContentProps = {
  entry: FilesystemEntry | null
  /** 로드 활성화 — 다이얼로그가 열려 있을 때 true(닫히면 리셋). */
  active: boolean
  getDownloadUrl: (path: string) => Promise<string>
  getBytes?: (path: string) => Promise<ArrayBuffer>
  getOfficePdf?: (path: string) => Promise<ArrayBuffer | null>
  previewFile?: (
    path: string,
    options?: { sheet?: string; maxRows?: number },
  ) => Promise<unknown>
  /** officePDF/카테고리 기준 넓은 레이아웃 필요 여부를 부모(다이얼로그 폭)로 통지. */
  onWideChange?: (wide: boolean) => void
  /** PDF/오피스(→PDF) 원본에서 이 텍스트 위치를 찾아 색칠·스크롤(검색 결과 진입 시). */
  highlight?: string
}

function formatSizeLimit(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(0)} MB`
}

export function FileViewerContent({
  entry,
  active,
  getDownloadUrl,
  getBytes,
  getOfficePdf,
  previewFile,
  onWideChange,
  highlight,
}: FileViewerContentProps) {
  const [content, setContent] = useState<string | null>(null)
  const [mediaUrl, setMediaUrl] = useState<string | null>(null)
  const [previewData, setPreviewData] = useState<unknown>(null)
  const [bytesData, setBytesData] = useState<ArrayBuffer | null>(null)
  const [officePdfUrl, setOfficePdfUrl] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // getBytes 로 만든 blob URL — 교체/닫힘 시 revoke
  const blobUrlRef = useRef<string | null>(null)

  const revokeBlob = useCallback(() => {
    if (blobUrlRef.current) {
      URL.revokeObjectURL(blobUrlRef.current)
      blobUrlRef.current = null
    }
  }, [])

  const reset = useCallback(() => {
    revokeBlob()
    setContent(null)
    setMediaUrl(null)
    setPreviewData(null)
    setBytesData(null)
    setOfficePdfUrl(null)
    setIsLoading(false)
    setError(null)
  }, [revokeBlob])

  useEffect(() => {
    if (!active || !entry || entry.kind === "folder") {
      reset()
      return
    }
    const target = entry
    const ext = getExtension(target.name)
    let cancelled = false

    const fail = (err: unknown) => {
      if (cancelled) return
      setError(err instanceof Error ? err.message : "Failed to load file")
      setIsLoading(false)
    }

    const run = async () => {
      setError(null)

      // 1) 오피스: LibreOffice 변환 PDF 우선(고충실도). null = 미설치/실패 → native 폴백.
      if (officePdfExtensions.has(ext) && getOfficePdf) {
        setIsLoading(true)
        try {
          const buf = await getOfficePdf(target.key)
          if (cancelled) return
          if (buf) {
            revokeBlob()
            const objUrl = URL.createObjectURL(new Blob([buf], { type: "application/pdf" }))
            blobUrlRef.current = objUrl
            setOfficePdfUrl(objUrl)
            setIsLoading(false)
            return
          }
        } catch {
          if (cancelled) return
          // 변환 실패 → native 폴백으로 계속
        }
      }

      const category = getFileCategoryByName(target.name, ext)
      if (!category) {
        setIsLoading(false)
        setError("Unsupported file format.")
        return
      }

      const sizeLimit = SIZE_UNLIMITED_CATEGORIES.has(category) ? null : MAX_VIEW_SIZE
      if (sizeLimit !== null && target.size > sizeLimit) {
        setIsLoading(false)
        setError(`Only files of ${formatSizeLimit(sizeLimit)} or smaller can be displayed.`)
        return
      }

      setIsLoading(true)
      try {
        // 서버사이드 native 미리보기(parquet/xlsx/docx/pptx) — 오피스 변환 폴백 포함
        if (serverPreviewExtensions.has(ext) && previewFile) {
          const data = await previewFile(target.key)
          if (cancelled) return
          setPreviewData(data)
          setIsLoading(false)
          return
        }
        // 텍스트: 동일출처 인증 fetch(getBytes) — presigned 직접 fetch 는 CORS 로 막힘
        if (category === "text" && getBytes) {
          const buf = await getBytes(target.key)
          if (cancelled) return
          setContent(new TextDecoder("utf-8", { fatal: false }).decode(buf))
          setIsLoading(false)
          return
        }
        // HWP/HWPX: raw 바이트를 클라이언트 WASM(rhwp)에 직접
        if (category === "hwp" && getBytes) {
          const buf = await getBytes(target.key)
          if (cancelled) return
          setBytesData(buf)
          setIsLoading(false)
          return
        }
        // fetch 기반 뷰어(pdf/csv): 동일출처 바이트 → blob URL
        if (getBytes && BLOB_FETCH_CATEGORIES.has(category)) {
          const buf = await getBytes(target.key)
          if (cancelled) return
          revokeBlob()
          const objUrl = URL.createObjectURL(new Blob([buf], { type: blobMime(category, ext) }))
          blobUrlRef.current = objUrl
          setMediaUrl(objUrl)
          setIsLoading(false)
          return
        }
        // 그 외(이미지/영상/오디오): URL 을 element src 로
        const url = await getDownloadUrl(target.key)
        if (cancelled) return
        if (category === "text") {
          const res = await fetch(url)
          if (!res.ok) throw new Error(`Failed to fetch file (${res.status})`)
          const text = await res.text()
          if (cancelled) return
          setContent(text)
        } else {
          setMediaUrl(url)
        }
        setIsLoading(false)
      } catch (err) {
        fail(err)
      }
    }

    run()
    return () => {
      cancelled = true
    }
  }, [active, entry, getDownloadUrl, getBytes, getOfficePdf, previewFile, reset, revokeBlob])

  const ext = entry ? getExtension(entry.name) : ""
  const category = entry ? getFileCategoryByName(entry.name, ext) : null
  const language = entry
    ? filenameToLanguage[entry.name] ?? extensionToLanguage[ext] ?? "plaintext"
    : "plaintext"
  const isWide = officePdfUrl != null || WIDE_DIALOG_CATEGORIES.has(category)

  useEffect(() => {
    onWideChange?.(isWide)
  }, [isWide, onWideChange])

  if (!entry) return null

  return (
        <div className="flex-1 min-h-0 mt-2">
          {isLoading && (
            <div className="flex items-center justify-center h-[500px]">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          )}

          {error && (
            <div className="flex items-center justify-center h-[200px]">
              <p className="text-sm text-muted-foreground">{error}</p>
            </div>
          )}

          {!isLoading && !error && officePdfUrl && (
            <PdfViewer url={officePdfUrl} highlight={highlight} />
          )}

          {!isLoading && !error && !officePdfUrl && category === "image" && mediaUrl && (
            <div className="flex items-center justify-center overflow-auto max-h-[70vh]">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={mediaUrl}
                alt={entry.name}
                className="max-w-full max-h-[70vh] object-contain rounded"
              />
            </div>
          )}

          {!isLoading && !error && category === "csv" && mediaUrl && (
            <CsvViewer url={mediaUrl} defaultDelimiter={csvExtensions[ext] ?? ","} />
          )}

          {!isLoading && !error && category === "pdf" && mediaUrl && (
            <PdfViewer url={mediaUrl} highlight={highlight} />
          )}

          {!isLoading && !error && category === "video" && mediaUrl && (
            <VideoViewer url={mediaUrl} extension={ext} />
          )}

          {!isLoading && !error && category === "audio" && mediaUrl && (
            <AudioViewer url={mediaUrl} extension={ext} fileName={entry.name} />
          )}

          {!isLoading && !error && category === "xlsx" && previewData != null && (
            <XlsxViewer
              data={previewData as never}
              entryKey={entry.key}
              previewFile={previewFile}
            />
          )}

          {!isLoading && !error && category === "docx" && previewData != null && (
            <DocxViewer data={previewData as never} />
          )}

          {!isLoading && !error && category === "pptx" && previewData != null && (
            <PptxViewer data={previewData as never} />
          )}

          {!isLoading && !error && category === "parquet" && previewData != null && (
            <ParquetViewer data={previewData as never} />
          )}

          {!isLoading && !error && category === "hwp" && bytesData != null && (
            <HwpViewer bytes={bytesData} highlight={highlight} />
          )}

          {!isLoading && !error && category === "text" && content !== null && (
            <CodeViewer
              code={content}
              language={language}
              height={500}
              wordWrap="on"
              copyLabel={entry.name}
            />
          )}
        </div>
  )
}

export function FileViewerDialog({
  open,
  onOpenChange,
  entry,
  getDownloadUrl,
  getBytes,
  getOfficePdf,
  previewFile,
}: FileViewerDialogProps) {
  const [isWide, setIsWide] = useState(false)
  if (!entry) return null
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        aria-describedby={undefined}
        className={`max-h-[85vh] flex flex-col ${isWide ? "sm:max-w-[1000px]" : "sm:max-w-[800px]"}`}
      >
        <DialogHeader>
          <DialogTitle className="truncate">{entry.name}</DialogTitle>
        </DialogHeader>
        <FileViewerContent
          entry={entry}
          active={open}
          getDownloadUrl={getDownloadUrl}
          getBytes={getBytes}
          getOfficePdf={getOfficePdf}
          previewFile={previewFile}
          onWideChange={setIsWide}
        />
      </DialogContent>
    </Dialog>
  )
}
