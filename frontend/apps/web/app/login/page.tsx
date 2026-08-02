// 로그인 페이지 — username/password 폼. 백엔드 auth_type 에 따라 로컬 JWT 또는 Keycloak
// 으로 검증된다(프론트는 동일 흐름). authType 을 안내 문구로 노출한다.
"use client"

import { useEffect, useState, type FormEvent } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import { useAuth } from "@/features/auth"

export default function LoginPage() {
  const router = useRouter()
  const { login, isAuthenticated, user, authType } = useAuth()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (isAuthenticated) {
      router.replace(
        user?.must_change_password ? "/change-password-required" : "/dashboard"
      )
    }
  }, [isAuthenticated, user, router])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError("")
    setLoading(true)
    try {
      const userInfo = await login(username, password)
      router.replace(
        userInfo.must_change_password ? "/change-password-required" : "/dashboard"
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl font-bold">Argus RAG Studio</CardTitle>
          <CardDescription>
            {authType === "keycloak"
              ? "Keycloak 계정으로 로그인"
              : "계정으로 로그인하세요"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                type="text"
                placeholder="아이디를 입력하세요"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoFocus
                autoComplete="username"
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="비밀번호를 입력하세요"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "로그인 중..." : "로그인"}
            </Button>
          </form>
        </CardContent>
        <div className="border-t border-border px-6 py-3 -mb-6">
          <p className="text-center text-xs text-muted-foreground">
            Copyright © {new Date().getFullYear()} Data Dynamics Inc.
          </p>
        </div>
      </Card>
    </div>
  )
}
