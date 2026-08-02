"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { Loader2 } from "lucide-react"
import { cn } from "@workspace/ui/lib/utils"
import { getHwpViewerMode } from "@/lib/hwp-pref"

type HwpViewerProps = {
  /** Raw HWP/HWPX bytes (same-origin fetch via getBytes — avoids CORS). */
  bytes: ArrayBuffer
  /** 이 텍스트(검색 매칭 청크)를 렌더된 결과에서 찾아 강조·스크롤. */
  highlight?: string
}

// WASM init 은 비싸므로 모듈 스코프에서 1회만 수행한다.
let initPromise: Promise<unknown> | null = null

// 매칭용 정규화 — 소문자 + 글자/숫자(CJK 포함)만 남김(공백·구두점 차이 흡수).
function normalize(s: string): string {
  return s.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "")
}

// SVG 문자열 → <img> 로 표시할 data URL (브라우저가 비트맵으로 래스터화 → 빠른 페인트·스크롤).
function svgToDataUrl(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

// SVG 문자열에서 텍스트만 파싱(렌더 없이) — 페이지 단위 매칭용.
function pageText(svg: string): string {
  try {
    const doc = new DOMParser().parseFromString(svg, "image/svg+xml")
    let s = ""
    doc.querySelectorAll("text").forEach((t) => {
      s += normalize(t.textContent ?? "")
    })
    return s
  } catch {
    return ""
  }
}

export function HwpViewer({ bytes, highlight }: HwpViewerProps) {
  const [pages, setPages] = useState<string[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  // 렌더링 방식(클라이언트 설정). 마운트 시 1회 읽는다 — 다이얼로그를 다시 열면 반영.
  const [mode] = useState(getHwpViewerMode)

  useEffect(() => {
    let alive = true
    setIsLoading(true)
    setError(null)
    setPages([])

    ;(async () => {
      const mod = await import("@rhwp/core")
      initPromise ??= mod.default({ module_or_path: "/rhwp_bg.wasm" })
      await initPromise

      const doc = new mod.HwpDocument(new Uint8Array(bytes))
      const count = doc.pageCount()
      const svgs: string[] = []
      for (let i = 0; i < count; i++) svgs.push(doc.renderPageSvg(i))
      if (alive) {
        setPages(svgs)
        setIsLoading(false)
      }
    })().catch((err) => {
      if (alive) {
        setError(err instanceof Error ? err.message : "HWP 파일을 렌더링하지 못했습니다.")
        setIsLoading(false)
      }
    })

    return () => {
      alive = false
    }
  }, [bytes])

  // ── 이미지 모드(A): 매칭 페이지 선택(SVG 텍스트만 파싱, 렌더 없이 빠름) ──────────
  const bestPage = useMemo(() => {
    if (mode !== "image") return -1
    const needle = normalize(highlight ?? "")
    if (!needle || pages.length === 0) return -1
    let best = -1
    let bestCov = 0
    const mid = Math.floor(needle.length / 2)
    pages.forEach((svg, i) => {
      const pt = pageText(svg) // 페이지의 정규화 텍스트(렌더 없이 파싱)
      // 청크(needle) 전체 또는 앞/중간 슬라이스가 페이지 텍스트에 들어있으면 그 페이지로 본다.
      let cov = 0
      if (needle.length >= 12 && pt.includes(needle)) cov += needle.length
      for (const probe of [needle.slice(0, 60), needle.slice(mid, mid + 60)]) {
        if (probe.length >= 12 && pt.includes(probe)) cov += probe.length
      }
      if (cov > bestCov) {
        bestCov = cov
        best = i
      }
    })
    return best
  }, [mode, pages, highlight])

  // 이미지 모드: 매칭 페이지로 스크롤.
  useEffect(() => {
    if (mode !== "image" || bestPage < 0) return
    const el = containerRef.current?.querySelector(`[data-page="${bestPage}"]`)
    if (el) requestAnimationFrame(() => el.scrollIntoView({ block: "center", behavior: "smooth" }))
  }, [mode, bestPage, pages])

  // ── SVG 모드(B): inline SVG + 매칭 셀 정밀 색칠(레이아웃 후 실행 + 재시도) ────────
  useEffect(() => {
    if (mode !== "svg") return
    const container = containerRef.current
    if (!container || pages.length === 0) return
    const needle = normalize(highlight ?? "")
    if (!needle) return

    const NS = "http://www.w3.org/2000/svg"
    let cancelled = false
    let tries = 0

    const draw = (): number => {
      container.querySelectorAll(".rhwp-hl").forEach((n) => n.remove())
      let best: SVGTextElement[] | null = null
      let bestCov = 0
      container.querySelectorAll("svg").forEach((svg) => {
        const els: SVGTextElement[] = []
        let cov = 0
        svg.querySelectorAll("text").forEach((t) => {
          const ni = normalize(t.textContent ?? "")
          if (ni.length >= 3 && needle.includes(ni)) {
            els.push(t as SVGTextElement)
            cov += ni.length
          }
        })
        if (cov >= 16 && cov > bestCov) {
          bestCov = cov
          best = els
        }
      })
      if (!best) return -1

      let firstRect: SVGRectElement | null = null
      for (const t of best as SVGTextElement[]) {
        const svg = t.ownerSVGElement
        if (!svg) continue
        let bb: DOMRect
        let ctm: DOMMatrix | null
        try {
          bb = t.getBBox()
          ctm = t.getCTM()
        } catch {
          continue
        }
        if (!ctm || (bb.width === 0 && bb.height === 0)) continue
        const corners = [
          [bb.x, bb.y],
          [bb.x + bb.width, bb.y],
          [bb.x, bb.y + bb.height],
          [bb.x + bb.width, bb.y + bb.height],
        ].map(([x, y]) => {
          const p = svg.createSVGPoint()
          p.x = x!
          p.y = y!
          return p.matrixTransform(ctm!)
        })
        const xs = corners.map((p) => p.x)
        const ys = corners.map((p) => p.y)
        const rx = Math.min(...xs)
        const ry = Math.min(...ys)
        const rect = document.createElementNS(NS, "rect")
        rect.setAttribute("x", String(rx))
        rect.setAttribute("y", String(ry))
        rect.setAttribute("width", String(Math.max(Math.max(...xs) - rx, 1)))
        rect.setAttribute("height", String(Math.max(Math.max(...ys) - ry, 1)))
        rect.setAttribute("fill", "rgba(251,191,36,.4)")
        rect.setAttribute("stroke", "rgba(180,83,9,.85)")
        rect.setAttribute("stroke-width", "1")
        rect.setAttribute("rx", "2")
        rect.setAttribute("class", "rhwp-hl")
        rect.style.pointerEvents = "none"
        svg.appendChild(rect)
        if (!firstRect) firstRect = rect
      }
      if (!firstRect) return 0

      const rect = firstRect as SVGRectElement
      requestAnimationFrame(() => {
        if (cancelled || !container) return
        const cr = container.getBoundingClientRect()
        const rr = rect.getBoundingClientRect()
        container.scrollTo({
          top: container.scrollTop + (rr.top - cr.top - container.clientHeight / 2 + rr.height / 2),
          behavior: "smooth",
        })
      })
      return 1
    }

    const tick = () => {
      if (cancelled) return
      const r = draw()
      if (r === 0 && tries < 6) {
        tries += 1
        setTimeout(() => requestAnimationFrame(tick), 120)
      } else if (r === -1 && tries < 2) {
        tries += 1
        setTimeout(() => requestAnimationFrame(tick), 200)
      }
    }
    requestAnimationFrame(tick)
    return () => {
      cancelled = true
      container.querySelectorAll(".rhwp-hl").forEach((n) => n.remove())
    }
  }, [mode, pages, highlight])

  if (isLoading) {
    return (
      <div className="flex h-[600px] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-[200px] flex-col items-center justify-center gap-1 px-6 text-center">
        <p className="text-sm text-muted-foreground">{error}</p>
        <p className="text-xs text-muted-foreground">
          복잡한 문서는 일부 렌더링이 제한될 수 있습니다. 원본을 다운로드해 확인하세요.
        </p>
      </div>
    )
  }

  return (
    <div ref={containerRef} className="max-h-[70vh] space-y-4 overflow-auto rounded border bg-muted/30 p-4">
      {pages.map((svg, i) =>
        mode === "image" ? (
          <div
            key={i}
            data-page={i}
            className={cn(
              "mx-auto w-fit max-w-full rounded bg-white shadow-sm",
              i === bestPage && "ring-2 ring-amber-400 ring-offset-2",
            )}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={svgToDataUrl(svg)} alt={`HWP page ${i + 1}`} className="block max-w-full" />
          </div>
        ) : (
          <div
            key={i}
            data-page={i}
            className="mx-auto w-fit max-w-full bg-white shadow-sm [&_svg]:h-auto [&_svg]:max-w-full"
            // rhwp 가 생성한 페이지 SVG 문자열을 삽입
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        ),
      )}
    </div>
  )
}
