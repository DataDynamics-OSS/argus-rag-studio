"use client"

import type { ReactNode } from "react"
import { Separator } from "@workspace/ui/components/separator"
import { SidebarTrigger } from "@workspace/ui/components/sidebar"

interface DashboardHeaderProps {
  title: string
  /** 타이틀 우측에 흐리게 덧붙이는 보조 텍스트(예: 현재 파일명). */
  subtitle?: ReactNode
}

export function DashboardHeader({ title, subtitle }: DashboardHeaderProps) {
  return (
    <header className="sticky top-0 z-20 flex h-16 shrink-0 items-center gap-2 border-b bg-background px-4">
      {/* 사이드바 접기/펼치기 토글 */}
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="mr-2 h-4" />
      <h1 className="shrink-0 text-xl font-semibold leading-none">{title}</h1>
      {subtitle != null && subtitle !== "" && (
        <>
          <Separator orientation="vertical" className="mx-1 h-4" />
          <span
            className="min-w-0 truncate text-sm text-muted-foreground"
            title={typeof subtitle === "string" ? subtitle : undefined}
          >
            {subtitle}
          </span>
        </>
      )}
    </header>
  )
}
