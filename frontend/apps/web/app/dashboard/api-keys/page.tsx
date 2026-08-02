// API 키 — 외부 시스템 연동용 서비스 계정. admin 전용.
// 발급된 키로 RAG 백엔드(search/query/chat)를 X-API-Key 또는 Authorization: Bearer 로
// 프로그래밍 호출할 수 있다. 평문 키는 발급 직후 1회만 노출되므로 그 자리에서 복사해야 한다.
"use client"

import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Check, Copy, KeyRound, Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import { Textarea } from "@workspace/ui/components/textarea"
import { Badge } from "@workspace/ui/components/badge"
import { Switch } from "@workspace/ui/components/switch"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@workspace/ui/components/alert-dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { DashboardHeader } from "@/components/dashboard-header"
import { useAuth } from "@/features/auth"
import {
  createApiKey,
  deleteApiKey,
  fetchApiKeys,
  updateApiKey,
  type ApiKey,
} from "@/features/apikeys/api"
import { formatDateTime } from "@/lib/format"

const ROLE_OPTIONS = [
  { value: "argus-user", label: "User (검색·질의·챗 호출)" },
  { value: "argus-superuser", label: "Superuser" },
  { value: "argus-admin", label: "Admin (전체 권한 — 주의)" },
] as const

const ROLE_LABELS: Record<string, string> = {
  "argus-admin": "Admin",
  "argus-superuser": "Superuser",
  "argus-user": "User",
}

