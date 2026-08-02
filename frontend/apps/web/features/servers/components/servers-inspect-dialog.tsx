"use client"

import { useCallback, useEffect, useState } from "react"
import {
  Cpu,
  Download,
  FileText,
  Flame,
  Globe,
  HardDrive,
  Info,
  Loader2,
  Monitor,
  Network,
  ScrollText,
  Server,
  Shield,
  Terminal,
  Users,
} from "lucide-react"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@workspace/ui/components/sheet"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@workspace/ui/components/dropdown-menu"
import { Separator } from "@workspace/ui/components/separator"
import { PlainCodeViewer } from "./plain-code-viewer"
import { fetchInspect } from "../api"
import { type Server as ServerType } from "../data/schema"

type ServersInspectDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  currentRow: ServerType
}

/* eslint-disable @typescript-eslint/no-explicit-any */

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B"
  const k = 1024
  const sizes = ["B", "KB", "MB", "GB", "TB"]
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
}

function Section({
  icon: Icon,
  title,
  children,
}: {
  icon: React.ElementType
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <Icon className="h-4 w-4 text-muted-foreground" />
        {title}
      </div>
      <div className="rounded-lg border bg-card">{children}</div>
    </div>
  )
}

function Field({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-4 px-4 py-2.5 text-sm border-b last:border-b-0">
      <span className="text-muted-foreground shrink-0">{label}</span>
      <span className={`text-right break-all ${mono ? "font-mono text-xs" : ""}`}>{value}</span>
    </div>
  )
}

