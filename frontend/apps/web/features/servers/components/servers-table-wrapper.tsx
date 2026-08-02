"use client"

import { ServersInspectDialog } from "./servers-inspect-dialog"
import { ServersRegisterDialog } from "./servers-register-dialog"
import dynamic from "next/dynamic"

const ServersTerminalDialog = dynamic(
  () => import("./servers-terminal-dialog").then((mod) => mod.ServersTerminalDialog),
  { ssr: false },
)
import { ServersTerminalWarningDialog } from "./servers-terminal-warning-dialog"
import { ServersTopDialog } from "./servers-top-dialog"
import { ServersProcessesDialog } from "./servers-processes-dialog"
import { ServersServicesDialog } from "./servers-services-dialog"
import { ServersUnregisterDialog } from "./servers-unregister-dialog"
import { ServersTable } from "./servers-table"
import { useServers } from "./servers-provider"

export function ServersTableWrapper() {
  const { servers, isLoading, open, setOpen, currentRow, setCurrentRow, selectedServers } = useServers()

  return (
    <>
      <ServersTable data={servers} isLoading={isLoading} />
      <ServersRegisterDialog
        open={open === "register"}
        onOpenChange={(v) => setOpen(v ? "register" : null)}
        currentRow={currentRow}
        selectedServers={selectedServers}
      />
      <ServersUnregisterDialog
        open={open === "unregister"}
        onOpenChange={(v) => setOpen(v ? "unregister" : null)}
        currentRow={currentRow}
        selectedServers={selectedServers}
      />
      <ServersTerminalWarningDialog
        open={open === "terminal-warning"}
        onOpenChange={(v) => setOpen(v ? "terminal-warning" : null)}
      />
      {currentRow && (
        <>
          <ServersTerminalDialog
            key={`terminal-${currentRow.hostname}`}
            open={open === "terminal"}
            onOpenChange={(v) => {
              setOpen(v ? "terminal" : null)
              if (!v) setTimeout(() => setCurrentRow(null), 500)
            }}
            currentRow={currentRow}
          />
          <ServersInspectDialog
            open={open === "inspect"}
            onOpenChange={(v) => {
              setOpen(v ? "inspect" : null)
              if (!v) setTimeout(() => setCurrentRow(null), 300)
            }}
            currentRow={currentRow}
          />
          <ServersTopDialog
            open={open === "top"}
            onOpenChange={(v) => {
              setOpen(v ? "top" : null)
              if (!v) setTimeout(() => setCurrentRow(null), 300)
            }}
            currentRow={currentRow}
          />
          <ServersProcessesDialog
            open={open === "processes"}
            onOpenChange={(v) => {
              setOpen(v ? "processes" : null)
              if (!v) setTimeout(() => setCurrentRow(null), 300)
            }}
            currentRow={currentRow}
          />
          <ServersServicesDialog
            open={open === "services"}
            onOpenChange={(v) => {
              setOpen(v ? "services" : null)
              if (!v) setTimeout(() => setCurrentRow(null), 300)
            }}
            currentRow={currentRow}
          />
        </>
      )}
    </>
  )
}