export default function ApiKeysPage() {
  const { user } = useAuth()
  const isAdmin = user?.is_admin ?? false

  const [keys, setKeys] = useState<ApiKey[]>([])
  const [loading, setLoading] = useState(true)

  // 발급 다이얼로그
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [role, setRole] = useState<string>("argus-user")
  const [expiresInDays, setExpiresInDays] = useState("")
  const [submitting, setSubmitting] = useState(false)

  // 발급 결과(평문 키 1회 노출) 다이얼로그
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  // 삭제 확인
  const [deleteTarget, setDeleteTarget] = useState<ApiKey | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setKeys(await fetchApiKeys())
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "API 키 조회 실패")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isAdmin) void refresh()
  }, [isAdmin, refresh])

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    if (!name.trim()) {
      toast.error("이름을 입력하세요.")
      return
    }
    setSubmitting(true)
    try {
      const days = expiresInDays.trim() ? Number(expiresInDays) : undefined
      const created = await createApiKey({
        name: name.trim(),
        description: description.trim() || undefined,
        role,
        expires_in_days: days,
      })
      setCreateOpen(false)
      setName("")
      setDescription("")
      setRole("argus-user")
      setExpiresInDays("")
      setCreatedKey(created.api_key)
      setCopied(false)
      void refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "API 키 발급 실패")
    } finally {
      setSubmitting(false)
    }
  }

  async function handleToggle(key: ApiKey, enabled: boolean) {
    try {
      await updateApiKey(key.id, { enabled })
      setKeys((prev) => prev.map((k) => (k.id === key.id ? { ...k, enabled } : k)))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "상태 변경 실패")
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return
    try {
      await deleteApiKey(deleteTarget.id)
      toast.success("API 키가 폐기되었습니다.")
      setDeleteTarget(null)
      void refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "API 키 폐기 실패")
    }
  }

  async function copyKey() {
    if (!createdKey) return
    try {
      await navigator.clipboard.writeText(createdKey)
      setCopied(true)
      toast.success("클립보드에 복사되었습니다.")
    } catch {
      toast.error("복사 실패 — 키를 직접 선택해 복사하세요.")
    }
  }

  if (!isAdmin) {
    return (
      <>
        <DashboardHeader title="API 키" />
        <div className="p-6 text-sm text-muted-foreground">
          API 키 관리는 관리자(admin)만 사용할 수 있습니다.
        </div>
      </>
    )
  }

  return (
    <>
      <DashboardHeader title="API 키" />
      <div className="flex flex-col gap-6 p-6">
        {/* 사용 안내 */}
        <div className="rounded-lg border bg-muted/30 p-4 text-sm">
          <p className="font-medium">외부 시스템 연동용 서비스 계정</p>
          <p className="mt-1 text-muted-foreground">
            발급된 키로 RAG 백엔드의 검색·질의·챗 API 를 프로그래밍 방식으로 호출할 수 있습니다.
            요청 헤더에 <code className="rounded bg-muted px-1">X-API-Key: &lt;키&gt;</code> 또는
            <code className="ml-1 rounded bg-muted px-1">Authorization: Bearer &lt;키&gt;</code> 를 넣으세요.
            평문 키는 발급 직후 1회만 표시됩니다.
          </p>
          <pre className="mt-3 overflow-x-auto rounded bg-background p-3 text-xs leading-relaxed">{`curl -X POST https://<host>/api/v1/collections/<id>/query \\
  -H "X-API-Key: argus_sk_..." \\
  -H "Content-Type: application/json" \\
  -d '{"query": "질문 내용"}'`}</pre>
        </div>

        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            발급된 키 {keys.length}개
          </p>
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-1 h-4 w-4" /> API 키 발급
          </Button>
        </div>

        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>이름</TableHead>
                <TableHead>키</TableHead>
                <TableHead>역할</TableHead>
                <TableHead>활성</TableHead>
                <TableHead>마지막 사용</TableHead>
                <TableHead>만료</TableHead>
                <TableHead>발급일</TableHead>
                <TableHead className="text-right">작업</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={8} className="py-8 text-center text-muted-foreground">
                    불러오는 중…
                  </TableCell>
                </TableRow>
              ) : keys.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="py-8 text-center text-muted-foreground">
                    발급된 API 키가 없습니다.
                  </TableCell>
                </TableRow>
              ) : (
                keys.map((k) => (
                  <TableRow key={k.id}>
                    <TableCell className="font-medium">
                      {k.name}
                      {k.description && (
                        <p className="text-xs text-muted-foreground">{k.description}</p>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {k.key_prefix}…
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">{ROLE_LABELS[k.role_id] ?? k.role_id}</Badge>
                    </TableCell>
                    <TableCell>
                      <Switch
                        checked={k.enabled}
                        onCheckedChange={(v) => void handleToggle(k, v)}
                      />
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {k.last_used_at ? formatDateTime(k.last_used_at) : "—"}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {k.expires_at ? formatDateTime(k.expires_at) : "무기한"}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatDateTime(k.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setDeleteTarget(k)}
                        aria-label="폐기"
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* 발급 다이얼로그 */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <form onSubmit={handleCreate}>
            <DialogHeader>
              <DialogTitle>API 키 발급</DialogTitle>
              <DialogDescription>
                외부 시스템 연동용 키를 발급합니다. 평문 키는 발급 직후 1회만 표시됩니다.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-4 py-4">
              <div className="flex flex-col gap-2">
                <Label htmlFor="ak-name">이름</Label>
                <Input
                  id="ak-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="예: 사내 챗봇 연동"
                  autoFocus
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="ak-desc">설명 (선택)</Label>
                <Textarea
                  id="ak-desc"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="용도·소유 시스템 등"
                  rows={2}
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label>역할(권한)</Label>
                <Select value={role} onValueChange={setRole}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ROLE_OPTIONS.map((r) => (
                      <SelectItem key={r.value} value={r.value}>
                        {r.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="ak-exp">만료(일) — 비우면 무기한</Label>
                <Input
                  id="ak-exp"
                  type="number"
                  min={1}
                  max={3650}
                  value={expiresInDays}
                  onChange={(e) => setExpiresInDays(e.target.value)}
                  placeholder="예: 90"
                />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setCreateOpen(false)}>
                취소
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? "발급 중…" : "발급"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 발급 결과 — 평문 키 1회 노출 */}
      <Dialog open={createdKey !== null} onOpenChange={(o) => !o && setCreatedKey(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <KeyRound className="h-5 w-5" /> API 키가 발급되었습니다
            </DialogTitle>
            <DialogDescription>
              이 키는 지금만 표시됩니다. 안전한 곳에 보관하세요. 창을 닫으면 다시 볼 수 없습니다.
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2 py-2">
            <code className="flex-1 overflow-x-auto rounded bg-muted px-3 py-2 font-mono text-sm">
              {createdKey}
            </code>
            <Button variant="outline" size="icon" onClick={copyKey} aria-label="복사">
              {copied ? <Check className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4" />}
            </Button>
          </div>
          <DialogFooter>
            <Button onClick={() => setCreatedKey(null)}>확인</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 삭제 확인 */}
      <AlertDialog open={deleteTarget !== null} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>API 키를 폐기할까요?</AlertDialogTitle>
            <AlertDialogDescription>
              <span className="font-medium">{deleteTarget?.name}</span> 키를 영구 삭제합니다. 이 키로
              연동된 외부 시스템은 즉시 인증에 실패합니다. 되돌릴 수 없습니다.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>취소</AlertDialogCancel>
            <AlertDialogAction onClick={() => void handleDelete()}>폐기</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
