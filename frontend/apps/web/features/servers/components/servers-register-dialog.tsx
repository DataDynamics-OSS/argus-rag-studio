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
import { registerServers } from "../api"
import { type Server } from "../data/schema"
import { useServers } from "./servers-provider"

type ServersRegisterDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Single server from row action, or null for bulk action */
  currentRow: Server | null
  selectedServers: Server[]
}

export function ServersRegisterDialog({
  open,
  onOpenChange,
  currentRow,
  selectedServers,
}: ServersRegisterDialogProps) {
  const { refreshServers } = useServers()

  // Determine targets: single row action vs bulk action
  const targets = currentRow ? [currentRow] : selectedServers
  const unregistered = targets.filter((s) => s.status === "UNREGISTERED")
  const isBulk = !currentRow
  const hasNoSelection = isBulk && targets.length === 0

  const handleConfirm = async () => {
    if (unregistered.length === 0) {
      onOpenChange(false)
      return
    }
    try {
      await registerServers(unregistered.map((s) => s.hostname))
      await refreshServers()
    } catch (err) {
      console.error("Failed to register servers:", err)
    }
    onOpenChange(false)
  }

  // Case 1: Bulk action but nothing selected
  if (hasNoSelection) {
    return (
      <AlertDialog open={open} onOpenChange={onOpenChange}>
        <AlertDialogContent>
          <AlertDialogHeader className="text-start">
            <AlertDialogTitle>서버 등록</AlertDialogTitle>
            <AlertDialogDescription>
              등록할 서버를 선택하세요.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button onClick={() => onOpenChange(false)}>확인</Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    )
  }

  // Case 2: Confirm registration
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader className="text-start">
          <AlertDialogTitle>서버 등록</AlertDialogTitle>
          <AlertDialogDescription>
            {unregistered.length > 0
              ? `${unregistered.length}대의 서버를 등록하시겠습니까?`
              : "선택 항목에 미등록 서버가 없습니다."}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter className="flex-row justify-end gap-2 sm:flex-row">
          {unregistered.length > 0 ? (
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
