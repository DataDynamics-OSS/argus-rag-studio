"use client"

import { Cpu, Gpu } from "lucide-react"

import { Badge } from "@workspace/ui/components/badge"

/** 디바이스 배지(그리드·카드 공용) — 미상은 CPU 로 간주, CUDA=에메랄드 / CPU=징크 + 아이콘. */
export function DeviceBadge({ device, className }: { device?: string | null; className?: string }) {
  const d = (device ?? "cpu").toLowerCase()
  const cuda = d === "cuda"
  const cls = cuda
    ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
    : "border-zinc-500/40 bg-zinc-500/10 text-zinc-600 dark:text-zinc-400"
  return (
    <Badge variant="outline" className={`text-xs uppercase ${cls} ${className ?? ""}`}>
      {cuda ? <Gpu className="size-3" /> : <Cpu className="size-3" />}
      {d}
    </Badge>
  )
}
