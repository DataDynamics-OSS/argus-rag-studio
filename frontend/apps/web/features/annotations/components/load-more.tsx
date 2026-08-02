"use client"

// 증분 로딩 푸터 — 화면 하단 sentinel 이 보이면 자동으로 다음 페이지를 부르고(무한 스크롤),
// 수동 '더 보기' 버튼도 함께 제공한다. hasMore=false 면 렌더하지 않는다.

import { useCallback, useEffect, useRef } from "react"
import { Loader2 } from "lucide-react"
import { Button } from "@workspace/ui/components/button"

export function LoadMore({
  hasMore,
  loading,
  onLoadMore,
}: {
  hasMore: boolean
  loading: boolean
  onLoadMore: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  // 최신 콜백을 ref 로 들고 있어 IntersectionObserver 를 재생성하지 않는다.
  const cbRef = useRef(onLoadMore)
  cbRef.current = onLoadMore

  const handle = useCallback(() => cbRef.current(), [])

  useEffect(() => {
    if (!hasMore) return
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) cbRef.current()
      },
      { rootMargin: "300px" }
    )
    io.observe(el)
    return () => io.disconnect()
  }, [hasMore])

  if (!hasMore) return null
  return (
    <div ref={ref} className="flex justify-center py-4">
      <Button variant="outline" size="sm" disabled={loading} onClick={handle}>
        {loading ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : null}
        더 보기
      </Button>
    </div>
  )
}
