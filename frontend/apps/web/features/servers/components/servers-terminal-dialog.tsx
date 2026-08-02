"use client"

import { useRef, useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@workspace/ui/components/alert-dialog"
import { Button } from "@workspace/ui/components/button"
import { TerminalView, type TerminalViewHandle } from "@/features/terminal/components/terminal-view"
import { buildTerminalWsUrl } from "@/features/terminal/components/terminal-panel"
import { type Server } from "../data/schema"

type ServersTerminalDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  currentRow: Server
}

export function ServersTerminalDialog({
  open,
  onOpenChange,
  currentRow,
}: ServersTerminalDialogProps) {
  const terminalRef = useRef<TerminalViewHandle>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const handleDisconnect = () => {
    terminalRef.current?.disconnect()
    setConfirmOpen(false)
    onOpenChange(false)
  }

  return (
    <>
      <Dialog open={open} onOpenChange={() => {}}>
        <DialogContent
          className="max-w-5xl h-[80vh] flex flex-col"
          showCloseButton={false}
          onInteractOutside={(e) => e.preventDefault()}
          onEscapeKeyDown={(e) => e.preventDefault()}
        >
          <DialogHeader>
            <DialogTitle className="font-mono text-sm">
              터미널 — {currentRow.hostname} ({currentRow.ipAddress})
            </DialogTitle>
          </DialogHeader>
          <div className="flex-1 min-h-0">
            {open && (
              <TerminalView
                ref={terminalRef}
                wsUrl={buildTerminalWsUrl(currentRow.hostname)}
              />
            )}
          </div>
          <div className="flex justify-center pt-3">
            <Button
              variant="destructive"
              onClick={() => setConfirmOpen(true)}
            >
              연결 해제
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>터미널 연결 해제</AlertDialogTitle>
            <AlertDialogDescription>
              서버와의 연결을 해제하시겠습니까?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>아니오</AlertDialogCancel>
            <AlertDialogAction onClick={handleDisconnect}>
              예
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
