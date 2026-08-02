"use client"

import {
  File,
  FileArchive,
  FileAudio,
  FileCode,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileType,
  FileVideo,
  Folder,
} from "lucide-react"

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"

import { fileTypeLabel } from "@/lib/format"

import type { FilesystemEntry } from "./types"
import { formatBytes, formatDate, getFileCategory, getExtension } from "./utils"

type PropertiesDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  entry: FilesystemEntry | null
}

const fileIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  image: FileImage,
  video: FileVideo,
  audio: FileAudio,
  archive: FileArchive,
  code: FileCode,
  document: FileText,
  text: FileType,
  data: FileSpreadsheet,
  generic: File,
}

function EntryIcon({ entry, className }: { entry: FilesystemEntry; className?: string }) {
  if (entry.kind === "folder") return <Folder className={className} />
  const category = getFileCategory(entry.name)
  const Icon = fileIcons[category] ?? File
  return <Icon className={className} />
}

export function PropertiesDialog({
  open,
  onOpenChange,
  entry,
}: PropertiesDialogProps) {
  if (!entry) return null

  const isFolder = entry.kind === "folder"

  const rows: { label: string; value: string }[] = [
    { label: "이름", value: entry.name },
    { label: "유형", value: isFolder ? "디렉터리" : fileTypeLabel(entry.name) },
    { label: "경로", value: entry.key },
  ]
  if (!isFolder) {
    rows.push({
      label: "크기",
      value: `${formatBytes(entry.size)} (${entry.size.toLocaleString()} 바이트)`,
    })
    rows.push({ label: "최종 수정", value: formatDate(entry.lastModified) })
    if (getExtension(entry.name)) {
      rows.push({ label: "확장자", value: `.${getExtension(entry.name)}` })
    }
  }
  rows.push({ label: "소유자", value: entry.owner ?? "-" })
  rows.push({ label: "그룹", value: entry.group ?? "-" })
  rows.push({ label: "권한", value: entry.permissions ?? "-" })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-describedby={undefined} className="sm:max-w-[750px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <EntryIcon
              entry={entry}
              className="h-5 w-5 shrink-0 text-muted-foreground"
            />
            <span className="truncate">{entry.name}</span>
          </DialogTitle>
        </DialogHeader>

        <div className="mt-2">
          <table className="w-full table-fixed border-collapse text-sm text-black">
            <colgroup>
              <col className="w-[100px]" />
              <col />
            </colgroup>
            <thead>
              <tr>
                <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">
                  속성
                </th>
                <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">
                  값
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.label}>
                  <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">
                    {r.label}
                  </th>
                  <td className="border px-3 py-2 align-middle text-black break-all">{r.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DialogContent>
    </Dialog>
  )
}
