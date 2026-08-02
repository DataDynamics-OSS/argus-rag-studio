"use client"

import { Badge } from "@workspace/ui/components/badge"

import { runtimePrivilege } from "../api"

/** 런타임(docker/systemd/k8s)별 권한 등급 배지. */
export function PrivilegeBadge({ runtime }: { runtime: string }) {
  const p = runtimePrivilege[runtime]
  if (!p) return null
  return (
    <Badge variant="outline" className={p.cls} title={`필요 권한: ${p.privilege}`}>
      {p.label}
    </Badge>
  )
}
