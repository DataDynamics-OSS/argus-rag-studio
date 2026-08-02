// 이미지 어노테이션 에디터 — 캔버스에서 bbox/텍스트 라벨링 후 AI-Hub 포맷으로 내보내기.
"use client"

import { use } from "react"
import Link from "next/link"
import { ChevronLeft } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { DashboardHeader } from "@/components/dashboard-header"
import { AnnotationEditor } from "@/features/annotations/components/annotation-editor"

export default function AnnotationEditorPage({
  params,
}: {
  params: Promise<{ imageId: string }>
}) {
  const { imageId } = use(params)
  return (
    <div className="flex h-screen flex-col">
      <DashboardHeader title="어노테이션 에디터" />
      <div className="flex items-center gap-2 border-b px-4 py-2">
        <Button asChild variant="ghost" size="sm">
          <Link href="/dashboard/annotations">
            <ChevronLeft className="mr-1 h-4 w-4" /> 목록으로
          </Link>
        </Button>
      </div>
      <AnnotationEditor imageId={imageId} />
    </div>
  )
}
