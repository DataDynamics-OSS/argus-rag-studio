"use client"

import { type Row } from "@tanstack/react-table"
import { Activity, List, Minus, MoreHorizontal, Plus, Rocket, Search, Terminal } from "lucide-react"

import { Button } from "@workspace/ui/components/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@workspace/ui/components/dropdown-menu"
import { type Server } from "../data/schema"
import { useServers } from "./servers-provider"

type DataTableRowActionsProps = {
  row: Row<Server>
}

export function DataTableRowActions({ row }: DataTableRowActionsProps) {
  const { setCurrentRow, setOpen } = useServers()

  const status = row.original.status
  // UNREGISTERED: 등록만 / DISCONNECTED: 등록 해제만 / REGISTERED: 등록 외 전부.
  const canRegister = status === "UNREGISTERED"
  const canUnregister = status === "REGISTERED" || status === "DISCONNECTED"
  // 점검·Top·프로세스·서비스·터미널은 연결되어 관리 중(REGISTERED)일 때만 동작 가능.
  const canManage = status === "REGISTERED"

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          className="flex h-8 w-8 p-0 data-[state=open]:bg-muted"
        >
          <MoreHorizontal className="h-4 w-4" />
          <span className="sr-only">메뉴 열기</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[160px]">
        <DropdownMenuItem
          disabled={!canRegister}
          onClick={() => {
            setCurrentRow(row.original)
            setOpen("register")
          }}
        >
          등록
          <span className="ml-auto">
            <Plus size={16} />
          </span>
        </DropdownMenuItem>
        <DropdownMenuItem
          disabled={!canUnregister}
          onClick={() => {
            setCurrentRow(row.original)
            setOpen("unregister")
          }}
        >
          등록 해제
          <span className="ml-auto">
            <Minus size={16} />
          </span>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          disabled={!canManage}
          onClick={() => {
            setCurrentRow(row.original)
            setOpen("inspect")
          }}
        >
          상세 점검
          <span className="ml-auto">
            <Search size={16} />
          </span>
        </DropdownMenuItem>
        <DropdownMenuItem
          disabled={!canManage}
          onClick={() => {
            setCurrentRow(row.original)
            setOpen("top")
          }}
        >
          리소스(Top)
          <span className="ml-auto">
            <Activity size={16} />
          </span>
        </DropdownMenuItem>
        <DropdownMenuItem
          disabled={!canManage}
          onClick={() => {
            setCurrentRow(row.original)
            setOpen("processes")
          }}
        >
          프로세스
          <span className="ml-auto">
            <List size={16} />
          </span>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          disabled={!canManage}
          onClick={() => {
            setCurrentRow(row.original)
            setOpen("services")
          }}
        >
          서비스 / 워커 배포
          <span className="ml-auto">
            <Rocket size={16} />
          </span>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          disabled={!canManage}
          onClick={() => {
            setCurrentRow(row.original)
            setOpen("terminal")
          }}
        >
          터미널
          <span className="ml-auto">
            <Terminal size={16} />
          </span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
