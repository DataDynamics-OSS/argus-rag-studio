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

type ServersTerminalWarningDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ServersTerminalWarningDialog({
  open,
  onOpenChange,
}: ServersTerminalWarningDialogProps) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader className="text-start">
          <AlertDialogTitle>터미널 사용 불가</AlertDialogTitle>
          <AlertDialogDescription>
            터미널은 서버가 등록(REGISTERED)된 경우에만 사용할 수 있습니다. 먼저 서버를 등록하세요.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <Button onClick={() => onOpenChange(false)}>
            확인
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
