"use client"

// 문자열 상태 ↔ URL 쿼리 동기화 — 브라우저 back/forward 가 화면 상태 단위로 움직이게 한다.
//
// 화면 전환(탭·폴더 경로 등)을 클라이언트 상태로만 두면 히스토리에 안 남아, back 이
// 한참 전의 다른 페이지로 튄다. 이 훅은 상태 변경을 history.pushState(네이티브 shallow
// routing — Next App Router 가 공식 지원)로 기록해 back=이전 상태, 새로고침/딥링크=보던
// 상태가 되게 한다. useSearchParams 를 쓰지 않아 Suspense 경계가 필요 없다(SSR 첫
// 렌더는 기본값, 마운트 시 URL 값으로 보정).
import { useCallback, useEffect, useState } from "react"

/** 범용 — param 을 생략하면 URL 동기화 없는 일반 상태(재사용 컴포넌트의 opt-in 용). */
export function useUrlState(
  defaultValue: string,
  param?: string
): [string, (v: string) => void] {
  const [value, setValueState] = useState(defaultValue)

  useEffect(() => {
    if (!param) return
    const read = () => {
      const v = new URLSearchParams(window.location.search).get(param)
      setValueState(v ?? defaultValue)
    }
    read() // 마운트 시 URL 반영(딥링크·다른 페이지 갔다가 back 으로 복귀)
    window.addEventListener("popstate", read)
    return () => window.removeEventListener("popstate", read)
  }, [defaultValue, param])

  const setValue = useCallback(
    (v: string) => {
      setValueState(v)
      if (!param) return
      const q = new URLSearchParams(window.location.search)
      if ((q.get(param) ?? defaultValue) === v) return // 동일 값 재선택 — 중복 엔트리 방지
      if (v === defaultValue) q.delete(param) // 기본값은 쿼리 없이(URL 청결)
      else q.set(param, v)
      const qs = q.toString()
      window.history.pushState(null, "", qs ? `?${qs}` : window.location.pathname)
    },
    [defaultValue, param]
  )

  return [value, setValue]
}

/** 탭 전용 별칭 — <UrlTabs> 가 사용(기본 param="tab"). */
export function useTabState(
  defaultTab: string,
  param = "tab"
): [string, (v: string) => void] {
  return useUrlState(defaultTab, param)
}
