// 이미지 정보 뷰어 — 목록/그리드 행의 ℹ️ 아이콘 → Popover.
// 지식베이스 상세의 문서 메타데이터 표시와 동일한 테이블 구조(항목 / 값 / 설명)를 따른다.
"use client"

import { Info } from "lucide-react"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@workspace/ui/components/popover"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@workspace/ui/components/tooltip"
import { formatBytes, formatDateTime } from "@/lib/format"
import type { AnnotationImage } from "../../data/schema"

const STATUS_LABEL: Record<string, string> = {
  draft: "업로드",
  in_progress: "작업중",
  completed: "완료",
}

/** content_type(image/png) → 친숙한 형식 표시명(PNG). 없으면 "—". */
function formatLabel(ct: string | null): string {
  const sub = (ct || "").split("/")[1]
  return sub ? sub.toUpperCase() : "—"
}

type Row = { label: string; value: string; desc: string }

function buildRows(img: AnnotationImage): Row[] {
  const folder = img.folder ? img.folder : "루트"
  const hash = img.content_hash ? `${img.content_hash.slice(0, 12)}…` : "—"
  return [
    { label: "파일명", value: img.filename, desc: "원본 이미지 파일 이름" },
    { label: "형식", value: formatLabel(img.content_type), desc: "이미지 파일 형식" },
    { label: "해상도", value: `${img.width} × ${img.height} px`, desc: "이미지 가로×세로 픽셀" },
    { label: "파일 크기", value: formatBytes(img.size_bytes), desc: "원본 이미지 용량" },
    { label: "상태", value: STATUS_LABEL[img.status] ?? img.status, desc: "라벨링 작업 상태" },
    { label: "박스 수", value: String(img.box_count), desc: "지정된 bbox 개수" },
    { label: "폴더", value: folder, desc: "저장된 폴더(위치)" },
    { label: "등록자", value: img.created_by ?? "—", desc: "이미지를 등록한 사용자" },
    { label: "등록일", value: formatDateTime(img.created_at), desc: "이미지 등록 일시" },
    { label: "수정일", value: formatDateTime(img.updated_at), desc: "최종 수정 일시" },
    { label: "콘텐츠 해시", value: hash, desc: "중복·무결성 식별 해시" },
  ]
}

export function ImageInfo({ image }: { image: AnnotationImage }) {
  const rows = buildRows(image)
  return (
    <Popover>
      <TooltipProvider delayDuration={150}>
        <Tooltip>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>
              <button
                type="button"
                aria-label="이미지 정보"
                className="shrink-0 text-muted-foreground/60 transition-colors hover:text-foreground"
              >
                <Info className="size-3.5" />
              </button>
            </PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent>클릭시 상세 정보를 볼 수 있습니다.</TooltipContent>
        </Tooltip>
      </TooltipProvider>
      <PopoverContent align="start" className="w-[34rem] overflow-hidden p-0">
        <div className="border-b bg-muted/40 px-3 py-2 text-sm font-medium text-black">
          이미지 정보
        </div>
        <div className="max-h-80 overflow-y-auto p-3">
          <div className="overflow-hidden rounded-md border">
            <table className="w-full table-fixed border-collapse text-sm text-black">
              <colgroup>
                <col className="w-24" />
                <col className="w-[42%]" />
                <col />
              </colgroup>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.label}>
                    <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">
                      {r.label}
                    </th>
                    <td className="break-words border px-3 py-2 align-middle text-black">
                      {r.value}
                    </td>
                    <td className="border px-3 py-2 align-middle text-sm text-black">
                      {r.desc}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}
