// 스토리지 소스 — 참조 인테이크(pull)가 원본을 읽어올 S3·NAS 소스 등록/관리.
// 백엔드 app/sources. 소스는 읽기 전용이며, 인테이크 시 원본은 내부 저장소로 스냅샷 복사된다.
"use client"

import { useCallback, useEffect, useState, type FormEvent } from "react"
import Link from "next/link"
import { FlaskConical, FolderInput, HardDrive, Network, Pencil, Plus, Trash2 } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import { Badge } from "@workspace/ui/components/badge"
import { Switch } from "@workspace/ui/components/switch"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
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
import { Tooltip, TooltipContent, TooltipTrigger } from "@workspace/ui/components/tooltip"
import { TabsContent, TabsList, TabsTrigger } from "@workspace/ui/components/tabs"
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard-header"
import { Bullets, Callout, Heading, Sub, TabShell } from "@/components/doc-blocks"
import { useAuth } from "@/features/auth"
import {
  createSource,
  deleteSource,
  listSources,
  testSource,
  updateSource,
} from "@/features/storage-sources/api"
import type { SourceKind, StorageSource } from "@/features/storage-sources/data/schema"
import { WatchesTab } from "@/features/storage-sources/components/watches-tab"
import { UrlTabs } from "@/components/url-tabs"

const BLANK = {
  name: "", kind: "s3" as SourceKind, description: "", enabled: true,
  endpoint: "", bucket: "", base_prefix: "", region: "",
  access_key: "", secret_key: "",
  mount_path: "",
}
type FormState = typeof BLANK

function locationSummary(s: StorageSource): string {
  if (s.kind === "nas") {
    const base = s.config.base_prefix ? `/${s.config.base_prefix}` : ""
    return `${s.config.mount_path ?? ""}${base}`
  }
  const prefix = s.config.base_prefix ? `/${s.config.base_prefix}` : ""
  const ep = s.config.endpoint ? ` @ ${s.config.endpoint}` : ""
  return `s3://${s.config.bucket ?? ""}${prefix}${ep}`
}

export default function StorageSourcesPage() {
  return (
    <>
      <DashboardHeader title="스토리지 소스" />
      <div className="flex flex-1 flex-col p-4">
        <UrlTabs defaultValue="sources" className="gap-4">
          <TabsList>
            <TabsTrigger value="sources">소스 목록</TabsTrigger>
            <TabsTrigger value="watches">자동 수집</TabsTrigger>
            <TabsTrigger value="guide">사용법</TabsTrigger>
          </TabsList>
          <TabsContent value="sources"><SourcesTab /></TabsContent>
          <TabsContent value="watches"><WatchesTab /></TabsContent>
          <TabsContent value="guide"><GuideTab /></TabsContent>
        </UrlTabs>
      </div>
    </>
  )
}

