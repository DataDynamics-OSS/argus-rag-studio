"use client"

// Mermaid 다이어그램 렌더러 — mermaid 는 브라우저에서만 동작하므로 동적 import 로 클라이언트 렌더.
// chart 는 정적(코드에 하드코딩된) 신뢰 가능한 문자열이라 생성된 SVG 를 그대로 삽입한다.

import { useEffect, useId, useState } from "react"

export function Mermaid({ chart, className }: { chart: string; className?: string }) {
  const [svg, setSvg] = useState<string>("")
  const [failed, setFailed] = useState(false)
  const rawId = useId()
  const id = "mmd" + rawId.replace(/[^a-zA-Z0-9]/g, "")

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const mermaid = (await import("mermaid")).default
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "loose",
          theme: "neutral",
          flowchart: { htmlLabels: true, curve: "basis" },
        })
        const { svg } = await mermaid.render(id, chart)
        if (!cancelled) {
          setSvg(svg)
          setFailed(false)
        }
      } catch {
        if (!cancelled) setFailed(true)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [chart, id])

  if (failed) {
    return (
      <pre className="overflow-x-auto rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
        {chart}
      </pre>
    )
  }
  if (!svg) {
    return (
      <div className="rounded-lg border bg-muted/20 p-4 text-xs text-muted-foreground">
        다이어그램 렌더링 중…
      </div>
    )
  }
  return (
    <div
      className={`overflow-x-auto rounded-lg border bg-background p-3 [&_svg]:mx-auto [&_svg]:h-auto [&_svg]:max-w-full ${className ?? ""}`}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}
