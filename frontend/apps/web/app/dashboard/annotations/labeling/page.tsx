// 라벨링 작업화면 — 좌측 폴더 이미지 카드 목록 + 우측 어노테이션 편집기.
"use client"

import { Suspense, useState } from "react"
import { useSearchParams } from "next/navigation"
import { Loader2 } from "lucide-react"
import { DashboardHeader } from "@/components/dashboard-header"
import { LabelingWorkspace } from "@/features/annotations/components/labeling-workspace"

function LabelingInner({
  onFilenameChange,
}: {
  onFilenameChange: (filename: string | null) => void
}) {
  const params = useSearchParams()
  const folder = params.get("folder") ?? ""
  const image = params.get("image") ?? undefined
  // folder 가 바뀌면 작업화면을 새로 마운트(선택/목록 초기화)
  return (
    <LabelingWorkspace
      key={folder}
      folder={folder}
      initialImageId={image}
      onFilenameChange={onFilenameChange}
    />
  )
}

export default function LabelingPage() {
  // 현재 편집 중인 이미지 파일명 — 헤더 타이틀 옆에 표시.
  const [filename, setFilename] = useState<string | null>(null)
  return (
    <div className="flex h-screen flex-col">
      <DashboardHeader title="이미지 라벨링" subtitle={filename ?? undefined} />
      <Suspense
        fallback={
          <div className="flex flex-1 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        }
      >
        <LabelingInner onFilenameChange={setFilename} />
      </Suspense>
    </div>
  )
}
