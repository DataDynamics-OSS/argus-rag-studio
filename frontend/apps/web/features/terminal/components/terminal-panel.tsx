"use client"

import { useCallback, useState } from "react"
import { TerminalIcon } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import { TerminalView } from "./terminal-view"

export function buildTerminalWsUrl(hostname: string): string {
  // WebSocket 은 Next.js 프록시(HTTP 전용)를 통과하지 못하므로 백엔드(:4700)로 직접 연결한다.
  // NEXT_PUBLIC_API_URL 이 있으면 그것을, 없으면 현재 호스트의 백엔드 포트(4700)를 사용.
  const base =
    process.env.NEXT_PUBLIC_API_URL ??
    `${window.location.protocol}//${window.location.hostname}:4700`
  const wsBase = base.replace(/^http/, "ws")
  return `${wsBase}/api/v1/servermgr/servers/${encodeURIComponent(hostname)}/terminal/ws`
}

export function TerminalPanel() {
  const [hostname, setHostname] = useState("")
  const [activeHost, setActiveHost] = useState<string | null>(null)
  const [connected, setConnected] = useState(false)

  const handleConnect = useCallback(() => {
    const h = hostname.trim()
    if (!h) return
    setActiveHost(null)
    setTimeout(() => setActiveHost(h), 0)
  }, [hostname])

  const handleDisconnect = useCallback(() => {
    setActiveHost(null)
    setConnected(false)
  }, [])

  return (
    <div className="flex flex-col h-full gap-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <TerminalIcon className="h-4 w-4" />
            원격 터미널
          </CardTitle>
          <CardDescription>
            에이전트 서버에 원격 터미널로 접속합니다.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-end gap-3">
            <div className="flex-1">
              <Label htmlFor="hostname" className="text-xs mb-1.5 block">
                호스트명
              </Label>
              <Input
                id="hostname"
                placeholder="호스트명을 입력하세요"
                value={hostname}
                onChange={(e) => setHostname(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleConnect()
                }}
                className="h-9 text-sm font-mono"
              />
            </div>
            {!activeHost ? (
              <Button
                onClick={handleConnect}
                disabled={!hostname.trim()}
                size="sm"
                className="h-9"
              >
                접속
              </Button>
            ) : (
              <Button
                onClick={handleDisconnect}
                variant="destructive"
                size="sm"
                className="h-9"
              >
                연결 해제
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {activeHost ? (
        <div className="flex-1 min-h-0">
          <TerminalView
            wsUrl={buildTerminalWsUrl(activeHost)}
            onConnectionChange={setConnected}
          />
        </div>
      ) : (
        <Card className="flex-1 flex items-center justify-center">
          <div className="text-center text-muted-foreground">
            <TerminalIcon className="h-12 w-12 mx-auto mb-3 opacity-30" />
            <p className="text-sm">에이전트에 접속하면 터미널이 표시됩니다.</p>
          </div>
        </Card>
      )}
    </div>
  )
}
