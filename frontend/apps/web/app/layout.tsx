import "@workspace/ui/globals.css"
import type { Metadata } from "next"
import localFont from "next/font/local"
import { Toaster } from "sonner"
import { ThemeProvider } from "@/components/theme-provider"
import { AuthProviderWrapper } from "@/components/auth-provider-wrapper"

// 본문 — Pretendard(라틴·한글 통합). globals.css 의 --font-sans 가 참조.
const pretendard = localFont({
  src: "./fonts/PretendardVariable.woff2",
  variable: "--font-pretendard",
  display: "swap",
  weight: "45 920",
})

// 한글 폴백 — Noto Sans KR.
const notoSansKR = localFont({
  src: [
    { path: "./fonts/NotoSansKR-400.woff2", weight: "400", style: "normal" },
    { path: "./fonts/NotoSansKR-500.woff2", weight: "500", style: "normal" },
    { path: "./fonts/NotoSansKR-700.woff2", weight: "700", style: "normal" },
  ],
  variable: "--font-noto-sans-kr",
  display: "swap",
})

// 헤더/그리드 헤더용 좁은 글꼴 — Roboto Condensed (--font-display).
const robotoCondensed = localFont({
  src: "./fonts/RobotoCondensed-Variable.woff2",
  variable: "--font-roboto-condensed",
  display: "swap",
  weight: "100 900",
})

// 코드/모노스페이스 — D2Coding (--font-mono).
const d2coding = localFont({
  src: [
    { path: "./fonts/D2Coding-Regular.woff2", weight: "400", style: "normal" },
    { path: "./fonts/D2Coding-Bold.woff2", weight: "700", style: "normal" },
  ],
  variable: "--font-d2coding",
  display: "swap",
})

export const metadata: Metadata = {
  title: "Argus RAG Studio",
  description: "Retrieval-Augmented Generation platform",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="ko"
      suppressHydrationWarning
      className={`${pretendard.variable} ${notoSansKR.variable} ${robotoCondensed.variable} ${d2coding.variable}`}
    >
      <body className="min-h-screen bg-background text-foreground text-sm font-sans antialiased">
        <ThemeProvider>
          <AuthProviderWrapper>{children}</AuthProviderWrapper>
          <Toaster richColors position="top-center" />
        </ThemeProvider>
      </body>
    </html>
  )
}
