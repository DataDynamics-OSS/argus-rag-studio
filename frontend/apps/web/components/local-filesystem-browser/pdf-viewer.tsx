"use client"

import { useEffect, useRef, useState } from "react"
import { Loader2 } from "lucide-react"

type PdfViewerProps = {
  /** Presigned download URL (또는 동일출처 blob URL) for the PDF file. */
  url: string
  /** 이 텍스트(검색 매칭 청크)를 PDF 원본에서 찾아 색칠·스크롤(검색 결과 진입용, 선택). */
  highlight?: string
}

/**
 * pdf.js 로 페이지를 앱 안에서 직접 렌더한다 — HWP 뷰어(rhwp WASM)와 동형의 인앱 페이지
 * 렌더로, 브라우저 내장 PDF UI(iframe) 대신 일관된 미리보기를 제공한다. PDF 원본과
 * 오피스(doc/docx/ppt/xls)의 LibreOffice 변환 PDF 가 모두 이 경로를 탄다.
 * pdf.js 실패(워커 로드 불가 등) 시에만 native iframe 으로 폴백한다.
 */
export function PdfViewer({ url, highlight }: PdfViewerProps) {
  return <PdfPagesViewer url={url} highlight={highlight} />
}

// ── 폴백: native iframe(브라우저 내장 뷰어) — pdf.js 경로 실패 시에만 ─────────
function PdfIframe({ url }: { url: string }) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let revoke: string | null = null
    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to fetch PDF (${res.status})`)
        return res.blob()
      })
      .then((blob) => {
        const objUrl = URL.createObjectURL(blob)
        revoke = objUrl
        setBlobUrl(objUrl)
        setIsLoading(false)
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load PDF")
        setIsLoading(false)
      })
    return () => {
      if (revoke) URL.revokeObjectURL(revoke)
    }
  }, [url])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[600px]">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }
  if (error) {
    return (
      <div className="flex items-center justify-center h-[200px]">
        <p className="text-sm text-muted-foreground">{error}</p>
      </div>
    )
  }
  return <iframe src={blobUrl!} className="w-full h-[600px] rounded border" title="PDF Viewer" />
}

// 매칭용 정규화 — 소문자 + 글자/숫자(CJK 포함)만 남김.
// 파싱 텍스트(마크다운·표 기호 포함)와 PDF 추출 텍스트의 공백·구두점·마크다운 차이를 모두 흡수.
function normalize(s: string): string {
  return s.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "")
}

// ── pdf.js 인앱 페이지 렌더(+ 선택적 매칭 청크 색칠) ─────────────────────────
function PdfPagesViewer({ url, highlight }: { url: string; highlight?: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<"loading" | "ready" | "failed">("loading")

  useEffect(() => {
    let cancelled = false
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let doc: any = null

    async function run() {
      const container = containerRef.current
      if (!container) return
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const pdfjs: any = await import("pdfjs-dist")
        // 워커는 public 에 벤더링한 동일출처 파일(에어갭 환경 안전). 실패 시 catch → iframe 폴백.
        // 주의: pdfjs-dist 업그레이드 시 apps/web/public/pdf.worker.min.mjs 를 재복사해야 함
        //       (워커-API 버전 불일치는 pdf.js 가 오류 → 자동으로 iframe 폴백).
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs"

        // blob URL 문자열 대신 바이트로 직접 로드(pdf.js v6 의 src 인자 모호성·CORS 회피).
        const buf = await (await fetch(url)).arrayBuffer()
        if (cancelled) return
        doc = await pdfjs.getDocument({ data: new Uint8Array(buf) }).promise
        if (cancelled) return
        container.innerHTML = ""
        const needle = normalize(highlight ?? "")  // 비면 색칠 없이 렌더만
        const cw = container.clientWidth || 800
        let firstHl: HTMLElement | null = null

        for (let p = 1; p <= doc.numPages; p++) {
          const page = await doc.getPage(p)
          if (cancelled) return
          const base = page.getViewport({ scale: 1 })
          const scale = Math.min(2, Math.max(0.5, (cw - 8) / base.width))
          const viewport = page.getViewport({ scale })

          const pageDiv = document.createElement("div")
          pageDiv.style.cssText = `position:relative;margin:0 auto 8px;width:${viewport.width}px;height:${viewport.height}px;`
          const canvas = document.createElement("canvas")
          canvas.width = viewport.width
          canvas.height = viewport.height
          canvas.style.cssText = "display:block;width:100%;height:100%;"
          pageDiv.appendChild(canvas)
          container.appendChild(pageDiv)

          await page.render({ canvasContext: canvas.getContext("2d")!, viewport }).promise
          if (cancelled) return
          if (!needle) continue  // 하이라이트 없음 — 텍스트 추출 생략(렌더만)

          // 페이지 텍스트를 공백 제거로 이어붙이고, 각 정규화 문자가 어느 item 에서 왔는지 추적.
          const tc = await page.getTextContent()
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const items = (tc.items as any[]).filter((it) => typeof it.str === "string")

          // 청크 텍스트가 layout 파싱으로 재배열돼 PDF 읽기순서와 다르므로, 한 구간을 찾는 대신
          // "각 text item 이 청크에 포함되면 색칠"한다(순서 무관). 청크가 있는 페이지에서 문단 전체가 칠해진다.
          const matched: number[] = []
          let coverage = 0
          for (let i = 0; i < items.length; i++) {
            const ni = normalize(items[i].str)
            if (ni.length >= 3 && needle.includes(ni)) {
              matched.push(i)
              coverage += ni.length
            }
          }
          // 페이지에 청크 내용이 충분히 있을 때만(짧은 우연 일치로 엉뚱한 페이지가 칠해지는 것 방지).
          if (coverage < 16) continue

          for (const idx of matched) {
            const it = items[idx]
            const tx = pdfjs.Util.transform(viewport.transform, it.transform)
            const fontH = Math.hypot(tx[1], tx[3]) || 10
            const w = (it.width || 0) * scale
            const hl = document.createElement("div")
            hl.style.cssText =
              `position:absolute;left:${tx[4]}px;top:${tx[5] - fontH}px;` +
              `width:${Math.max(w, 2)}px;height:${fontH}px;` +
              `background:rgba(251,191,36,.45);box-shadow:0 0 0 1px rgba(180,83,9,.8);` +
              `border-radius:2px;pointer-events:none;`
            pageDiv.appendChild(hl)
            if (!firstHl) firstHl = hl
          }
        }

        if (cancelled) return
        setStatus("ready")
        if (firstHl) firstHl.scrollIntoView({ block: "center", behavior: "smooth" })
      } catch (e) {
        // 폴백 원인을 콘솔에 남긴다(워커 404 / pdf.js 로드 실패 등 진단용).
        console.warn("[pdf-highlight] pdf.js 렌더 실패 → iframe 폴백:", e)
        if (!cancelled) setStatus("failed")
      }
    }

    void run()
    return () => {
      cancelled = true
      try {
        doc?.destroy?.()
      } catch {
        /* noop */
      }
    }
  }, [url, highlight])

  // pdf.js 경로 실패(워커 로드 불가 등) 시 기존 iframe 으로 폴백.
  if (status === "failed") return <PdfIframe url={url} />

  return (
    <div className="relative">
      {status === "loading" && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/60">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      )}
      <div
        ref={containerRef}
        className="w-full overflow-auto rounded border bg-muted/20 p-2"
        style={{ maxHeight: "72vh" }}
      />
    </div>
  )
}
