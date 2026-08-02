"use client"

// 배포된 서비스 선택 픽커 — 서버 URL 을 손으로 치는 대신 실행 중 서비스에서 고른다.
// 사용처: 라우팅 정책(llm_classify)·인제스천 파이프라인(image_captions)·설정 화면.
// 목록 조회는 백엔드/프론트 60s TTL 캐시를 타므로 첫 호출만 수 초 걸린다.

import { useEffect, useState } from "react"

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { fetchServiceEndpoints, type ServiceEndpoint } from "@/features/deploy/api"

const CUSTOM = "__custom__"
const LOADING = "__loading__"
const NONE = "__none__"

export function ServiceEndpointPicker({
  kind,
  value,
  disabled,
  onPick,
  className,
  allowCustom = true,
}: {
  kind: string // embedding | reranker | vlm | detection | hwp_render
  value: string // 현재 server_url (서비스 목록에 있으면 해당 항목 선택 표시)
  disabled?: boolean
  onPick: (svc: { url: string; model: string | null } | null) => void // null = 직접 입력 선택
  className?: string
  // false 면 '직접 입력' 을 제공하지 않는다 — 등록(배포)된 서비스만 허용하는 방침의 화면용.
  allowCustom?: boolean
}) {
  const [services, setServices] = useState<ServiceEndpoint[]>([])
  const [loading, setLoading] = useState(true)
  // "직접 입력" 을 고른 뒤에는 URL 이 서비스와 일치해도 되돌리지 않는다 —
  // 완전 제어형으로 두면 선택 직후 서비스 항목으로 스냅백해 '선택이 무시되는' 버그가 된다.
  const [custom, setCustom] = useState(false)

  useEffect(() => {
    let alive = true
    fetchServiceEndpoints(kind)
      .then((rows) => alive && setServices(rows))
      .catch(() => alive && setServices([]))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [kind])

  const matched = services.find((s) => s.url === value)
  const selectValue = loading
    ? LOADING
    : !custom && matched
      ? matched.url
      : allowCustom
        ? CUSTOM
        : NONE // 직접 입력 불가 화면 — 매칭 없으면 '서비스 선택' 플레이스홀더 상태
  return (
    <Select
      value={selectValue}
      disabled={disabled || loading}
      onValueChange={(v) => {
        if (v === CUSTOM) {
          setCustom(true)
          onPick(null)
        } else if (v !== LOADING) {
          const svc = services.find((s) => s.url === v)
          if (svc) {
            setCustom(false)
            onPick({ url: svc.url, model: svc.model })
          }
        }
      }}
    >
      <SelectTrigger className={className ?? "h-8 w-96 text-sm"}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {loading && (
          <SelectItem value={LOADING} disabled>
            서비스 조회 중...
          </SelectItem>
        )}
        {services.map((s) => (
          <SelectItem key={s.url} value={s.url}>
            <span className="font-medium">{s.name}</span>
            <span className="ml-2 font-mono text-xs text-muted-foreground">{s.url}</span>
            {s.model && <span className="ml-2 text-xs text-muted-foreground">({s.model})</span>}
          </SelectItem>
        ))}
        {!loading && services.length === 0 && (
          <div className="px-2 py-1.5 text-sm text-muted-foreground">
            실행 중인 {kind} 서비스 없음
          </div>
        )}
        {allowCustom ? (
          <SelectItem value={CUSTOM}>직접 입력</SelectItem>
        ) : (
          <SelectItem value={NONE} disabled className="hidden">
            서비스 선택
          </SelectItem>
        )}
      </SelectContent>
    </Select>
  )
}
