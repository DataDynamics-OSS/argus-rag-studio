// 폴링 + 클라이언트 롤링 시계열 훅. 페이지가 숨겨지면 폴링을 멈추고, 다시 보이면 즉시 갱신한다.
"use client"

import { useEffect, useRef, useState } from "react"

export type Sample<T> = { t: number; v: T }

export function useRollingSeries<T>(
  fetcher: () => Promise<T>,
  opts: { intervalMs?: number; cap?: number; enabled?: boolean } = {}
): { latest: T | null; series: Sample<T>[]; error: string | null; loading: boolean } {
  const { intervalMs = 3000, cap = 120, enabled = true } = opts
  const [latest, setLatest] = useState<T | null>(null)
  const [series, setSeries] = useState<Sample<T>[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const fetcherRef = useRef(fetcher)
  useEffect(() => {
    fetcherRef.current = fetcher
  })

  useEffect(() => {
    if (!enabled) return
    let active = true
    let timer: ReturnType<typeof setTimeout>

    // 실제 fetch(숨김 여부와 무관) → 마운트/가시성 복귀 시 즉시 데이터 확보.
    const fetchNow = async () => {
      try {
        const v = await fetcherRef.current()
        if (!active) return
        setLatest(v)
        setSeries((s) => [...s, { t: Date.now(), v }].slice(-cap))
        setError(null)
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : "조회 실패")
      } finally {
        if (active) setLoading(false)
      }
    }

    // 주기 폴링 — 숨김 상태면 fetch 스킵(재스케줄만)으로 자원 절약.
    const schedule = () => {
      timer = setTimeout(async () => {
        if (typeof document === "undefined" || !document.hidden) {
          await fetchNow()
        }
        if (active) schedule()
      }, intervalMs)
    }

    const onVisible = () => {
      if (active && typeof document !== "undefined" && !document.hidden) void fetchNow()
    }

    void fetchNow() // 마운트 즉시 1회
    schedule()
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisible)
    }
    return () => {
      active = false
      clearTimeout(timer)
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisible)
      }
    }
  }, [enabled, intervalMs, cap])

  return { latest, series, error, loading }
}
