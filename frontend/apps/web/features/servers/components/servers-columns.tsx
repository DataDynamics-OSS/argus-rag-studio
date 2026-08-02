"use client"

import Link from "next/link"
import { type ColumnDef } from "@tanstack/react-table"

import { SortableHeader } from "@/components/data-table/sortable-header"
import { formatDuration } from "@/lib/format"

import { cn } from "@workspace/ui/lib/utils"
import { Badge } from "@workspace/ui/components/badge"
import { Checkbox } from "@workspace/ui/components/checkbox"
import { serverStatusLabels, serverStatusStyles } from "../data/data"
import { type Server } from "../data/schema"
import { DataTableRowActions } from "./data-table-row-actions"

export const serversColumns: ColumnDef<Server>[] = [
  {
    id: "select",
    header: ({ table }) => (
      <Checkbox
        checked={
          table.getIsAllPageRowsSelected() ||
          (table.getIsSomePageRowsSelected() && "indeterminate")
        }
        onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
        aria-label="전체 선택"
        className="translate-y-[2px]"
      />
    ),
    meta: {
      className: cn("w-12 max-w-12 max-md:sticky start-0 z-10 rounded-tl-[inherit]"),
    },
    cell: ({ row }) => (
      <div onClick={(e) => e.stopPropagation()}>
        <Checkbox
          checked={row.getIsSelected()}
          onCheckedChange={(value) => row.toggleSelected(!!value)}
          aria-label="행 선택"
          className="translate-y-[2px]"
        />
      </div>
    ),
    enableHiding: false,
  },
  {
    accessorKey: "hostname",
    header: ({ column }) => (
      <SortableHeader column={column} title="호스트명" className="justify-center w-full" />
    ),
    cell: ({ row }) => {
      const hostname = row.getValue("hostname") as string
      return (
        <div className="text-center text-sm font-medium">
          <Link
            href={`/dashboard/server-management/${encodeURIComponent(hostname)}`}
            className="text-primary hover:underline"
          >
            {hostname}
          </Link>
        </div>
      )
    },
    enableHiding: false,
  },
  {
    accessorKey: "ipAddress",
    header: ({ column }) => (
      <SortableHeader column={column} title="IP" className="justify-center w-full" />
    ),
    cell: ({ row }) => (
      <div className="text-center text-sm text-nowrap">{row.getValue("ipAddress")}</div>
    ),
    enableHiding: false,
  },
  {
    accessorKey: "version",
    header: ({ column }) => (
      <SortableHeader column={column} title="버전" className="justify-center w-full" />
    ),
    cell: ({ row }) => (
      <div className="text-center text-sm">{row.getValue("version") ?? "-"}</div>
    ),
  },
  {
    accessorKey: "osVersion",
    header: ({ column }) => (
      <SortableHeader column={column} title="OS" className="justify-center w-full" />
    ),
    cell: ({ row }) => (
      <div className="text-center text-sm">{row.getValue("osVersion") ?? "-"}</div>
    ),
  },
  {
    accessorKey: "coreCount",
    header: ({ column }) => (
      <SortableHeader column={column} title="코어" className="justify-center w-full" />
    ),
    cell: ({ row }) => (
      <div className="text-center text-sm">{row.getValue("coreCount") ?? "-"}</div>
    ),
  },
  {
    accessorKey: "totalMemory",
    header: ({ column }) => (
      <SortableHeader column={column} title="총 메모리" className="justify-center w-full" />
    ),
    cell: ({ row }) => {
      const bytes = row.getValue("totalMemory") as number | null
      if (bytes == null) return <div className="text-center text-sm">-</div>
      const gib = bytes / (1024 * 1024 * 1024)
      return (
        <div className="text-center text-sm text-nowrap">
          {gib.toLocaleString(undefined, { maximumFractionDigits: 1 })} GiB
        </div>
      )
    },
  },
  {
    accessorKey: "cpuUsage",
    header: ({ column }) => (
      <SortableHeader column={column} title="CPU 사용률" className="justify-center w-full" />
    ),
    cell: ({ row }) => {
      const value = row.getValue("cpuUsage") as number | null
      if (value == null) return <div className="text-center text-sm">-</div>
      const color = value > 90 ? "bg-red-500" : "bg-green-500"
      return (
        <div className="flex items-center justify-center gap-2 min-w-24 px-2">
          <div className="h-2 w-full rounded-full bg-muted">
            <div
              className={cn("h-full rounded-full", color)}
              style={{ width: `${Math.min(value, 100)}%` }}
            />
          </div>
          <span className="text-xs text-muted-foreground w-10 text-right">{value.toFixed(1)}%</span>
        </div>
      )
    },
  },
  {
    accessorKey: "memoryUsage",
    header: ({ column }) => (
      <SortableHeader column={column} title="메모리 사용률" className="justify-center w-full" />
    ),
    cell: ({ row }) => {
      const value = row.getValue("memoryUsage") as number | null
      if (value == null) return <div className="text-center text-sm">-</div>
      const color = value > 90 ? "bg-red-500" : "bg-green-500"
      return (
        <div className="flex items-center justify-center gap-2 min-w-24 px-2">
          <div className="h-2 w-full rounded-full bg-muted">
            <div
              className={cn("h-full rounded-full", color)}
              style={{ width: `${Math.min(value, 100)}%` }}
            />
          </div>
          <span className="text-xs text-muted-foreground w-10 text-right">{value.toFixed(1)}%</span>
        </div>
      )
    },
  },
  {
    accessorKey: "diskSwapPercent",
    header: ({ column }) => (
      <SortableHeader column={column} title="디스크 스왑" className="justify-center w-full" />
    ),
    cell: ({ row }) => {
      const value = row.getValue("diskSwapPercent") as number | null
      if (value == null) return <div className="text-center text-sm">-</div>
      const color = value > 90 ? "bg-red-500" : "bg-green-500"
      return (
        <div className="flex items-center justify-center gap-2 min-w-24 px-2">
          <div className="h-2 w-full rounded-full bg-muted">
            <div
              className={cn("h-full rounded-full", color)}
              style={{ width: `${Math.min(value, 100)}%` }}
            />
          </div>
          <span className="text-xs text-muted-foreground w-10 text-right">{value.toFixed(1)}%</span>
        </div>
      )
    },
  },
  {
    accessorKey: "gpuUsage",
    header: ({ column }) => (
      <SortableHeader column={column} title="GPU" className="justify-center w-full" />
    ),
    cell: ({ row }) => {
      const { gpuUsage, gpuCount, gpuName } = row.original
      if (gpuUsage == null || !gpuCount) {
        return <div className="text-center text-sm text-muted-foreground">-</div>
      }
      const color = gpuUsage > 90 ? "bg-red-500" : "bg-green-500"
      return (
        <div
          className="flex items-center justify-center gap-2 min-w-28 px-2"
          title={gpuName ? `${gpuName} ×${gpuCount}` : `GPU ×${gpuCount}`}
        >
          <div className="h-2 w-full rounded-full bg-muted">
            <div
              className={cn("h-full rounded-full", color)}
              style={{ width: `${Math.min(gpuUsage, 100)}%` }}
            />
          </div>
          <span className="text-xs text-muted-foreground w-16 text-right text-nowrap">
            {gpuUsage.toFixed(0)}% ·{gpuCount}×
          </span>
        </div>
      )
    },
  },
  {
    accessorKey: "status",
    header: ({ column }) => (
      <SortableHeader column={column} title="상태" className="justify-center w-full" />
    ),
    cell: ({ row }) => {
      const { status } = row.original
      const badgeColor = serverStatusStyles.get(status)
      return (
        <div className="flex justify-center">
          <Badge variant="outline" className={cn(badgeColor)}>
            {serverStatusLabels.get(status) ?? status}
          </Badge>
        </div>
      )
    },
    filterFn: (row, id, value) => {
      return value.includes(row.getValue(id))
    },
    enableHiding: false,
  },
  {
    accessorKey: "lastHeartbeatSeconds",
    header: ({ column }) => (
      <SortableHeader column={column} title="마지막 하트비트" className="justify-center w-full" />
    ),
    cell: ({ row }) => {
      const seconds = row.getValue("lastHeartbeatSeconds") as number | null
      if (seconds == null) return <div className="text-center text-sm">-</div>
      return (
        <div className="text-center text-sm text-nowrap" title={`${seconds.toLocaleString()}초 전`}>
          {formatDuration(seconds)} 전
        </div>
      )
    },
  },
  {
    id: "actions",
    cell: DataTableRowActions,
  },
]
