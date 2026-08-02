// SPDX-License-Identifier: Apache-2.0
// Argus HWP 렌더 서비스 — 헤드리스 브라우저(@rhwp/core, WASM)로 HWP/HWPX 페이지를 렌더한다.
//
// 엔드포인트(JSON):
//   GET  /health                      → {status}
//   GET  /stats                       → 런타임 메트릭(요청 수·브라우저 상태)
//   POST /pages-text {data_b64}        → {page_count, page_texts:[...]}  (매칭용, 가벼움)
//   POST /render     {data_b64,page,scale} → {page, page_count, image_b64, width, height}
//
// 워밋업: 기동 시 브라우저 1개 + render.html 페이지를 띄워 둔다(요청마다 재기동 안 함).
// rhwp WASM 은 페이지 내 단일 컨텍스트라 evaluate 호출을 직렬화한다.
const http = require("http")
const fs = require("fs")
const path = require("path")
const { chromium } = require("playwright-core")

const PORT = parseInt(process.env.HWP_RENDER_PORT || "8085", 10)
const HOST = process.env.HWP_RENDER_HOST || "0.0.0.0"
// 버전 — /health·/stats 로 노출(모니터링 카드 표시용). rhwp 는 실제 렌더 엔진 버전.
const VERSION = require("./package.json").version
const RHWP_VERSION = (() => {
  try {
    return require("@rhwp/core/package.json").version
  } catch {
    return null
  }
})()
// chromium 실행 경로 — CHROMIUM_PATH env 우선, 없으면 흔한 시스템 경로 탐색.
const CHROMIUM_PATH = (() => {
  if (process.env.CHROMIUM_PATH) return process.env.CHROMIUM_PATH
  const cands = [
    "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
    "/snap/chromium/current/usr/lib/chromium-browser/chrome",
  ]
  for (const c of cands) { try { if (fs.existsSync(c)) return c } catch (e) {} }
  return undefined // playwright-core 기본(번들 chromium) 시도
})()
const STATIC = path.join(__dirname, "static")
const CONTENT = { ".html": "text/html", ".js": "text/javascript", ".wasm": "application/wasm" }

const metrics = { started: Date.now(), requests: 0, errors: 0, renders: 0 }
let browser = null
let page = null
let chain = Promise.resolve() // evaluate 직렬화

async function ensureBrowser() {
  if (page && !page.isClosed()) return page
  browser = await chromium.launch({
    executablePath: CHROMIUM_PATH,
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
  })
  const ctx = await browser.newContext()
  page = await ctx.newPage()
  // 정적 자산을 라우트로 직접 제공(외부 http 서버 불필요).
  await page.route("**/*", (route) => {
    const u = new URL(route.request().url())
    const name = u.pathname === "/" ? "/render.html" : u.pathname
    const file = path.join(STATIC, path.basename(name))
    if (fs.existsSync(file)) {
      route.fulfill({ status: 200, contentType: CONTENT[path.extname(file)] || "application/octet-stream", body: fs.readFileSync(file) })
    } else route.fulfill({ status: 404, body: "not found" })
  })
  await page.goto("https://rhwp.local/render.html", { waitUntil: "load" })
  await page.waitForFunction("window.__ready === true", { timeout: 30000 })
  console.log("[hwp-render] 브라우저 워밋업 완료")
  return page
}

function runExclusive(fn) {
  const next = chain.then(fn, fn)
  chain = next.catch(() => {}) // 체인은 끊기지 않게
  return next
}

async function readJson(req) {
  const chunks = []
  for await (const c of req) chunks.push(c)
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}")
}

const server = http.createServer(async (req, res) => {
  metrics.requests++
  const send = (code, obj) => { res.writeHead(code, { "Content-Type": "application/json" }); res.end(JSON.stringify(obj)) }
  try {
    if (req.method === "GET" && req.url === "/health")
      return send(200, { status: "ok", version: VERSION, rhwp: RHWP_VERSION })
    if (req.method === "GET" && req.url === "/stats")
      return send(200, {
        ...metrics,
        version: VERSION,
        rhwp: RHWP_VERSION,
        uptime_seconds: Math.round((Date.now() - metrics.started) / 1000),
        browser_up: !!(page && !page.isClosed()),
      })

    if (req.method === "POST" && (req.url === "/pages-text" || req.url === "/render")) {
      const body = await readJson(req)
      if (!body.data_b64) return send(400, { error: "data_b64 필요" })
      const p = await ensureBrowser()
      const result = await runExclusive(async () => {
        if (req.url === "/pages-text")
          return await p.evaluate(async (b) => await window.rhwpInfo(b), body.data_b64)
        const r = await p.evaluate(async (a) => await window.rhwpRender(a.b, a.page, a.scale),
          { b: body.data_b64, page: body.page || 0, scale: body.scale || 1.5 })
        return { page: r.page, page_count: r.page_count, width: r.width, height: r.height, image_b64: r.dataurl.split(",")[1] }
      })
      if (req.url === "/render") metrics.renders++
      return send(200, result)
    }
    send(404, { error: "not found" })
  } catch (e) {
    metrics.errors++
    console.error("[hwp-render] error:", e.message)
    send(500, { error: String(e.message || e).slice(0, 300) })
  }
})

server.listen(PORT, HOST, () => console.log(`[hwp-render] listening on ${HOST}:${PORT}`))
ensureBrowser().catch((e) => console.error("[hwp-render] 워밋업 실패(첫 요청 때 재시도):", e.message))
for (const sig of ["SIGTERM", "SIGINT"]) process.on(sig, async () => { try { await browser?.close() } catch (e) {} process.exit(0) })