function SourcesTab() {
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser
  const [sources, setSources] = useState<StorageSource[]>([])
  const [loading, setLoading] = useState(true)

  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<StorageSource | null>(null) // null = 신규
  const [form, setForm] = useState<FormState>(BLANK)
  const [submitting, setSubmitting] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<StorageSource | null>(null)
  const [testingId, setTestingId] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setSources(await listSources())
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { refresh() }, [refresh])

  function openNew() {
    setEditing(null)
    setForm(BLANK)
    setEditOpen(true)
  }
  function openEdit(s: StorageSource) {
    setEditing(s)
    setForm({
      ...BLANK,
      name: s.name, kind: s.kind, description: s.description ?? "", enabled: s.enabled,
      endpoint: s.config.endpoint ?? "", bucket: s.config.bucket ?? "",
      base_prefix: s.config.base_prefix ?? "", region: s.config.region ?? "",
      mount_path: s.config.mount_path ?? "",
      // 자격증명은 응답에 없음(has_secret 만) — 빈칸이면 기존 유지.
    })
    setEditOpen(true)
  }

  function buildConfig(f: FormState): Record<string, string> {
    if (f.kind === "nas") return { mount_path: f.mount_path.trim(), base_prefix: f.base_prefix.trim() }
    return {
      endpoint: f.endpoint.trim(), bucket: f.bucket.trim(),
      base_prefix: f.base_prefix.trim(), region: f.region.trim(),
    }
  }

  function buildSecret(f: FormState): Record<string, string> | null {
    if (f.kind !== "s3") return null
    if (!f.access_key.trim() && !f.secret_key.trim()) return null // 빈칸 = (수정 시) 기존 유지
    return { access_key: f.access_key.trim(), secret_key: f.secret_key.trim() }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    try {
      const config = buildConfig(form)
      const secret = buildSecret(form)
      const description = form.description.trim() || null
      if (editing) {
        await updateSource(editing.source_id, {
          name: form.name.trim(), description, config,
          ...(secret ? { secret } : {}), enabled: form.enabled,
        })
      } else {
        await createSource({
          name: form.name.trim(), kind: form.kind, description, config, secret,
          enabled: form.enabled,
        })
      }
      toast.success(editing ? "소스를 수정했습니다." : "소스를 등록했습니다.")
      setEditOpen(false)
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "저장 실패")
    } finally {
      setSubmitting(false)
    }
  }

  async function toggleEnabled(s: StorageSource) {
    try {
      await updateSource(s.source_id, { enabled: !s.enabled })
      setSources((prev) => prev.map((x) => (x.id === s.id ? { ...x, enabled: !x.enabled } : x)))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "변경 실패")
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    try {
      await deleteSource(deleteTarget.source_id)
      toast.success("소스를 삭제했습니다.")
      setDeleteTarget(null)
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "삭제 실패")
    }
  }

  async function runTest(s: StorageSource) {
    setTestingId(s.source_id)
    try {
      const r = await testSource(s.source_id)
      if (r.ok) toast.success(`${s.name}: ${r.message} (${r.elapsed_ms}ms)`)
      else toast.error(`${s.name}: ${r.message}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "테스트 실패")
    } finally {
      setTestingId(null)
    }
  }

  return (
    <>
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            문서를 <span className="font-medium text-foreground">경로 참조로 가져올(pull)</span> 원본 스토리지(S3·NAS)를 등록합니다.
            소스 <span className="font-medium text-foreground">이름</span>은 라우팅 정책의 경로 규칙(path_rule)이 참조하는 논리 식별자입니다.
            {!canManage && <span className="text-destructive"> 등록·수정은 관리자만 가능합니다.</span>}
          </p>
          {canManage && (
            <Button size="sm" onClick={openNew}>
              <Plus className="size-4" /> 소스 추가
            </Button>
          )}
        </div>

        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16 text-center">사용</TableHead>
                <TableHead className="w-48">이름</TableHead>
                <TableHead className="w-20 text-center">종류</TableHead>
                <TableHead>위치</TableHead>
                <TableHead className="w-24 text-center">자격증명</TableHead>
                <TableHead className="w-36 text-right">작업</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow><TableCell colSpan={6} className="py-8 text-center text-muted-foreground">불러오는 중...</TableCell></TableRow>
              ) : sources.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-8 text-center text-muted-foreground">
                    <HardDrive className="mx-auto mb-2 size-6 opacity-50" />
                    등록된 스토리지 소스가 없습니다.
                  </TableCell>
                </TableRow>
              ) : (
                sources.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell className="text-center">
                      <Switch checked={s.enabled} onCheckedChange={() => toggleEnabled(s)} disabled={!canManage} />
                    </TableCell>
                    <TableCell className="text-sm">
                      {s.name}
                      {s.description && <p className="text-xs text-muted-foreground">{s.description}</p>}
                    </TableCell>
                    <TableCell className="text-center">
                      <Badge variant="outline" className="font-mono text-xs uppercase">{s.kind}</Badge>
                    </TableCell>
                    <TableCell className="max-w-0">
                      <span className="block truncate font-mono text-xs" title={locationSummary(s)}>{locationSummary(s)}</span>
                    </TableCell>
                    <TableCell className="text-center text-xs text-muted-foreground">
                      {s.kind === "nas" ? "마운트" : s.has_secret ? "설정됨" : "없음"}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button variant="ghost" size="sm" className="h-7 px-2" disabled={!canManage || testingId === s.source_id} onClick={() => runTest(s)}>
                              <FlaskConical className="size-4" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>연결 테스트</TooltipContent>
                        </Tooltip>
                        {canManage && (
                          <>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => openEdit(s)}><Pencil className="size-4" /></Button>
                              </TooltipTrigger>
                              <TooltipContent>수정</TooltipContent>
                            </Tooltip>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button variant="ghost" size="sm" className="h-7 px-2 text-muted-foreground" onClick={() => setDeleteTarget(s)}><Trash2 className="size-4" /></Button>
                              </TooltipTrigger>
                              <TooltipContent>삭제</TooltipContent>
                            </Tooltip>
                          </>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>

        <Callout>
          소스는 <span className="font-medium text-foreground">읽기 전용</span>입니다. 인테이크 시 원본은 내부 저장소로{" "}
          <span className="font-medium text-foreground">스냅샷 복사</span>되므로, 이후 소스의 파일이 변경·삭제돼도 등록된 문서와 재인덱싱에는 영향이 없습니다.
        </Callout>
      </div>

      {/* 생성/수정 */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <DialogHeader>
              <DialogTitle>{editing ? "스토리지 소스 수정" : "스토리지 소스 등록"}</DialogTitle>
              <DialogDescription>
                {form.kind === "nas"
                  ? "서버 호스트에 NFS/SMB 마운트를 먼저 걸고, 마운트 루트 경로를 등록합니다."
                  : "S3 호환(MinIO/AWS) 버킷을 소스로 등록합니다. 자격증명은 암호화 저장되며 응답에 노출되지 않습니다."}
              </DialogDescription>
            </DialogHeader>

            <div className="flex gap-3">
              <div className="flex flex-1 flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">이름 (라우팅 규칙이 참조하는 논리명)</Label>
                <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required autoFocus placeholder="예: 사업부NAS, docs-s3" />
              </div>
              <div className="flex w-32 flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">종류</Label>
                <Select value={form.kind} onValueChange={(v) => setForm({ ...form, kind: v as SourceKind })} disabled={!!editing}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="s3">S3 호환</SelectItem>
                    <SelectItem value="nas">NAS(마운트)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {form.kind === "s3" ? (
              <>
                <div className="flex gap-3">
                  <div className="flex flex-1 flex-col gap-1.5">
                    <Label className="text-xs text-muted-foreground">엔드포인트 (AWS 는 비움)</Label>
                    <Input className="font-mono text-sm" value={form.endpoint} onChange={(e) => setForm({ ...form, endpoint: e.target.value })} placeholder="http://192.0.2.48:9000" />
                  </div>
                  <div className="flex w-40 flex-col gap-1.5">
                    <Label className="text-xs text-muted-foreground">리전 (선택)</Label>
                    <Input className="font-mono text-sm" value={form.region} onChange={(e) => setForm({ ...form, region: e.target.value })} placeholder="us-east-1" />
                  </div>
                </div>
                <div className="flex gap-3">
                  <div className="flex flex-1 flex-col gap-1.5">
                    <Label className="text-xs text-muted-foreground">버킷</Label>
                    <Input className="font-mono text-sm" value={form.bucket} onChange={(e) => setForm({ ...form, bucket: e.target.value })} required placeholder="dept-docs" />
                  </div>
                  <div className="flex flex-1 flex-col gap-1.5">
                    <Label className="text-xs text-muted-foreground">기본 프리픽스 (선택)</Label>
                    <Input className="font-mono text-sm" value={form.base_prefix} onChange={(e) => setForm({ ...form, base_prefix: e.target.value })} placeholder="shared/docs" />
                  </div>
                </div>
                <div className="flex gap-3">
                  <div className="flex flex-1 flex-col gap-1.5">
                    <Label className="text-xs text-muted-foreground">Access Key{editing?.has_secret ? " (비우면 기존 유지)" : ""}</Label>
                    <Input className="font-mono text-sm" value={form.access_key} onChange={(e) => setForm({ ...form, access_key: e.target.value })} autoComplete="off" />
                  </div>
                  <div className="flex flex-1 flex-col gap-1.5">
                    <Label className="text-xs text-muted-foreground">Secret Key{editing?.has_secret ? " (비우면 기존 유지)" : ""}</Label>
                    <Input type="password" className="font-mono text-sm" value={form.secret_key} onChange={(e) => setForm({ ...form, secret_key: e.target.value })} autoComplete="new-password" />
                  </div>
                </div>
              </>
            ) : (
              <div className="flex gap-3">
                <div className="flex flex-1 flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">마운트 경로 (서버 호스트의 절대 경로)</Label>
                  <Input className="font-mono text-sm" value={form.mount_path} onChange={(e) => setForm({ ...form, mount_path: e.target.value })} required placeholder="/mnt/nas/legal" />
                </div>
                <div className="flex flex-1 flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">기본 프리픽스 (선택)</Label>
                  <Input className="font-mono text-sm" value={form.base_prefix} onChange={(e) => setForm({ ...form, base_prefix: e.target.value })} placeholder="shared/docs" />
                </div>
              </div>
            )}

            <div className="flex items-center justify-between gap-3">
              <div className="flex flex-1 flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">설명 (선택)</Label>
                <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </div>
              <label className="flex items-center gap-2 pt-5 text-sm">
                <Switch checked={form.enabled} onCheckedChange={(v) => setForm({ ...form, enabled: v })} /> 사용
              </label>
            </div>

            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setEditOpen(false)}>취소</Button>
              <Button type="submit" disabled={submitting || !form.name.trim() || (form.kind === "s3" ? !form.bucket.trim() : !form.mount_path.trim())}>
                {submitting ? "저장 중..." : editing ? "수정" : "등록"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 삭제 확인 */}
      <Dialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>스토리지 소스 삭제</DialogTitle>
            <DialogDescription>
              이 소스를 삭제할까요? 이미 인테이크된 문서는 스냅샷이라 영향이 없지만, 활성 라우팅 정책이 이 소스 이름을 참조 중이면 삭제가 거부됩니다.
            </DialogDescription>
          </DialogHeader>
          {deleteTarget && <p className="rounded-md border bg-muted/40 p-2 text-sm">{deleteTarget.name} <span className="font-mono text-xs text-muted-foreground">({locationSummary(deleteTarget)})</span></p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setDeleteTarget(null)}>취소</Button>
            <Button type="button" variant="destructive" onClick={confirmDelete}>삭제</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

// ---------------------------------------------------------------------------
// 사용법
// ---------------------------------------------------------------------------

function GuideTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={HardDrive}>스토리지 소스 — 경로 참조 인테이크의 원본</Heading>
        <p className="text-muted-foreground">
          문서를 직접 업로드하는 대신, 부서 시스템·배치가 <span className="font-medium text-foreground">약속된 스토리지 경로에 문서를 놓기만 하면</span>{" "}
          시스템이 가져와(pull) 처리하도록 원본 스토리지를 등록하는 곳입니다. 등록한 소스는{" "}
          <Link href="/dashboard/routing" className="text-primary hover:underline">RAG 문서 라우팅</Link>의 인테이크(&lsquo;소스에서 가져오기&rsquo;)와
          경로 규칙(path_rule)에서 사용됩니다.
        </p>
      </section>

      <section>
        <Sub icon={Plus}>① 소스 등록</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">이름</span> — 라우팅 경로 규칙이 참조하는 <span className="font-medium text-foreground">논리 식별자</span>(unique). 활성 정책이 참조 중이면 이름 변경/삭제가 거부됩니다.</>,
            <><span className="font-medium text-foreground">S3 호환</span> — 엔드포인트(MinIO)·버킷·자격증명을 입력합니다. 자격증명은 <span className="font-medium text-foreground">암호화 저장</span>되며 조회 응답에 노출되지 않습니다.</>,
            <><span className="font-medium text-foreground">NAS(마운트)</span> — 서버 호스트에 NFS/SMB 마운트를 먼저 걸고 마운트 루트 경로만 등록합니다(자격증명은 마운트가 대신).</>,
            <><span className="font-medium text-foreground">기본 프리픽스</span> — 소스 내 특정 폴더만 노출하고 싶을 때(경로는 이 프리픽스 기준 상대 경로).</>,
            <><span className="font-medium text-foreground">연결 테스트</span> — 목록의 플라스크 버튼으로 접근 가능/자격증명을 즉시 확인하십시오.</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={FolderInput}>② 인테이크에서 사용</Sub>
        <p className="text-muted-foreground">
          <Link href="/dashboard/routing" className="text-primary hover:underline">RAG 문서 라우팅</Link> → 인테이크 탭의{" "}
          <span className="font-medium text-foreground">&lsquo;소스에서 가져오기&rsquo;</span>에서 소스와 경로를 지정하면, 시스템이 원본을 읽어
          라우팅 정책으로 지식베이스를 정해 등록·인제스천합니다. 원본은 내부 저장소로 <span className="font-medium text-foreground">스냅샷 복사</span>되고
          출처(소스·경로)는 문서 메타데이터(<span className="font-mono text-sm">origin_source</span>/<span className="font-mono text-sm">origin_path</span>)에 보존됩니다.
        </p>
      </section>

      <section>
        <Sub icon={Network}>③ 경로로 라우팅</Sub>
        <p className="text-muted-foreground">
          라우팅 정책에 <span className="font-medium text-foreground">경로 규칙(path_rule)</span> 단계를 추가하면{" "}
          <span className="font-mono text-sm">contracts/</span> 같은 경로 프리픽스(또는 글롭·정규식)와 소스 이름으로 지식베이스를 배분할 수 있습니다.
          경로 체계가 곧 문서의 소속인 조직 폴더 구조를 그대로 라우팅 규칙으로 옮기는 방식입니다.
        </p>
      </section>

      <Callout icon={FlaskConical}>
        정책을 바꾸기 전·후로 라우팅 테스트 탭의 <span className="font-medium text-foreground">경로 시뮬레이션</span>(파일 없이 경로 문자열만으로 확인)을 활용하십시오.
      </Callout>
    </TabShell>
  )
}
