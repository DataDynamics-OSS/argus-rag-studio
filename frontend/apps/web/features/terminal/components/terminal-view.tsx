"use client"

import { useCallback, useEffect, useImperativeHandle, useRef, useState, forwardRef } from "react"
import { Terminal } from "@xterm/xterm"
import { FitAddon } from "@xterm/addon-fit"
import { WebLinksAddon } from "@xterm/addon-web-links"
import "@xterm/xterm/css/xterm.css"

interface TerminalViewProps {
  /** WebSocket URL to connect to the terminal proxy. */
  wsUrl: string
  /** Called when connection state changes. */
  onConnectionChange?: (connected: boolean) => void
}

export interface TerminalViewHandle {
  /** Gracefully disconnect the terminal session. */
  disconnect: () => void
}

export const TerminalView = forwardRef<TerminalViewHandle, TerminalViewProps>(
  function TerminalView({ wsUrl, onConnectionChange }, ref) {
    const containerRef = useRef<HTMLDivElement>(null)
    const termRef = useRef<Terminal | null>(null)
    const wsRef = useRef<WebSocket | null>(null)
    const fitAddonRef = useRef<FitAddon | null>(null)
    const cleanedUpRef = useRef(false)
    const [status, setStatus] = useState<"connecting" | "connected" | "disconnected">("connecting")

    const updateStatus = useCallback(
      (s: "connecting" | "connected" | "disconnected") => {
        setStatus(s)
        onConnectionChange?.(s === "connected")
      },
      [onConnectionChange],
    )

    const cleanup = useCallback(() => {
      if (cleanedUpRef.current) return
      cleanedUpRef.current = true

      const ws = wsRef.current
      if (ws && ws.readyState !== WebSocket.CLOSED) {
        ws.close()
      }

      const term = termRef.current
      if (term) {
        term.dispose()
      }

      wsRef.current = null
      termRef.current = null
      fitAddonRef.current = null
      updateStatus("disconnected")
    }, [updateStatus])

    // Expose disconnect method via ref
    useImperativeHandle(ref, () => ({
      disconnect: cleanup,
    }), [cleanup])

    useEffect(() => {
      if (!containerRef.current) return
      cleanedUpRef.current = false

      // --- Terminal setup ---
      const term = new Terminal({
        cursorBlink: true,
        fontSize: 14,
        fontFamily: "'D2Coding', 'JetBrains Mono', 'Fira Code', 'Cascadia Code', Menlo, monospace",
        theme: {
          background: "#1a1b26",
          foreground: "#a9b1d6",
          cursor: "#c0caf5",
          selectionBackground: "#33467c",
          black: "#32344a",
          red: "#f7768e",
          green: "#9ece6a",
          yellow: "#e0af68",
          blue: "#7aa2f7",
          magenta: "#ad8ee6",
          cyan: "#449dab",
          white: "#787c99",
          brightBlack: "#444b6a",
          brightRed: "#ff7a93",
          brightGreen: "#b9f27c",
          brightYellow: "#ff9e64",
          brightBlue: "#7da6ff",
          brightMagenta: "#bb9af7",
          brightCyan: "#0db9d7",
          brightWhite: "#acb0d0",
        },
        scrollback: 5000,
        convertEol: true,
      })

      const fitAddon = new FitAddon()
      const webLinksAddon = new WebLinksAddon()
      term.loadAddon(fitAddon)
      term.loadAddon(webLinksAddon)
      term.open(containerRef.current)
      fitAddon.fit()

      termRef.current = term
      fitAddonRef.current = fitAddon

      // --- WebSocket setup ---
      updateStatus("connecting")
      const ws = new WebSocket(wsUrl)
      ws.binaryType = "arraybuffer"
      wsRef.current = ws

      ws.onopen = () => {
        updateStatus("connected")
        // Send initial resize
        const dims = fitAddon.proposeDimensions()
        if (dims) {
          ws.send(JSON.stringify({ type: "resize", rows: dims.rows, cols: dims.cols }))
        }
      }

      ws.onmessage = (event) => {
        if (event.data instanceof ArrayBuffer) {
          term.write(new Uint8Array(event.data))
        } else {
          term.write(event.data)
        }
      }

      ws.onclose = () => {
        updateStatus("disconnected")
        if (!cleanedUpRef.current) {
          term.write("\r\n\x1b[31m[Connection closed]\x1b[0m\r\n")
        }
      }

      ws.onerror = () => {
        updateStatus("disconnected")
      }

      // --- Terminal → WebSocket ---
      const dataDisposable = term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(data)
        }
      })

      const binaryDisposable = term.onBinary((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          const bytes = new Uint8Array(data.length)
          for (let i = 0; i < data.length; i++) {
            bytes[i] = data.charCodeAt(i) & 0xff
          }
          ws.send(bytes.buffer)
        }
      })

      // --- Resize handling ---
      const resizeDisposable = term.onResize(({ rows, cols }) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "resize", rows, cols }))
        }
      })

      const handleWindowResize = () => {
        fitAddon.fit()
      }
      window.addEventListener("resize", handleWindowResize)

      // ResizeObserver for container size changes
      const resizeObserver = new ResizeObserver(() => {
        fitAddon.fit()
      })
      resizeObserver.observe(containerRef.current)

      // --- Handle browser refresh / tab close ---
      const handleBeforeUnload = () => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.close()
        }
      }
      window.addEventListener("beforeunload", handleBeforeUnload)

      // --- Cleanup ---
      return () => {
        dataDisposable.dispose()
        binaryDisposable.dispose()
        resizeDisposable.dispose()
        window.removeEventListener("resize", handleWindowResize)
        window.removeEventListener("beforeunload", handleBeforeUnload)
        resizeObserver.disconnect()
        ws.close()
        term.dispose()
        termRef.current = null
        wsRef.current = null
        fitAddonRef.current = null
      }
    }, [wsUrl, updateStatus])

    return (
      <div className="flex flex-col h-full">
        <div className="flex items-center gap-2 px-3 py-1.5 bg-[#1a1b26] rounded-t-md border border-b-0 border-[#32344a]">
          <span
            className={`h-2.5 w-2.5 rounded-full ${
              status === "connected"
                ? "bg-green-500"
                : status === "connecting"
                  ? "bg-yellow-500 animate-pulse"
                  : "bg-red-500"
            }`}
          />
          <span className="text-xs text-[#787c99] font-mono">
            {status === "connected"
              ? "Connected"
              : status === "connecting"
                ? "Connecting..."
                : "Disconnected"}
          </span>
        </div>
        <div
          ref={containerRef}
          className="flex-1 min-h-0 rounded-b-md border border-[#32344a] overflow-hidden"
          style={{ backgroundColor: "#1a1b26" }}
        />
      </div>
    )
  }
)
