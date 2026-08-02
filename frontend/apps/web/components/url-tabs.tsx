"use client"

// URL 동기화 Tabs — <Tabs defaultValue> 의 drop-in 대체.
// 탭 전환을 ?tab=(또는 param 지정) 쿼리로 히스토리에 기록해 브라우저 back/forward 가
// 탭 단위로 움직이고, 새로고침·딥링크에서 보던 탭이 유지된다. hooks/use-tab-state 참조.
import type { ComponentProps } from "react"

import { Tabs } from "@workspace/ui/components/tabs"
import { useTabState } from "@/hooks/use-tab-state"

type Props = Omit<ComponentProps<typeof Tabs>, "value" | "onValueChange" | "defaultValue"> & {
  defaultValue: string
  param?: string
}

export function UrlTabs({ defaultValue, param = "tab", ...props }: Props) {
  const [tab, setTab] = useTabState(defaultValue, param)
  return <Tabs {...props} value={tab} onValueChange={setTab} />
}
