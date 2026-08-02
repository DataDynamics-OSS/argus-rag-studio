"use client"

// 이미지 파일 자체의 메타데이터 표시 — DB 기본 정보(해상도/형식/크기) + EXIF(카메라/촬영설정/일시/GPS).
// EXIF 는 이미 받아온 이미지 blob 을 클라이언트에서 exifr 로 파싱한다(백엔드 변경 불필요).
// PNG·스크린샷·웹 가공 이미지 등은 EXIF 가 없을 수 있다.

import { useEffect, useState } from "react"
import exifr from "exifr"
import { Loader2, MapPin } from "lucide-react"
import type { AnnotationDetail } from "../data/schema"

interface Row {
  label: string
  value: React.ReactNode
}
interface Section {
  title: string
  rows: Row[]
}

// ── 포맷 헬퍼 ──────────────────────────────────────────────────────────────
function fmtBytes(n: number): string {
  if (!n) return "0 B"
  const u = ["B", "KB", "MB", "GB"]
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)))
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`
}

function gcd(a: number, b: number): number {
  return b ? gcd(b, a % b) : a
}

function aspectRatio(w: number, h: number): string {
  if (!w || !h) return "—"
  const g = gcd(w, h)
  return `${w / g} : ${h / g}`
}

function fmtNum(v: unknown, digits = 0, suffix = ""): string | null {
  if (typeof v !== "number" || Number.isNaN(v)) return null
  return `${digits ? v.toFixed(digits) : Math.round(v)}${suffix}`
}

function fmtExposure(v: unknown): string | null {
  if (typeof v !== "number" || v <= 0) return null
  return v >= 1 ? `${v} s` : `1/${Math.round(1 / v)} s`
}

function fmtDate(v: unknown): string | null {
  if (v instanceof Date && !Number.isNaN(v.getTime())) return v.toLocaleString()
  if (typeof v === "string" && v.trim()) return v
  return null
}

function str(v: unknown): string | null {
  if (v == null) return null
  const s = String(v).trim()
  return s.length ? s : null
}

/** value 가 있는 행만 추려 섹션을 만든다(빈 섹션은 호출부에서 제외). */
function section(title: string, rows: (Row | null)[]): Section | null {
  const filtered = rows.filter((r): r is Row => r != null)
  return filtered.length ? { title, rows: filtered } : null
}

export function ImageInfo({ detail, imgUrl }: { detail: AnnotationDetail; imgUrl: string }) {
  const [exif, setExif] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    if (!imgUrl) {
      setLoading(false)
      return
    }
    ;(async () => {
      try {
        // gps:true → latitude/longitude 십진수 좌표 계산 포함.
        const data = await exifr.parse(imgUrl, { gps: true })
        if (!cancelled) setExif((data as Record<string, unknown>) ?? null)
      } catch {
        if (!cancelled) setExif(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [imgUrl])

  const e = exif ?? {}
  const ext = (detail.filename.split(".").pop() || "").toUpperCase()
  const mp = detail.width && detail.height ? (detail.width * detail.height) / 1e6 : 0

  const lat = typeof e.latitude === "number" ? e.latitude : null
  const lng = typeof e.longitude === "number" ? e.longitude : null

  const sections: (Section | null)[] = [
    section("파일", [
      { label: "해상도", value: `${detail.width} × ${detail.height} px` },
      mp ? { label: "메가픽셀", value: `${mp.toFixed(1)} MP` } : null,
      { label: "종횡비", value: aspectRatio(detail.width, detail.height) },
      { label: "파일 형식", value: detail.content_type || ext || "—" },
      { label: "파일 크기", value: fmtBytes(detail.size_bytes) },
      detail.content_hash
        ? { label: "SHA-256", value: <span className="break-all font-mono text-xs">{detail.content_hash}</span> }
        : null,
    ]),
    section("카메라", [
      str(e.Make) ? { label: "제조사", value: str(e.Make)! } : null,
      str(e.Model) ? { label: "모델", value: str(e.Model)! } : null,
      str(e.LensModel) ? { label: "렌즈", value: str(e.LensModel)! } : null,
      str(e.Software) ? { label: "소프트웨어", value: str(e.Software)! } : null,
    ]),
    section("촬영 설정", [
      fmtNum(e.ISO, 0) ? { label: "ISO", value: fmtNum(e.ISO, 0)! } : null,
      fmtNum(e.FNumber, 1, "") ? { label: "조리개", value: `f/${fmtNum(e.FNumber, 1)}` } : null,
      fmtExposure(e.ExposureTime) ? { label: "셔터 속도", value: fmtExposure(e.ExposureTime)! } : null,
      fmtNum(e.FocalLength, 0, " mm") ? { label: "초점 거리", value: fmtNum(e.FocalLength, 0, " mm")! } : null,
      fmtNum(e.FocalLengthIn35mmFormat, 0, " mm")
        ? { label: "35mm 환산", value: fmtNum(e.FocalLengthIn35mmFormat, 0, " mm")! }
        : null,
      fmtNum(e.ExposureCompensation, 1, " EV")
        ? { label: "노출 보정", value: fmtNum(e.ExposureCompensation, 1, " EV")! }
        : null,
      str(e.MeteringMode) ? { label: "측광 모드", value: str(e.MeteringMode)! } : null,
      str(e.Flash) ? { label: "플래시", value: str(e.Flash)! } : null,
      str(e.WhiteBalance) ? { label: "화이트밸런스", value: str(e.WhiteBalance)! } : null,
    ]),
    section("일시", [
      fmtDate(e.DateTimeOriginal) ? { label: "촬영 일시", value: fmtDate(e.DateTimeOriginal)! } : null,
      fmtDate(e.CreateDate) ? { label: "디지털화 일시", value: fmtDate(e.CreateDate)! } : null,
      fmtDate(e.ModifyDate) ? { label: "수정 일시", value: fmtDate(e.ModifyDate)! } : null,
    ]),
    section("GPS", [
      lat != null && lng != null
        ? {
            label: "좌표",
            value: (
              <a
                href={`https://www.google.com/maps?q=${lat},${lng}`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-primary underline"
              >
                <MapPin className="h-3 w-3" />
                {lat.toFixed(6)}, {lng.toFixed(6)}
              </a>
            ),
          }
        : null,
      fmtNum(e.GPSAltitude, 1, " m") ? { label: "고도", value: fmtNum(e.GPSAltitude, 1, " m")! } : null,
    ]),
    section("기타", [
      str(e.Orientation) ? { label: "방향(Orientation)", value: str(e.Orientation)! } : null,
      str(e.ColorSpace) ? { label: "색 공간", value: str(e.ColorSpace)! } : null,
      fmtNum(e.XResolution, 0) && fmtNum(e.YResolution, 0)
        ? { label: "해상도(DPI)", value: `${fmtNum(e.XResolution, 0)} × ${fmtNum(e.YResolution, 0)}` }
        : null,
    ]),
  ]

  const visible = sections.filter((s): s is Section => s != null)
  const hasExif = exif != null && Object.keys(exif).length > 0

  return (
    <div className="space-y-4">
      {loading && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" /> EXIF 분석 중…
        </div>
      )}

      {visible.map((s) => (
        <section key={s.title} className="space-y-1">
          <h4 className="text-sm font-semibold text-black">{s.title}</h4>
          <table className="w-full table-fixed border-collapse">
            <colgroup>
              <col style={{ width: 100 }} />
              <col />
            </colgroup>
            <tbody>
              {s.rows.map((r) => (
                <tr key={r.label}>
                  <td className="border border-border bg-muted/20 px-2 py-1 align-middle text-sm text-black">
                    {r.label}
                  </td>
                  <td className="border border-border px-2 py-1 text-sm text-black">{r.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}

      {!loading && !hasExif && (
        <p className="rounded-md bg-muted/40 px-2 py-2 text-xs leading-relaxed text-muted-foreground">
          이 이미지에는 EXIF 정보가 없습니다. PNG·스크린샷·웹에서 가공·재저장된 이미지는 카메라/GPS
          정보가 제거되는 경우가 많습니다. (DSLR·스마트폰 원본 JPEG 에는 보통 포함됩니다.)
        </p>
      )}
    </div>
  )
}
