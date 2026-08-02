// 이미지 어노테이션 — 업로드된 이미지 목록 + 업로드 진입점.
"use client"

import { DashboardHeader } from "@/components/dashboard-header"
import { ImageList } from "@/features/annotations/components/image-list"

export default function AnnotationsPage() {
  return (
    <>
      <DashboardHeader title="이미지 어노테이션" />
      <ImageList />
    </>
  )
}
