// 단순 플레인텍스트 뷰어(줄번호 거터 + 스크롤). inspect 다이얼로그의 uname/프로세스 출력용.
// rag-studio 공용 CodeViewer 는 Monaco 기반(code/language)이라 용도가 달라 별도 경량 컴포넌트를 둔다.
"use client"

import { useRef } from "react"

type PlainCodeViewerProps = {
  content: string
  maxHeight?: string
}

export function PlainCodeViewer({ content, maxHeight = "300px" }: PlainCodeViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const lines = content ? content.split("\n") : ["(empty)"]
  const gutterWidth = String(lines.length).length

  return (
    <div
      ref={containerRef}
      className="overflow-auto rounded-md border bg-muted text-xs font-mono leading-relaxed"
      style={{ maxHeight }}
    >
      <table className="w-full border-collapse">
        <tbody>
          {lines.map((line, i) => (
            <tr key={i} className="hover:bg-muted-foreground/5">
              <td
                className="sticky left-0 select-none bg-muted px-2 py-0 text-right text-muted-foreground/50 border-r border-border/50"
                style={{ minWidth: `${gutterWidth + 2}ch` }}
              >
                {i + 1}
              </td>
              <td className="px-3 py-0 whitespace-pre">{line || " "}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
