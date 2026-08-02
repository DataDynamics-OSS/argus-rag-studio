"use client"

// 이미지 목록 증분 로딩 훅 — 오프셋 페이지네이션(page/page_size)을 append 방식으로 노출한다.
// reload({folder,...}) 로 1페이지부터 교체 로드, loadMore() 로 다음 페이지를 이어붙인다.
// 폴더/검색 전환 시 reqId 로 이전 요청 결과를 무시(레이스 방지)한다.

import { useCallback, useRef, useState } from "react"
import { toast } from "sonner"
import type { AnnotationImage } from "../data/schema"
import { listImages } from "../api"

export type ImageQuery = { folder?: string; status?: string; search?: string }

export function useIncrementalImages(pageSize = 60) {
  const [items, setItems] = useState<AnnotationImage[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true) // 초기/교체 로드
  const [loadingMore, setLoadingMore] = useState(false)

  const pageRef = useRef(1)
  const totalRef = useRef(0)
  const loadedRef = useRef(0)
  const busyRef = useRef(false)
  const reqIdRef = useRef(0)
  const paramsRef = useRef<ImageQuery>({})

  const reload = useCallback(
    async (params: ImageQuery = {}) => {
      paramsRef.current = params
      const rid = ++reqIdRef.current
      pageRef.current = 1
      busyRef.current = true
      setLoading(true)
      try {
        const res = await listImages({ ...params, page: 1, pageSize })
        if (rid !== reqIdRef.current) return // 폴더가 바뀌어 stale → 무시
        setItems(res.items)
        setTotal(res.total)
        loadedRef.current = res.items.length
        totalRef.current = res.total
      } catch (e) {
        if (rid === reqIdRef.current) {
          toast.error(e instanceof Error ? e.message : "이미지 조회 실패")
        }
      } finally {
        if (rid === reqIdRef.current) {
          setLoading(false)
          busyRef.current = false
        }
      }
    },
    [pageSize]
  )

  const loadMore = useCallback(async () => {
    if (busyRef.current) return
    if (loadedRef.current >= totalRef.current) return
    const rid = reqIdRef.current
    const next = pageRef.current + 1
    busyRef.current = true
    setLoadingMore(true)
    try {
      const res = await listImages({ ...paramsRef.current, page: next, pageSize })
      if (rid !== reqIdRef.current) return // 다른 폴더 로드가 시작됨 → 무시
      pageRef.current = next
      totalRef.current = res.total
      setTotal(res.total)
      setItems((prev) => {
        const seen = new Set(prev.map((i) => i.image_id))
        const merged = [...prev, ...res.items.filter((i) => !seen.has(i.image_id))]
        loadedRef.current = merged.length
        return merged
      })
    } catch (e) {
      if (rid === reqIdRef.current) {
        toast.error(e instanceof Error ? e.message : "이미지 조회 실패")
      }
    } finally {
      if (rid === reqIdRef.current) {
        setLoadingMore(false)
        busyRef.current = false
      }
    }
  }, [pageSize])

  const hasMore = items.length < total

  return { items, total, loading, loadingMore, hasMore, reload, loadMore }
}
