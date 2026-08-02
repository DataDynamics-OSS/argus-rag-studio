// 학습 작업 상태 배지 — 목록·상세 공용.
import { Badge } from "@workspace/ui/components/badge"

const STATUS: Record<string, { label: string; className: string }> = {
  queued: { label: "대기", className: "border-muted-foreground/30 text-muted-foreground" },
  running: { label: "진행 중", className: "border-sky-500/40 bg-sky-500/10 text-sky-600 dark:text-sky-400" },
  succeeded: { label: "성공", className: "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" },
  failed: { label: "실패", className: "border-red-500/40 bg-red-500/10 text-red-600 dark:text-red-400" },
  canceled: { label: "취소", className: "border-muted-foreground/30 text-muted-foreground" },
}

export function JobStatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, className: "" }
  return (
    <Badge variant="outline" className={`font-normal ${s.className}`}>
      {s.label}
    </Badge>
  )
}
