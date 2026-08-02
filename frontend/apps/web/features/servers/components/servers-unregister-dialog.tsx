"use client"

import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@workspace/ui/components/alert-dialog"
import { Button } from "@workspace/ui/components/button"
import { unregisterServers } from "../api"
import { type Server } from "../data/schema"
import { useServers } from "./servers-provider"

type ServersUnregisterDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Single server from row action, or null for bulk action */
  currentRow: Server | null
  selectedServers: Server[]
}

export function ServersUnregisterDialog({
  open,
  onOpenChange,
  currentRow,
  selectedServers,
}: ServersUnregisterDialogProps) {
  const { refreshServers } = useServers()

  // Determine targets: single row action vs bulk action
  const targets = currentRow ? [currentRow] : selectedServers
  const registered = targets.filter((s) => s.status === "REGISTERED")
  const isBulk = !currentRow
  const hasNoSelection = isBulk && targets.length === 0

  const handleConfirm = async () => {
    if (registered.length === 0) {
      onOpenChange(false)
      return
    }
    try {
      await unregisterServers(registered.map((s) => s.hostname))
      await refreshServers()
    } catch (err) {
      console.error("Failed to unregister servers:", err)
    }
    onOpenChange(false)
  }

  // Case 1: Bulk action but nothing selected
  if (hasNoSelection) {
    return (
      <AlertDialog open={open} onOpenChange={onOpenChange}>
        <AlertDialogContent>
          <AlertDialogHeader className="text-start">
            <AlertDialogTitle>서버 등록 해제</AlertDialogTitle>
            <AlertDialogDescription>
              등록 해제할 서버를 선택하세요.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button onClick={() => onOpenChange(false)}>확인</Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    )
  }

  // Case 2: Confirm unregistration
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader className="text-start">
          <AlertDialogTitle>서버 등록 해제</AlertDialogTitle>
          <AlertDialogDescription>
            {registered.length > 0
              ? `${registered.length}대의 서버를 등록 해제하시겠습니까?`
              : "선택 항목에 등록된 서버가 없습니다."}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter className="flex-row justify-end gap-2 sm:flex-row">
          {registered.length > 0 ? (
            <>
              <Button onClick={handleConfirm}>예</Button>
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                아니오
              </Button>
            </>
          ) : (
            <Button onClick={() => onOpenChange(false)}>확인</Button>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
