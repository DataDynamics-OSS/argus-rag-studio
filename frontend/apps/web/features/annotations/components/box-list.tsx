"use client"

import { ListOrdered, Trash2 } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@workspace/ui/components/tooltip"
import type { Box } from "../data/schema"

interface BoxListProps {
  boxes: Box[]
  selectedSeq: number | null
  onSelect: (seq: number) => void
  onChangeText: (seq: number, data: string) => void
  onDelete: (seq: number) => void
  onRenumber: () => void
}

/** 우측 패널의 박스 목록 — seq · 텍스트(편집) · 삭제. 행 클릭 시 캔버스에서 선택. */
export function BoxList({
  boxes,
  selectedSeq,
  onSelect,
  onChangeText,
  onDelete,
  onRenumber,
}: BoxListProps) {
  const ordered = [...boxes].sort((a, b) => a.seq - b.seq)

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-1 pb-2">
        <span className="text-sm font-medium">박스 {boxes.length}개</span>
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                onClick={onRenumber}
                disabled={boxes.length === 0}
              >
                <ListOrdered className="mr-1 h-4 w-4" /> 번호 재정렬
              </Button>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs leading-relaxed">
              현재 번호 순서를 유지한 채, 삭제 등으로 생긴 빈 번호를 없애고 1부터
              연속된 번호(1, 2, 3 …)로 다시 매깁니다. 내보내기 시 bbox id 가 깔끔하게
              연속됩니다.
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
      <div className="flex-1 space-y-1 overflow-y-auto pr-1">
        {ordered.length === 0 && (
          <p className="px-1 py-8 text-center text-xs text-muted-foreground">
            이미지 위에서 드래그해 박스를 그리세요.
          </p>
        )}
        {ordered.map((b) => (
          <div
            key={b.seq}
            onClick={() => onSelect(b.seq)}
            className={`flex items-center gap-2 rounded-md border p-1.5 ${
              selectedSeq === b.seq ? "border-primary bg-primary/5" : "border-transparent hover:bg-muted/50"
            }`}
          >
            <span className="w-7 shrink-0 text-center text-xs font-mono text-muted-foreground">
              {b.seq}
            </span>
            <Input
              value={b.data}
              placeholder="텍스트"
              onChange={(e) => onChangeText(b.seq, e.target.value)}
              onFocus={() => onSelect(b.seq)}
              className="h-8 flex-1"
            />
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
              onClick={(e) => {
                e.stopPropagation()
                onDelete(b.seq)
              }}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}
      </div>
    </div>
  )
}