export function ServersInspectDialog({
  open,
  onOpenChange,
  currentRow,
}: ServersInspectDialogProps) {
  const [data, setData] = useState<Record<string, any> | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadInspect = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await fetchInspect(currentRow.hostname)
      setData(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : "점검 데이터를 불러오지 못했습니다")
    } finally {
      setLoading(false)
    }
  }, [currentRow.hostname])

  useEffect(() => {
    if (open) {
      loadInspect()
    } else {
      setData(null)
      setError(null)
    }
  }, [open, loadInspect])

  const esc = (s: string) => s?.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") ?? ""

  const buildInspectHtml = useCallback(() => {
    if (!data) return ""
    const now = new Date().toLocaleString()
    const hn = data.hostname as any
    const ru = data.resource_usage as any
    const ips = (data.ip_addresses ?? []) as any[]
    const nss = (data.nameservers ?? []) as any[]
    const dps = (data.disk_partitions ?? []) as any[]
    const procs = (data.processes ?? []) as any[]
    const uls = (data.ulimits ?? []) as any[]
    const nifs = (data.network_interfaces ?? []) as any[]

    const field = (label: string, value: string) =>
      `<tr><td class="lbl">${esc(label)}</td><td class="val">${esc(String(value ?? ""))}</td></tr>`

    const sectionStart = (title: string) =>
      `<h2>${esc(title)}</h2><table class="kv">`
    const sectionEnd = `</table>`

    const codeBlock = (title: string, content: string) =>
      `<h2>${esc(title)}</h2><pre>${esc(content ?? "")}</pre>`

    let html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Inspect - ${esc(currentRow.hostname)}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 24px; color: #1a1a1a; max-width: 900px; }
  h1 { font-size: 20px; margin-bottom: 4px; }
  .meta { font-size: 13px; color: #666; margin-bottom: 20px; }
  h2 { font-size: 15px; margin: 20px 0 8px; padding-bottom: 4px; border-bottom: 2px solid #e5e5e5; }
  table.kv { border-collapse: collapse; width: 100%; font-size: 13px; margin-bottom: 8px; }
  table.kv td { border: 1px solid #ddd; padding: 6px 10px; }
  table.kv td.lbl { background: #f8f8f8; font-weight: 500; width: 220px; white-space: nowrap; }
  table.kv td.val { font-family: monospace; font-size: 12px; word-break: break-all; }
  table.proc { border-collapse: collapse; width: 100%; font-size: 12px; }
  table.proc th, table.proc td { border: 1px solid #ddd; padding: 4px 8px; white-space: nowrap; }
  table.proc th { background: #f5f5f5; font-weight: 600; text-align: left; }
  table.proc td.r { text-align: right; }
  pre { background: #f5f5f5; border: 1px solid #ddd; border-radius: 4px; padding: 12px; font-size: 12px; overflow-x: auto; white-space: pre-wrap; word-break: break-all; max-height: 400px; }
  @media print { body { margin: 10px; } h1 { font-size: 16px; } pre { max-height: none; } }
</style>
</head>
<body>
<h1>Host Inspection - ${esc(currentRow.hostname)}</h1>
<div class="meta">${esc(currentRow.ipAddress)} &middot; ${now}</div>`

    // Hostname
    html += sectionStart("Hostname")
    html += field("Hostname", hn?.hostname)
    html += field("FQDN", hn?.fqdn)
    html += field("Hostname == FQDN", hn?.is_consistent ? "YES" : "NO")
    html += sectionEnd

    // Firewall
    html += sectionStart("Firewall")
    html += field("Firewall Enabled?", data.firewall_enabled ? "ENABLED" : "DISABLED")
    html += sectionEnd

    // Network
    html += sectionStart("Network")
    for (const ip of ips) html += field(ip.interface, ip.address)
    for (let i = 0; i < nss.length; i++) html += field(`Nameserver ${i + 1}`, nss[i].address)
    html += sectionEnd

    // Resource Usage
    html += sectionStart("Resource Usage")
    html += field("CPU Cores", String(ru?.cpu_cores ?? ""))
    html += field("Total Memory", formatBytes(ru?.total_memory_bytes ?? 0))
    html += field("CPU Usage", `${ru?.cpu_usage_percent?.toFixed(1)}%`)
    html += field("Memory Usage", `${ru?.memory_usage_percent?.toFixed(1)}%`)
    html += field("Swap Usage", `${ru?.swap_usage_percent?.toFixed(1)}%`)
    html += sectionEnd

    // Disk Partitions
    html += sectionStart("Disk Partitions")
    for (const dp of dps) {
      html += `<tr><td class="lbl">${esc(dp.device)} (${esc(dp.fs_type)})</td>`
      html += `<td class="val">Mount: ${esc(dp.mount_point)} &middot; Total: ${formatBytes(dp.total_bytes)} &middot; Used: ${dp.usage_percent?.toFixed(1)}%</td></tr>`
    }
    html += sectionEnd

    // Ulimit
    html += sectionStart("Ulimit")
    for (const ul of uls) html += field(`${ul.resource} (${ul.option})`, `soft=${ul.soft} / hard=${ul.hard}`)
    html += sectionEnd

    // Network Interfaces
    html += sectionStart("Network Interfaces (ifconfig)")
    for (const iface of nifs) {
      const parts = [iface.inet && `inet ${iface.inet}`, iface.netmask && `netmask ${iface.netmask}`, iface.ether && `ether ${iface.ether}`, iface.mtu && `mtu ${iface.mtu}`].filter(Boolean).join(" · ")
      html += `<tr><td class="lbl">${esc(iface.name)}${iface.flags ? ` <small>${esc(iface.flags)}</small>` : ""}</td><td class="val">${esc(parts)}</td></tr>`
    }
    html += sectionEnd

    // uname
    html += codeBlock("System Info (uname -a)", data.uname as string)

    // Process List
    html += `<h2>Processes (${procs.length})</h2>`
    html += `<table class="proc"><thead><tr><th>UID</th><th class="r">PID</th><th class="r">PPID</th><th>C</th><th>STIME</th><th>TTY</th><th>TIME</th><th>CMD</th></tr></thead><tbody>`
    for (const p of procs) {
      html += `<tr><td>${esc(p.uid)}</td><td class="r">${p.pid}</td><td class="r">${p.ppid}</td><td>${esc(p.c)}</td><td>${esc(p.stime)}</td><td>${esc(p.tty)}</td><td>${esc(p.time)}</td><td>${esc(p.cmd)}</td></tr>`
    }
    html += `</tbody></table>`

    // Environment Variables
    html += codeBlock("Environment Variables (set)", data.env_variables as string)

    // sysctl.conf
    html += codeBlock("/etc/sysctl.conf", data.sysctl_conf as string)

    // /etc/passwd
    html += codeBlock("/etc/passwd", data.etc_passwd as string)

    // /etc/hosts
    html += codeBlock("/etc/hosts", data.etc_hosts as string)

    html += `</body></html>`
    return html
  }, [data, currentRow])

  const downloadHtml = useCallback(() => {
    const html = buildInspectHtml()
    if (!html) return
    const blob = new Blob([html], { type: "text/html;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `inspect-${currentRow.hostname}-${new Date().toISOString().slice(0, 19).replace(/:/g, "")}.html`
    a.click()
    URL.revokeObjectURL(url)
  }, [buildInspectHtml, currentRow])

  const downloadPdf = useCallback(() => {
    const html = buildInspectHtml()
    if (!html) return
    const win = window.open("", "_blank")
    if (!win) return
    win.document.write(html)
    win.document.close()
    win.onload = () => {
      win.onafterprint = () => win.close()
      win.print()
    }
  }, [buildInspectHtml])

  const hostname = data?.hostname as any
  const resourceUsage = data?.resource_usage as any
  const ipAddresses = (data?.ip_addresses ?? []) as any[]
  const nameservers = (data?.nameservers ?? []) as any[]
  const diskPartitions = (data?.disk_partitions ?? []) as any[]
  const processes = (data?.processes ?? []) as any[]
  const ulimits = (data?.ulimits ?? []) as any[]
  const networkInterfaces = (data?.network_interfaces ?? []) as any[]

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="overflow-y-auto px-5"
        style={{ width: 600, maxWidth: "none" }}
      >
        <SheetHeader>
          <div className="flex items-center justify-between">
            <SheetTitle className="flex items-center gap-2">
              <Monitor className="h-5 w-5" />
              호스트 점검
            </SheetTitle>
            {data && !loading && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" className="h-8 text-sm gap-1.5 mr-8">
                    <Download className="h-3.5 w-3.5" />
                    내보내기
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={downloadHtml}>
                    <Globe className="h-4 w-4 mr-2" />
                    HTML 다운로드
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={downloadPdf}>
                    <FileText className="h-4 w-4 mr-2" />
                    PDF 다운로드
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
          <SheetDescription>
            {currentRow.hostname} ({currentRow.ipAddress})
          </SheetDescription>
        </SheetHeader>

        {loading && (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            <span className="ml-2 text-sm text-muted-foreground">호스트 점검 중...</span>
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-4 text-sm text-destructive">
            {error}
          </div>
        )}

        {data && !loading && (
          <div className="space-y-6 pb-6">
            {/* 1. Hostname */}
            <Section icon={Server} title="호스트명">
              <Field label="호스트명" value={hostname?.hostname} mono />
              <Field label="FQDN" value={hostname?.fqdn} mono />
              <Field
                label="Hostname == FQDN"
                value={
                  <Badge
                    variant={hostname?.is_consistent ? "default" : "destructive"}
                    className={hostname?.is_consistent ? "bg-blue-500 hover:bg-blue-600 text-white" : ""}
                  >
                    {hostname?.is_consistent ? "YES" : "NO"}
                  </Badge>
                }
              />
            </Section>

            {/* 2. Firewall */}
            <Section icon={Flame} title="방화벽">
              <Field
                label="Firewall Enabled?"
                value={
                  <Badge
                    variant={data?.firewall_enabled ? "destructive" : "default"}
                    className={data?.firewall_enabled ? "" : "bg-blue-500 hover:bg-blue-600 text-white"}
                  >
                    {data?.firewall_enabled ? "ENABLED" : "DISABLED"}
                  </Badge>
                }
              />
            </Section>

            {/* 3. Network */}
            <Section icon={Network} title="네트워크">
              {ipAddresses.map((ip: any, i: number) => (
                <Field key={i} label={ip.interface} value={ip.address} mono />
              ))}
              {nameservers.length > 0 && (
                <>
                  {nameservers.map((ns: any, i: number) => (
                    <Field key={`ns-${i}`} label={`Nameserver ${i + 1}`} value={ns.address} mono />
                  ))}
                </>
              )}
            </Section>

            {/* 3. Resource Usage */}
            <Section icon={Cpu} title="리소스 사용량">
              <Field label="CPU 코어" value={resourceUsage?.cpu_cores} />
              <Field label="총 메모리" value={formatBytes(resourceUsage?.total_memory_bytes ?? 0)} />
              <Field
                label="CPU 사용률"
                value={`${resourceUsage?.cpu_usage_percent?.toFixed(1)}%`}
              />
              <Field
                label="메모리 사용률"
                value={`${resourceUsage?.memory_usage_percent?.toFixed(1)}%`}
              />
              <Field
                label="Swap Usage"
                value={`${resourceUsage?.swap_usage_percent?.toFixed(1)}%`}
              />
            </Section>

            {/* 4. Disk Partitions */}
            <Section icon={HardDrive} title="디스크 파티션">
              {diskPartitions.map((dp: any, i: number) => (
                <div key={i} className="px-4 py-2.5 border-b last:border-b-0">
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-mono text-xs">{dp.device}</span>
                    <Badge variant="outline">{dp.fs_type}</Badge>
                  </div>
                  <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
                    <span>Mount: {dp.mount_point}</span>
                    <span>Total: {formatBytes(dp.total_bytes)}</span>
                    <span>Used: {dp.usage_percent?.toFixed(1)}%</span>
                  </div>
                </div>
              ))}
            </Section>

            {/* 5. Ulimit */}
            <Section icon={Shield} title="Ulimit">
              {ulimits.map((ul: any, i: number) => (
                <Field
                  key={i}
                  label={`${ul.resource} (${ul.option})`}
                  value={`soft=${ul.soft} / hard=${ul.hard}`}
                  mono
                />
              ))}
            </Section>

            {/* 6. Network Interfaces */}
            <Section icon={Network} title="네트워크 인터페이스 (ifconfig)">
              {networkInterfaces.map((iface: any, i: number) => (
                <div key={i} className="px-4 py-2.5 border-b last:border-b-0">
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-semibold">{iface.name}</span>
                    {iface.flags && (
                      <span className="text-xs text-muted-foreground">{iface.flags}</span>
                    )}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted-foreground font-mono">
                    {iface.inet && <span>inet {iface.inet}</span>}
                    {iface.netmask && <span>netmask {iface.netmask}</span>}
                    {iface.ether && <span>ether {iface.ether}</span>}
                    {iface.mtu && <span>mtu {iface.mtu}</span>}
                  </div>
                </div>
              ))}
            </Section>

            {/* 7. uname -a */}
            <Section icon={Info} title="시스템 정보 (uname -a)">
              <div className="p-3">
                <PlainCodeViewer content={data.uname as string} maxHeight="80px" />
              </div>
            </Section>

            {/* 8. Process List */}
            <Section icon={Terminal} title={`프로세스 (${processes.length})`}>
              <div className="p-3">
                <PlainCodeViewer
                  content={
                    "UID        PID  PPID  C STIME TTY      TIME     CMD\n" +
                    processes
                      .map(
                        (p: any) =>
                          `${p.uid.padEnd(9)} ${String(p.pid).padStart(5)} ${String(p.ppid).padStart(5)}  ${p.c} ${p.stime.padEnd(5)} ${p.tty.padEnd(8)} ${p.time.padEnd(8)} ${p.cmd}`
                      )
                      .join("\n")
                  }
                  maxHeight="300px"
                />
              </div>
            </Section>

            {/* 9. Environment Variables */}
            <Section icon={ScrollText} title="환경 변수 (set)">
              <div className="p-3">
                <PlainCodeViewer content={data.env_variables as string} maxHeight="300px" />
              </div>
            </Section>

            {/* 10. sysctl.conf */}
            <Section icon={Shield} title="/etc/sysctl.conf">
              <div className="p-3">
                <PlainCodeViewer content={data.sysctl_conf as string} maxHeight="300px" />
              </div>
            </Section>

            {/* 11. /etc/passwd */}
            <Section icon={Users} title="/etc/passwd">
              <div className="p-3">
                <PlainCodeViewer content={data.etc_passwd as string} maxHeight="300px" />
              </div>
            </Section>

            {/* 12. /etc/hosts */}
            <Section icon={Server} title="/etc/hosts">
              <div className="p-3">
                <PlainCodeViewer content={data.etc_hosts as string} maxHeight="200px" />
              </div>
            </Section>

            <Separator />
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
