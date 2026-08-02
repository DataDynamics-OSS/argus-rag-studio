// 자동 수집(소스 워치) 탭 — 소스+폴더+주기를 등록하면 시스템이 주기 스캔해 자동 인테이크.
// 백엔드 app/sourcewatch, 설계 design/source-watch.md. 수동 드롭존(인테이크)의 무인화.
"use client"

import { useCallback, useEffect, useState, type FormEvent } from "react"
import { AlertTriangle, FolderSearch, History, Pencil, Play, Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"

import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@workspace/ui/components/alert-dialog"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { Switch } from "@workspace/ui/components/switch"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@workspace/ui/components/tooltip"

import { useAuth } from "@/features/auth"
import { SourcePathPicker } from "@/features/storage-sources/components/source-path-picker"
import {
  createWatch,
  deleteWatch,
  listSources,
  listWatchRuns,
  listWatches,
  runWatchNow,
  updateWatch,
  type SourceWatch,
  type SourceWatchRun,
} from "@/features/storage-sources/api"
import type { StorageSource } from "@/features/storage-sources/data/schema"

const COUNT_LABELS: Record<string, string> = {
  routed: "배분", duplicate: "중복", no_route: "미배분", failed: "실패", skipped: "스킵",
}

function fmtTime(iso?: string | null): string {
  if (!iso) return ""
  return new Date(iso).toLocaleString()
}

function fmtInterval(s: number): string {
  if (s % 3600 === 0) return `${s / 3600}시간`
  if (s % 60 === 0) return `${s / 60}분`
  return `${s}초`
}

function CountsInline({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts).filter(([, v]) => v > 0)
  if (entries.length === 0) return <span className="text-muted-foreground">변화 없음</span>
  return (
    <span>
      {entries.map(([k, v], i) => (
        <span key={k}>
          {i > 0 && " · "}
          {COUNT_LABELS[k] ?? k} {v}
        </span>
      ))}
    </span>
  )
}

const BLANK = { name: "", source_id: "", prefix: "", recursive: true, interval: "300", enabled: true }
type FormState = typeof BLANK

export function WatchesTab() {
  const { user } = useAuth()
  const canManage = !!(user?.is_admin || user?.is_superuser)
  const [watches, setWatches] = useState<SourceWatch[]>([])
  const [sources, setSources] = useState<StorageSource[]>([])
  const [loading, setLoading] = useState(true)
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<SourceWatch | null>(null)
  const [form, setForm] = useState<FormState>(BLANK)
  const [submitting, setSubmitting] = useState(false)
  const [deleting, setDeleting] = useState<SourceWatch | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [runsOf, setRunsOf] = useState<SourceWatch | null>(null)
  const [runs, setRuns] = useState<SourceWatchRun[]>([])

  const load = useCallback(async () => {
    try {
      const [w, s] = await Promise.all([listWatches(), listSources()])
      setWatches(w)
      setSources(s)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    const t = setInterval(() => void load(), 15_000) // 워처 tick 과 동일 주기로 상태 갱신
    return () => clearInterval(t)
  }, [load])

  function openNew() {
    setEditing(null)
    setForm({ ...BLANK, source_id: sources[0]?.source_id ?? "" })
    setEditOpen(true)
  }

  function openEdit(w: SourceWatch) {
    setEditing(w)
    setForm({
      name: w.name, source_id: w.source_id, prefix: w.prefix,
      recursive: w.recursive, interval: String(w.interval_seconds), enabled: w.enabled,
    })
    setEditOpen(true)
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const interval = Number(form.interval)
    if (!Number.isInteger(interval) || interval < 60) {
      toast.error("주기는 60초 이상이어야 합니다.")
      return
    }
    setSubmitting(true)
    try {
      if (editing) {
        await updateWatch(editing.watch_id, {
          name: form.name.trim(), prefix: form.prefix.trim(),
          recursive: form.recursive, interval_seconds: interval, enabled: form.enabled,
        })
        toast.success("워치 수정됨")
      } else {
        await createWatch({
          source_id: form.source_id, name: form.name.trim(), prefix: form.prefix.trim(),
          recursive: form.recursive, interval_seconds: interval, enabled: form.enabled,
        })
        toast.success("워치 등록됨 — 곧 첫 스캔이 실행됩니다")
      }
      setEditOpen(false)
      await load()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "저장 실패")
    } finally {
      setSubmitting(false)
    }
  }

  async function toggleEnabled(w: SourceWatch) {
    try {
      await updateWatch(w.watch_id, { enabled: !w.enabled })
      await load()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "변경 실패")
    }
  }

  async function runNow(w: SourceWatch) {
    try {
      await runWatchNow(w.watch_id)
      toast.success(`${w.name} — 다음 tick(15초 내)에 실행됩니다`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "실행 요청 실패")
    }
  }

  async function confirmDelete() {
    if (!deleting) return
    try {
      await deleteWatch(deleting.watch_id)
      toast.success("워치 삭제됨")
      setDeleting(null)
      await load()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "삭제 실패")
    }
  }

  async function openRuns(w: SourceWatch) {
    setRunsOf(w)
    try {
      setRuns(await listWatchRuns(w.watch_id))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "이력 조회 실패")
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <span className="text-sm">
          소스의 약속된 폴더(드롭존)를 주기 스캔해 새 문서를 자동 인테이크합니다 — 라우팅
          정책으로 컬렉션 배분, 처리된 파일은 증분 캐시로 건너뜁니다.
        </span>
        {canManage && (
          <Button size="sm" onClick={openNew} disabled={sources.length === 0}>
            <Plus className="size-4" /> 워치 등록
          </Button>
        )}
      </div>

      <div className="rounded-md border">
        <TooltipProvider delayDuration={300}>
          <Table className="text-sm">
            <TableHeader>
              <TableRow>
                <TableHead className="w-14 text-center text-sm">사용</TableHead>
                <TableHead className="text-sm">이름</TableHead>
                <TableHead className="text-sm">소스 / 폴더</TableHead>
                <TableHead className="w-20 text-center text-sm">주기</TableHead>
                <TableHead className="text-sm">마지막 실행</TableHead>
                <TableHead className="text-sm">다음 실행</TableHead>
                {canManage && <TableHead className="w-32 text-center text-sm">동작</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {watches.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={canManage ? 7 : 6} className="h-24 text-center text-sm text-muted-foreground">
                    {loading ? "불러오는 중…" : "등록된 워치가 없습니다 — 소스를 먼저 등록한 뒤 워치를 추가하세요."}
                  </TableCell>
                </TableRow>
              ) : (
                watches.map((w) => (
                  <TableRow key={w.watch_id} className={w.enabled ? undefined : "opacity-55"}>
                    <TableCell className="text-center">
                      <Switch checked={w.enabled} onCheckedChange={() => void toggleEnabled(w)} disabled={!canManage} />
                    </TableCell>
                    <TableCell className="font-medium">{w.name}</TableCell>
                    <TableCell>
                      <span className="font-mono text-sm">
                        {w.source_name}
                        {w.prefix ? ` / ${w.prefix}` : " / (루트)"}
                        {w.recursive ? "" : "  (하위 폴더 제외)"}
                      </span>
                    </TableCell>
                    <TableCell className="text-center">{fmtInterval(w.interval_seconds)}</TableCell>
                    <TableCell>
                      {w.last_status == null ? (
                        <span className="text-muted-foreground">미실행</span>
                      ) : w.last_status === "ok" ? (
                        <span className="inline-flex flex-wrap items-center gap-1.5">
                          <Badge variant="success">정상</Badge>
                          <span className="text-muted-foreground">{fmtTime(w.last_run_at)}</span>
                          <CountsInline counts={w.last_counts} />
                        </span>
                      ) : (
                        <span className="inline-flex flex-wrap items-center gap-1.5">
                          <Badge variant="destructive" title={w.last_error ?? undefined} className="cursor-help">
                            오류 {w.consecutive_failures > 1 ? `×${w.consecutive_failures}` : ""}
                          </Badge>
                          <span className="text-muted-foreground">{fmtTime(w.last_run_at)}</span>
                          <span className="inline-flex items-center gap-1 text-destructive">
                            <AlertTriangle className="size-3" /> {w.last_error}
                          </span>
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {w.enabled ? fmtTime(w.next_run_at) : ""}
                    </TableCell>
                    {canManage && (
                      <TableCell className="text-center">
                        <div className="flex justify-center gap-0.5">
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button variant="ghost" size="icon" className="size-7" disabled={!w.enabled} onClick={() => void runNow(w)}>
                                <Play className="size-4" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>지금 실행</TooltipContent>
                          </Tooltip>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button variant="ghost" size="icon" className="size-7" onClick={() => void openRuns(w)}>
                                <History className="size-4" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>실행 이력</TooltipContent>
                          </Tooltip>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button variant="ghost" size="icon" className="size-7" onClick={() => openEdit(w)}>
                                <Pencil className="size-4" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>수정</TooltipContent>
                          </Tooltip>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button variant="ghost" size="icon" className="size-7" onClick={() => setDeleting(w)}>
                                <Trash2 className="size-4 text-destructive" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>삭제</TooltipContent>
                          </Tooltip>
                        </div>
                      </TableCell>
                    )}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TooltipProvider>
      </div>

      {/* 등록/수정 */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="sm:max-w-lg">
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <DialogHeader>
              <DialogTitle>{editing ? "워치 수정" : "워치 등록"}</DialogTitle>
              <DialogDescription>
                등록 즉시 첫 스캔이 실행되고, 이후 주기마다 새 파일만 자동 인테이크합니다.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-1.5">
              <Label className="text-sm">이름</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="예: 계약서 드롭존" />
            </div>
            <div className="flex gap-3">
              <div className="flex flex-1 flex-col gap-1.5">
                <Label className="text-sm">소스</Label>
                <Select
                  value={form.source_id}
                  onValueChange={(v) => setForm({ ...form, source_id: v })}
                  disabled={!!editing}
                >
                  <SelectTrigger><SelectValue placeholder="소스 선택" /></SelectTrigger>
                  <SelectContent>
                    {sources.map((s) => (
                      <SelectItem key={s.source_id} value={s.source_id}>{s.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex w-32 flex-col gap-1.5">
                <Label className="text-sm">주기(초)</Label>
                <Input inputMode="numeric" value={form.interval} onChange={(e) => setForm({ ...form, interval: e.target.value })} placeholder="300" />
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-sm">폴더(prefix) — 비우면 소스 루트</Label>
              <div className="flex gap-2">
                <Input className="flex-1 font-mono text-sm" value={form.prefix} onChange={(e) => setForm({ ...form, prefix: e.target.value })} placeholder="예: drop/contracts" />
                <Button type="button" variant="outline" size="icon" title="폴더 찾아보기" disabled={!form.source_id} onClick={() => setPickerOpen(true)}>
                  <FolderSearch className="size-4" />
                </Button>
              </div>
            </div>
            <div className="flex items-center gap-6 text-sm">
              <label className="flex items-center gap-2">
                <Switch checked={form.recursive} onCheckedChange={(v) => setForm({ ...form, recursive: v })} /> 하위 폴더 포함
              </label>
              <label className="flex items-center gap-2">
                <Switch checked={form.enabled} onCheckedChange={(v) => setForm({ ...form, enabled: v })} /> 사용
              </label>
            </div>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setEditOpen(false)}>취소</Button>
              <Button type="submit" disabled={submitting || !form.name.trim() || !form.source_id}>
                {submitting ? "저장 중…" : editing ? "수정" : "등록"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 폴더 피커 — 인테이크 드롭존과 동일 컴포넌트(folderMode) */}
      <SourcePathPicker
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        sourceId={form.source_id}
        sourceName={sources.find((s) => s.source_id === form.source_id)?.name ?? ""}
        folderMode
        onSelect={(path) => {
          setForm((f) => ({ ...f, prefix: path }))
          setPickerOpen(false)
        }}
      />

      {/* 삭제 확인 */}
      <AlertDialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader className="text-start">
            <AlertDialogTitle>워치 삭제</AlertDialogTitle>
            <AlertDialogDescription>
              <span className="font-medium text-foreground">{deleting?.name}</span> 워치를 삭제합니다.
              이미 인테이크된 문서는 영향받지 않으며, 자동 스캔만 중단됩니다.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button variant="ghost" onClick={() => setDeleting(null)}>취소</Button>
            <Button variant="destructive" onClick={() => void confirmDelete()}>삭제</Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* 실행 이력 */}
      <Dialog open={!!runsOf} onOpenChange={(o) => !o && setRunsOf(null)}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>실행 이력 — {runsOf?.name}</DialogTitle>
            <DialogDescription>최근 {runs.length}회. 파일 단위 상세는 라우팅 결정 로그 참조.</DialogDescription>
          </DialogHeader>
          <div className="max-h-96 overflow-y-auto rounded-md border">
            <Table className="text-sm">
              <TableHeader>
                <TableRow>
                  <TableHead className="text-sm">시각</TableHead>
                  <TableHead className="w-16 text-center text-sm">처리</TableHead>
                  <TableHead className="w-16 text-center text-sm">스킵</TableHead>
                  <TableHead className="text-sm">결과</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.map((r, i) => (
                  <TableRow key={i}>
                    <TableCell className="whitespace-nowrap">{fmtTime(r.started_at)}</TableCell>
                    <TableCell className="text-center">{r.scanned}</TableCell>
                    <TableCell className="text-center">{r.skipped}</TableCell>
                    <TableCell>
                      {r.error ? (
                        <span className="text-destructive">{r.error}</span>
                      ) : (
                        <span>
                          <CountsInline counts={r.counts} />
                          {r.truncated && <Badge variant="warning" className="ml-2">상한 초과 — 즉시 재실행됨</Badge>}
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
