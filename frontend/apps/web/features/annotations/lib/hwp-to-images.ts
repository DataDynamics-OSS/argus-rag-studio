// HWP/HWPX → 페이지별 PNG 변환(클라이언트). s3browse 미리보기와 동일한 rhwp(@rhwp/core, WASM)
// 엔진을 쓴다.
//
// 렌더 방식: renderPageSvg 로 페이지를 SVG 로 받은 뒤 <img> 로 로드해 canvas 에 래스터화한다.
// renderPageToCanvas 를 직접 쓰면 WASM 이 임베디드 이미지를 new Image()+src 로 비동기 로드하는데
// 그리는 시점엔 image.complete=false 라서 그림만 누락된다(텍스트/도형은 정상). SVG 는 이미지를
// data URI 로 임베드하므로 브라우저가 <img> 로드 완료를 기다린 뒤 그리면 그림까지 보존된다.

export interface RenderedHwpPage {
  blob: Blob
  width: number
  height: number
}

// WASM init·텍스트 측정 콜백은 비싸므로 모듈 스코프에서 1회만 준비한다.
let initPromise: Promise<unknown> | null = null

/** rhwp 텍스트 레이아웃에 필요한 전역 텍스트 폭 측정 콜백 등록(권장, 멱등). */
function ensureMeasureText(): void {
  const g = globalThis as unknown as {
    measureTextWidth?: (font: string, text: string) => number
  }
  if (g.measureTextWidth) return
  let ctx: CanvasRenderingContext2D | null = null
  let lastFont = ""
  g.measureTextWidth = (font: string, text: string) => {
    if (!ctx) ctx = document.createElement("canvas").getContext("2d")
    if (!ctx) return 0
    if (font !== lastFont) {
      ctx.font = font
      lastFont = font
    }
    return ctx.measureText(text).width
  }
}

/** 페이지 SVG 문자열을 지정 배율로 PNG 로 래스터화한다(임베디드 이미지 포함). */
async function rasterizeSvg(svg: string, scale: number): Promise<RenderedHwpPage> {
  // 기준 크기 산출 — viewBox(문서 사용자 단위) 우선, 없으면 width/height 숫자부.
  const root = new DOMParser().parseFromString(svg, "image/svg+xml").documentElement
  let baseW = 0
  let baseH = 0
  const vb = root.getAttribute("viewBox")
  if (vb) {
    const p = vb.split(/[\s,]+/).map(Number)
    if (p.length === 4 && p[2]! > 0 && p[3]! > 0) {
      baseW = p[2]!
      baseH = p[3]!
    }
  }
  if (!baseW || !baseH) {
    baseW = parseFloat(root.getAttribute("width") || "") || 794
    baseH = parseFloat(root.getAttribute("height") || "") || 1123
  }
  const w = Math.max(1, Math.round(baseW * scale))
  const h = Math.max(1, Math.round(baseH * scale))
  // 해당 해상도로 디코드되도록 SVG 루트 width/height 를 스케일된 px 로 지정(viewBox 보존).
  root.setAttribute("width", String(w))
  root.setAttribute("height", String(h))
  if (!vb) root.setAttribute("viewBox", `0 0 ${baseW} ${baseH}`)
  const serialized = new XMLSerializer().serializeToString(root)
  const url = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(serialized)

  const img = new Image()
  img.width = w
  img.height = h
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve()
    img.onerror = () => reject(new Error("페이지 SVG 를 이미지로 불러오지 못했습니다."))
    img.src = url
  })
  // 일부 브라우저에서 onload 후에도 디코드를 보장(임베디드 이미지 포함).
  if (img.decode) {
    try {
      await img.decode()
    } catch {
      /* decode 미지원/실패는 무시 — onload 로 충분 */
    }
  }

  const canvas = document.createElement("canvas")
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext("2d")
  if (!ctx) throw new Error("canvas 2D 컨텍스트를 만들 수 없습니다.")
  ctx.fillStyle = "#ffffff" // 투명 배경 대비 흰 배경
  ctx.fillRect(0, 0, w, h)
  ctx.drawImage(img, 0, 0, w, h)

  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("페이지 PNG 인코딩에 실패했습니다."))),
      "image/png"
    )
  })
  return { blob, width: w, height: h }
}

/**
 * HWP/HWPX 바이트를 페이지별 PNG 로 변환한다.
 * @param scale 렌더 배율(해상도). 기본 2.0 — 라벨링에 충분한 선명도.
 */
export async function renderHwpToPngs(
  bytes: ArrayBuffer,
  opts?: {
    scale?: number
    onProgress?: (done: number, total: number) => void
    signal?: AbortSignal
  }
): Promise<RenderedHwpPage[]> {
  const scale = opts?.scale ?? 2.0
  ensureMeasureText()
  // HWP 를 실제로 변환할 때만 5.5MB WASM 을 동적 로드(번들 절감) — 미리보기와 동일 패턴.
  const mod = await import("@rhwp/core")
  initPromise ??= mod.default({ module_or_path: "/rhwp_bg.wasm" })
  await initPromise

  const doc = new mod.HwpDocument(new Uint8Array(bytes))
  const count = doc.pageCount()
  const pages: RenderedHwpPage[] = []
  for (let i = 0; i < count; i++) {
    if (opts?.signal?.aborted) throw new DOMException("Aborted", "AbortError")
    const svg = doc.renderPageSvg(i)
    pages.push(await rasterizeSvg(svg, scale))
    opts?.onProgress?.(i + 1, count)
  }
  return pages
}
