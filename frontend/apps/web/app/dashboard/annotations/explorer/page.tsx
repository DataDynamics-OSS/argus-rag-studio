// 이미지 탐색기 — 폴더 트리 + 폴더별 이미지(Windows 탐색기 스타일).
"use client"

import { DashboardHeader } from "@/components/dashboard-header"
import { AnnotationExplorer } from "@/features/annotations/components/explorer/annotation-explorer"

export default function AnnotationsExplorerPage() {
  return (
    <>
      <DashboardHeader title="이미지 라벨링" />
      <AnnotationExplorer />
    </>
  )
}
