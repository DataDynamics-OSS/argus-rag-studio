// 상세 페이지 차트 래퍼 (recharts) — 시계열 Line/Area + 사용률 막대.
"use client"

import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

export type SeriesKey = { key: string; label: string; color: string }

function timeLabel(t: number): string {
  const d = new Date(t)
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })
}

/** 시계열 데이터(`[{t, ...}]`)를 라인 차트로. percent=true 면 Y축 0~100 고정. */
export function TimeLineChart({
  data,
  series,
  height = 200,
  percent = false,
  unit = "",
}: {
  data: Record<string, number | string>[]
  series: SeriesKey[]
  height?: number
  percent?: boolean
  unit?: string
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
        <XAxis dataKey="t" tickFormatter={(t) => timeLabel(Number(t))} fontSize={11} minTickGap={40} />
        <YAxis
          domain={percent ? [0, 100] : ["auto", "auto"]}
          fontSize={11}
          width={48}
          tickFormatter={(v) => `${v}${unit}`}
        />
        <Tooltip
          labelFormatter={(t) => timeLabel(Number(t))}
          formatter={(v, name) => [`${typeof v === "number" ? v.toFixed(1) : v}${unit}`, name]}
          contentStyle={{ fontSize: 12 }}
        />
        {series.map((s) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
            stroke={s.color}
            dot={false}
            isAnimationActive={false}
            strokeWidth={2}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

/** 단일 시리즈 영역 차트(메모리 등). */
export function TimeAreaChart({
  data,
  dataKey,
  label,
  color,
  height = 200,
  percent = true,
  unit = "%",
}: {
  data: Record<string, number | string>[]
  dataKey: string
  label: string
  color: string
  height?: number
  percent?: boolean
  unit?: string
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
        <XAxis dataKey="t" tickFormatter={(t) => timeLabel(Number(t))} fontSize={11} minTickGap={40} />
        <YAxis domain={percent ? [0, 100] : ["auto", "auto"]} fontSize={11} width={48} tickFormatter={(v) => `${v}${unit}`} />
        <Tooltip
          labelFormatter={(t) => timeLabel(Number(t))}
          formatter={(v) => [`${typeof v === "number" ? v.toFixed(1) : v}${unit}`, label]}
          contentStyle={{ fontSize: 12 }}
        />
        <Area type="monotone" dataKey={dataKey} name={label} stroke={color} fill={color} fillOpacity={0.18} isAnimationActive={false} strokeWidth={2} />
      </AreaChart>
    </ResponsiveContainer>
  )
}

/** 사용률 막대(0~100). */
export function UsageBar({ percent, color }: { percent: number; color?: string }) {
  const c = color ?? (percent > 90 ? "bg-red-500" : percent > 70 ? "bg-yellow-500" : "bg-green-500")
  return (
    <div className="h-2 w-full rounded-full bg-muted">
      <div className={`h-full rounded-full ${c}`} style={{ width: `${Math.min(percent, 100)}%` }} />
    </div>
  )
}
