import path from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))

/** @type {import('next').NextConfig} */
const nextConfig = {
  transpilePackages: ["@workspace/ui"],
  // 워크스페이스 루트 명시 — 상위 디렉터리(홈 등)의 다른 lockfile 로 루트가 오추론되는 것 방지.
  turbopack: {
    root: path.join(__dirname, "../.."),
  },
  logging: {
    fetches: {
      fullUrl: true,
    },
  },
  // 개발 서버 cross-origin 허용 — 환경변수로 오버라이드 가능.
  allowedDevOrigins: process.env.ALLOWED_DEV_ORIGINS
    ? process.env.ALLOWED_DEV_ORIGINS.split(",")
    : ["localhost", "192.0.2.*", "192.168.0.*"],
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "Access-Control-Allow-Origin", value: "*" },
          { key: "Access-Control-Allow-Methods", value: "GET, POST, PUT, PATCH, DELETE, OPTIONS" },
          { key: "Access-Control-Allow-Headers", value: "Content-Type, Authorization" },
        ],
      },
    ]
  },
}

export default nextConfig
