// 강제 비밀번호 변경 화면 — must_change_password=true 계정(기본 admin/admin 등)이
// 비밀번호를 바꾸기 전까지 머무는 게이트. 변경 성공 시 백엔드가 새 토큰을 재발급하고,
// applyTokens 로 세션을 교체하면 게이트가 즉시 풀린다.
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
import { toast } from "sonner"
import { useAuth } from "@/features/auth"
import { changePassword } from "@/features/auth/api"

export default function ChangePasswordRequiredPage() {
  const router = useRouter()
  const { accessToken, applyTokens, isAuthenticated, isLoading } = useAuth()
  const [current, setCurrent] = useState("")
  const [next, setNext] = useState("")
  const [confirm, setConfirm] = useState("")
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace("/login")
  }, [isLoading, isAuthenticated, router])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (next !== confirm) {
      toast.error("새 비밀번호가 일치하지 않습니다.")
      return
    }
    if (!accessToken) return
    setLoading(true)
    try {
      const tokens = await changePassword(accessToken, current, next)
      await applyTokens(tokens)
      toast.success("비밀번호가 변경되었습니다.")
      router.replace("/dashboard")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "비밀번호 변경 실패")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <CardTitle className="text-xl font-bold">비밀번호 변경 필요</CardTitle>
          <CardDescription>계속 이용하려면 비밀번호를 변경하세요.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="current">현재 비밀번호</Label>
              <Input id="current" type="password" value={current}
                onChange={(e) => setCurrent(e.target.value)} required autoFocus />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="next">새 비밀번호</Label>
              <Input id="next" type="password" value={next}
                onChange={(e) => setNext(e.target.value)} required minLength={4} />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="confirm">새 비밀번호 확인</Label>
              <Input id="confirm" type="password" value={confirm}
                onChange={(e) => setConfirm(e.target.value)} required minLength={4} />
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "변경 중..." : "비밀번호 변경"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
