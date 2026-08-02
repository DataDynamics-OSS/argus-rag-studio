// 모델 관리 — 모델 레지스트리(사용자 등록) + Model Repository(argus-models) 보유 현황.
// 흐름: 등록 → 외부망 팩(HF 다운로드·패키징) → 반입 → 배포 시 선택 → pull → 서빙.
// 백엔드 /api/v1/models(app/modelreg), 설계 design/model-registry.md.
"use client"

import { UrlTabs } from "@/components/url-tabs"
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react"
import {
  Boxes,
  Check,
  CloudDownload,
  Copy,
  Loader2,
  PackageCheck,
  PackageX,
  Pencil,
  Plus,
  RefreshCw,
  Terminal,
  Trash2,
  Wrench,
} from "lucide-react"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import { Switch } from "@workspace/ui/components/switch"
import { Textarea } from "@workspace/ui/components/textarea"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
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
import { TabsContent, TabsList, TabsTrigger } from "@workspace/ui/components/tabs"
import { Tooltip, TooltipContent, TooltipTrigger } from "@workspace/ui/components/tooltip"
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard-header"
import { Bullets, Callout, Heading, Sub, TabShell } from "@/components/doc-blocks"
import { useAuth } from "@/features/auth"
import {
  checkOnline,
  createModel,
  deleteModel,
  listModels,
  listPackJobs,
  startPack,
  updateModel,
  type ModelKind,
  type PackJob,
  type RegistryModel,
  type UnlistedModel,
} from "@/features/models/api"

const KIND_LABELS: Record<string, string> = {
  vlm: "VLM(이미지 인식)",
  embedding: "임베딩",
  reranker: "리랭커",
  detection: "검출(OCR)",
}
const KIND_ORDER = ["embedding", "reranker", "vlm", "detection"]

function packCommand(m: { kind: string; repo: string; name: string; revision: string }): string {
  return `python -m scripts.pack_model --kind ${m.kind} --repo ${m.repo} --name ${m.name} --revision ${m.revision}`
}

function importCommand(m: { kind: string; name: string; revision: string }): string {
  return `mc cp packs/${m.kind}/${m.name}/${m.revision}/* <alias>/argus-models/${m.kind}/${m.name}/${m.revision}/`
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2"
          onClick={async () => {
            await navigator.clipboard.writeText(text)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          }}
        >
          {copied ? <Check className="size-4 text-emerald-600" /> : <Copy className="size-4" />}
        </Button>
      </TooltipTrigger>
      {/* 공용 TooltipContent 는 inline-flex(가로) — 세로 2줄이 되도록 단일 블록으로 감싼다. */}
      <TooltipContent className="max-w-96">
        <div>
          <p>{label}</p>
          <p className="mt-1 font-mono text-sm">{text}</p>
        </div>
      </TooltipContent>
    </Tooltip>
  )
}

function AvailabilityBadge({ m }: { m: RegistryModel }) {
  if (m.available) {
    return (
      <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-600">
        <PackageCheck className="size-3" /> 보유
      </Badge>
    )
  }
  if (m.source !== "hf") {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge variant="outline" className="border-violet-500/30 bg-violet-500/10 text-violet-600">
            <Wrench className="size-3" /> 수동 반입
          </Badge>
        </TooltipTrigger>
        <TooltipContent className="max-w-72">
          HF 배포가 아니라 pack_model.py 로 팩할 수 없습니다. 볼륨에 직접 전개하십시오. {m.note}
        </TooltipContent>
      </Tooltip>
    )
  }
  return (
    <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-amber-600">
      <PackageX className="size-3" /> 미보유
    </Badge>
  )
}

export default function ModelsPage() {
  return (
    <>
      <DashboardHeader title="모델" />
      <div className="flex flex-1 flex-col p-4">
        <UrlTabs defaultValue="registry" className="gap-4">
          <TabsList>
            <TabsTrigger value="registry">모델 레지스트리</TabsTrigger>
            <TabsTrigger value="guide">사용법</TabsTrigger>
          </TabsList>
          <TabsContent value="registry"><RegistryTab /></TabsContent>
          <TabsContent value="guide"><GuideTab /></TabsContent>
        </UrlTabs>
      </div>
    </>
  )
}

const BLANK = {
  kind: "embedding" as ModelKind,
  name: "",
  nameTouched: false, // repo 입력에서 자동 제안할지
  repo: "",
  revision: "main",
  note: "",
  max_len: "8192",
  enabled: true,
}
type FormState = typeof BLANK

function RegistryTab() {
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser
  const [models, setModels] = useState<RegistryModel[]>([])
  const [unlisted, setUnlisted] = useState<UnlistedModel[]>([])
  const [bucket, setBucket] = useState("")
  const [loading, setLoading] = useState(true)

  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<RegistryModel | null>(null) // null = 신규
  const [form, setForm] = useState<FormState>(BLANK)
  const [submitting, setSubmitting] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<RegistryModel | null>(null)
  // 서버에서 팩(온라인 개발망 편의) — HF 도달 가능할 때만 버튼 노출, 잡은 폴링.
  const [online, setOnline] = useState(false)
  const [packJobs, setPackJobs] = useState<PackJob[]>([])
  const [packTarget, setPackTarget] = useState<RegistryModel | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const d = await listModels()
      setModels(d.models)
      setUnlisted(d.unlisted ?? [])
      setBucket(d.bucket)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { refresh() }, [refresh])
  useEffect(() => {
    checkOnline().then(setOnline)
    listPackJobs().then(setPackJobs).catch(() => {})
  }, [])

  // 진행 중 잡이 있으면 3초 폴링 — 끝나면 목록 새로고침(보유 전환 반영).
  useEffect(() => {
    if (!packJobs.some((j) => j.status === "running")) return
    const t = setInterval(async () => {
      try {
        const jobs = await listPackJobs()
        setPackJobs(jobs)
        if (!jobs.some((j) => j.status === "running")) {
          refresh()
          const failed = jobs.filter((j) => j.status === "error")
          if (failed.length) failed.forEach((j) => toast.error(`${j.name} 팩 실패: ${j.detail}`))
          else toast.success("서버 팩 완료 — 보유로 전환됐습니다.")
        }
      } catch { /* 다음 폴링에서 재시도 */ }
    }, 3000)
    return () => clearInterval(t)
  }, [packJobs, refresh])

  async function confirmPack() {
    if (!packTarget) return
    try {
      const job = await startPack(packTarget.model_id)
      setPackJobs((prev) => [job, ...prev.filter((j) => j.model_id !== job.model_id)])
      toast.success(`${packTarget.name} 팩을 시작했습니다 — 다운로드·업로드에 시간이 걸립니다.`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "팩 시작 실패")
    } finally {
      setPackTarget(null)
    }
  }

  const jobByModel = useMemo(
    () => new Map(packJobs.map((j) => [j.model_id, j])),
    [packJobs]
  )
  const anyPacking = packJobs.some((j) => j.status === "running")

  const sorted = useMemo(
    () =>
      [...models].sort(
        (a, b) =>
          KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind) ||
          a.name.localeCompare(b.name)
      ),
    [models]
  )
  const held = models.filter((m) => m.available).length

  function openNew(prefill?: Partial<FormState>) {
    setEditing(null)
    setForm({ ...BLANK, ...prefill })
    setEditOpen(true)
  }
  function openEdit(m: RegistryModel) {
    setEditing(m)
    setForm({
      kind: m.kind, name: m.name, nameTouched: true, repo: m.repo, revision: m.revision,
      note: m.note ?? "", max_len: String(m.max_len ?? 8192), enabled: m.enabled,
    })
    setEditOpen(true)
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    try {
      const body = {
        name: form.name.trim(),
        repo: form.repo.trim(),
        revision: form.revision.trim() || "main",
        note: form.note.trim(),
        ...(form.kind === "vlm" ? { max_len: parseInt(form.max_len, 10) || 8192 } : {}),
        enabled: form.enabled,
      }
      if (editing) {
        await updateModel(editing.model_id, body)
        toast.success("모델을 수정했습니다.")
      } else {
        await createModel({ kind: form.kind, ...body })
        toast.success("모델을 등록했습니다. 외부망에서 팩해 반입하면 '보유'로 바뀝니다.")
      }
      setEditOpen(false)
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "저장 실패")
    } finally {
      setSubmitting(false)
    }
  }

  async function toggleEnabled(m: RegistryModel) {
    try {
      await updateModel(m.model_id, { enabled: !m.enabled })
      setModels((prev) =>
        prev.map((x) => (x.model_id === m.model_id ? { ...x, enabled: !x.enabled } : x))
      )
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "변경 실패")
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    try {
      await deleteModel(deleteTarget.model_id)
      toast.success("모델을 삭제했습니다.")
      setDeleteTarget(null)
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "삭제 실패")
    }
  }

  return (
    <>
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            시스템이 사용할 모델을 <span className="font-medium text-foreground">종류별로 등록</span>하고, 모델 저장소{" "}
            <span className="font-mono text-sm">{bucket || "argus-models"}</span> 의 보유 현황을 관리합니다.
            등록한 모델은 에이전트의 <span className="font-medium text-foreground">서비스 배포에서 선택</span>할 수 있으며,
            보유한 모델은 배포 시 대상 서버에 자동 설치(오프라인 서빙)됩니다.
            {!loading && <span className="ml-1">보유 {held} / {models.length}</span>}
          </p>
          <div className="flex shrink-0 gap-2">
            <Button size="sm" variant="outline" onClick={refresh} disabled={loading}>
              <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} /> 새로고침
            </Button>
            {canManage && (
              <Button size="sm" onClick={() => openNew()}>
                <Plus className="size-4" /> 모델 등록
              </Button>
            )}
          </div>
        </div>

        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-14 text-center">사용</TableHead>
                <TableHead className="w-36">종류</TableHead>
                <TableHead className="w-48">모델</TableHead>
                <TableHead>HF 레포 / 비고</TableHead>
                <TableHead className="w-20 text-right">크기</TableHead>
                <TableHead className="w-24 text-center">보유</TableHead>
                <TableHead className="w-40 text-right">반입 명령 / 작업</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow><TableCell colSpan={7} className="py-8 text-center text-muted-foreground">불러오는 중...</TableCell></TableRow>
              ) : sorted.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                    <Boxes className="mx-auto mb-2 size-6 opacity-50" />
                    등록된 모델이 없습니다.
                  </TableCell>
                </TableRow>
              ) : (
                sorted.map((m) => (
                  <TableRow key={m.model_id} className={m.enabled ? undefined : "opacity-55"}>
                    <TableCell className="text-center">
                      <Switch checked={m.enabled} onCheckedChange={() => toggleEnabled(m)} disabled={!canManage} />
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-sm">{KIND_LABELS[m.kind] ?? m.kind}</Badge>
                    </TableCell>
                    <TableCell className="text-sm font-medium">
                      {m.name}
                      {m.revisions.length > 0 && (
                        <p className="font-mono text-sm font-normal text-muted-foreground">{m.revisions.join(", ")}</p>
                      )}
                    </TableCell>
                    <TableCell className="max-w-0">
                      <span className="block truncate font-mono text-sm" title={m.repo}>{m.repo}</span>
                      {/* 비고 1행 = 핵심 요약 — 전체(특징·추천 이유)는 툴팁으로 */}
                      {m.note && <p className="truncate text-sm text-muted-foreground" title={m.note}>{m.note.split("\n")[0]}</p>}
                    </TableCell>
                    <TableCell className="text-right text-sm text-muted-foreground">
                      {m.approx_gb != null ? `~${m.approx_gb} GB` : "-"}
                    </TableCell>
                    <TableCell className="text-center">
                      {jobByModel.get(m.model_id)?.status === "running" ? (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Badge variant="outline" className="border-sky-500/30 bg-sky-500/10 text-sky-600">
                              <Loader2 className="size-3 animate-spin" /> 팩 진행 중
                            </Badge>
                          </TooltipTrigger>
                          <TooltipContent className="max-w-80">{jobByModel.get(m.model_id)?.detail}</TooltipContent>
                        </Tooltip>
                      ) : (
                        <AvailabilityBadge m={m} />
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-0.5">
                        {m.source === "hf" && (
                          <>
                            <CopyButton text={packCommand(m)} label="외부망에서 실행할 팩 명령 복사" />
                            <CopyButton text={importCommand(m)} label="반입(mc cp) 명령 복사" />
                          </>
                        )}
                        {canManage && online && m.source === "hf" && (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span>
                                <Button
                                  variant="ghost" size="sm" className="h-7 px-2 text-sky-600"
                                  disabled={anyPacking}
                                  onClick={() => setPackTarget(m)}
                                >
                                  <CloudDownload className="size-4" />
                                </Button>
                              </span>
                            </TooltipTrigger>
                            <TooltipContent className="max-w-72">
                              {anyPacking
                                ? "다른 팩이 진행 중입니다 — 완료 후 시도하세요."
                                : "서버에서 팩 — 이 서버가 HF 에서 내려받아 모델 저장소에 올립니다(온라인 개발망 편의)."}
                            </TooltipContent>
                          </Tooltip>
                        )}
                        {canManage && (
                          <>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => openEdit(m)}>
                                  <Pencil className="size-4" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>수정</TooltipContent>
                            </Tooltip>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span>
                                  <Button
                                    variant="ghost" size="sm" className="h-7 px-2 text-muted-foreground"
                                    disabled={m.builtin}
                                    onClick={() => setDeleteTarget(m)}
                                  >
                                    <Trash2 className="size-4" />
                                  </Button>
                                </span>
                              </TooltipTrigger>
                              <TooltipContent>
                                {m.builtin ? "기본 제공 모델 — 삭제 대신 비활성화하세요" : "삭제"}
                              </TooltipContent>
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

        {unlisted.length > 0 && (
          <div className="flex flex-col gap-2">
            <p className="text-sm font-medium">레지스트리 외 반입분</p>
            <p className="text-sm text-muted-foreground">
              모델 저장소에는 있지만 레지스트리에 없는 팩입니다. 배포에서 쓰려면 등록해 목록으로 승격하십시오.
            </p>
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>키 (kind/name)</TableHead>
                    <TableHead className="w-40">리비전</TableHead>
                    <TableHead className="w-24 text-right">작업</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {unlisted.map((u) => {
                    const [kind, name] = u.key.split("/")
                    const knownKind = KIND_ORDER.includes(kind ?? "")
                    return (
                      <TableRow key={u.key}>
                        <TableCell className="font-mono text-sm">{u.key}</TableCell>
                        <TableCell className="font-mono text-sm">{u.revisions.join(", ")}</TableCell>
                        <TableCell className="text-right">
                          {canManage && (
                            <Button
                              variant="outline" size="sm" className="h-7"
                              onClick={() =>
                                openNew({
                                  kind: (knownKind ? kind : "embedding") as ModelKind,
                                  name: name ?? "", nameTouched: true,
                                  revision: u.revisions[0] ?? "main",
                                })
                              }
                            >
                              <Plus className="size-4" /> 등록
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          </div>
        )}

        <Callout>
          이 목록이 곧 <span className="font-medium text-foreground">에어갭 반출 승인 목록</span>입니다. 새 모델 도입 순서:
          여기서 등록 → 외부망에서 팩(행의 복사 버튼) → 반입(mc cp) → 배포에서 선택.
        </Callout>
      </div>

      {/* 등록/수정 */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <DialogHeader>
              <DialogTitle>{editing ? "모델 수정" : "모델 등록"}</DialogTitle>
              <DialogDescription>
                {editing
                  ? "이름·레포 변경 시 모델 저장소 키가 달라져 보유 상태가 끊길 수 있습니다."
                  : "HF 레포를 지정해 시스템이 사용할 모델을 선언합니다. 등록 후 외부망에서 팩해 반입하면 배포에 쓸 수 있습니다."}
              </DialogDescription>
            </DialogHeader>

            <div className="flex gap-3">
              <div className="flex w-44 flex-col gap-1.5">
                <Label className="text-sm text-muted-foreground">종류</Label>
                <Select
                  value={form.kind}
                  onValueChange={(v) => setForm({ ...form, kind: v as ModelKind })}
                  disabled={!!editing}
                >
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {KIND_ORDER.filter((k) => k !== "detection").map((k) => (
                      <SelectItem key={k} value={k}>{KIND_LABELS[k]}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-1 flex-col gap-1.5">
                <Label className="text-sm text-muted-foreground">HF 레포 (org/name)</Label>
                <Input
                  className="font-mono text-sm"
                  value={form.repo}
                  onChange={(e) => {
                    const repo = e.target.value
                    setForm((f) => ({
                      ...f, repo,
                      // 이름을 손대지 않았으면 repo 끝 이름(소문자)으로 자동 제안
                      name: f.nameTouched ? f.name : (repo.split("/").pop() ?? "").toLowerCase(),
                    }))
                  }}
                  required
                  autoFocus={!editing}
                  placeholder="BAAI/bge-m3"
                />
              </div>
            </div>

            <div className="flex gap-3">
              <div className="flex flex-1 flex-col gap-1.5">
                <Label className="text-sm text-muted-foreground">이름 (논리명 — 저장소 키·서빙 이름)</Label>
                <Input
                  className="font-mono text-sm"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value, nameTouched: true })}
                  required
                  placeholder="bge-m3"
                />
              </div>
              <div className="flex w-32 flex-col gap-1.5">
                <Label className="text-sm text-muted-foreground">리비전</Label>
                <Input
                  className="font-mono text-sm"
                  value={form.revision}
                  onChange={(e) => setForm({ ...form, revision: e.target.value })}
                  placeholder="main"
                />
              </div>
              {form.kind === "vlm" && (
                <div className="flex w-32 flex-col gap-1.5">
                  <Label className="text-sm text-muted-foreground">max-model-len</Label>
                  <Input
                    className="font-mono text-sm"
                    value={form.max_len}
                    onChange={(e) => setForm({ ...form, max_len: e.target.value })}
                    placeholder="8192"
                  />
                </div>
              )}
            </div>

            <div className="flex items-start justify-between gap-3">
              <div className="flex flex-1 flex-col gap-1.5">
                <Label className="text-sm text-muted-foreground">비고 (선택 — 1행: 핵심 요약, 2행부터: 특징·제약)</Label>
                <Textarea
                  rows={3}
                  value={form.note}
                  onChange={(e) => setForm({ ...form, note: e.target.value })}
                  placeholder="예: 한국어 지식베이스용"
                />
              </div>
              <label className="flex items-center gap-2 pt-5 text-sm">
                <Switch checked={form.enabled} onCheckedChange={(v) => setForm({ ...form, enabled: v })} /> 사용
              </label>
            </div>

            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setEditOpen(false)}>취소</Button>
              <Button type="submit" disabled={submitting || !form.name.trim() || !form.repo.trim()}>
                {submitting ? "저장 중..." : editing ? "수정" : "등록"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 서버 팩 확인 */}
      <Dialog open={!!packTarget} onOpenChange={(o) => !o && setPackTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>서버에서 팩</DialogTitle>
            <DialogDescription>
              이 서버가 HF 에서 모델을 내려받아 팩(tar+sha256)한 뒤 모델 저장소에 업로드합니다.
              {packTarget?.approx_gb ? ` 약 ${packTarget.approx_gb} GB — ` : " "}
              모델 크기에 따라 수 분~수십 분 걸리며 서버 디스크·대역폭을 사용합니다. 에어갭 반입은 외부망 pack_model 을 사용하세요.
            </DialogDescription>
          </DialogHeader>
          {packTarget && (
            <p className="rounded-md border bg-muted/40 p-2 text-sm">
              {KIND_LABELS[packTarget.kind]} / {packTarget.name}{" "}
              <span className="font-mono text-sm text-muted-foreground">({packTarget.repo}@{packTarget.revision})</span>
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setPackTarget(null)}>취소</Button>
            <Button type="button" onClick={confirmPack}><CloudDownload className="size-4" /> 팩 시작</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 삭제 확인 */}
      <Dialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>모델 삭제</DialogTitle>
            <DialogDescription>
              레지스트리에서만 제거되며 모델 저장소의 팩(반입분)은 남습니다. 배포 중인 서비스가 이 모델을 서빙 중이면 다음 배포부터 선택할 수 없게 됩니다.
            </DialogDescription>
          </DialogHeader>
          {deleteTarget && (
            <p className="rounded-md border bg-muted/40 p-2 text-sm">
              {KIND_LABELS[deleteTarget.kind]} / {deleteTarget.name}{" "}
              <span className="font-mono text-sm text-muted-foreground">({deleteTarget.repo})</span>
            </p>
          )}
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
        <Heading icon={Boxes}>모델 관리 — 등록에서 배포까지</Heading>
        <p className="text-muted-foreground">
          시스템이 사용할 모델을 자유롭게 등록하고, 에어갭 반입과 배포 선택까지 하나의 흐름으로 관리합니다:{" "}
          <span className="font-medium text-foreground">등록 → 외부망 팩 → 반입(Model Repository) → 배포에서 선택 → 자동 설치·서빙</span>.
        </p>
      </section>

      <section>
        <Sub icon={Plus}>① 모델 등록</Sub>
        <Bullets
          items={[
            <>종류(임베딩/리랭커/VLM)와 <span className="font-medium text-foreground">HF 레포(org/name)</span>를 입력합니다 — 이 레포가
              팩 명령과 서빙의 근거입니다. 이름은 레포에서 자동 제안됩니다.</>,
            <>등록 직후에는 <span className="font-medium text-foreground">미보유</span> 상태 — 아직 가중치 실물이 없다는 뜻입니다.</>,
            <>기본 제공(시드) 모델은 삭제 대신 <span className="font-medium text-foreground">사용 스위치로 비활성화</span>합니다(배포 선택에서 제외).</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={CloudDownload}>인터넷이 되는 개발망이라면 — 서버에서 팩</Sub>
        <p className="text-muted-foreground">
          이 서버가 HF 에 접근 가능하면 행의 <CloudDownload className="inline size-3.5 text-sky-600" /> 버튼으로{" "}
          <span className="font-medium text-foreground">다운로드 → 팩 → 모델 저장소 업로드</span>를 서버가 한 번에 처리합니다(외부망 PC 불필요).
          에어갭에서는 버튼이 표시되지 않으며 아래 절차로 반입합니다.
        </p>
      </section>

      <section>
        <Sub icon={Terminal}>② 외부망에서 팩 → ③ 반입</Sub>
        <Bullets
          items={[
            <>행의 <Copy className="inline size-3.5" /> 버튼으로 팩 명령을 복사해 인터넷 되는 PC 에서 실행 — HF 스냅샷을 내려받아{" "}
              <span className="font-mono text-sm">model.tar.zst</span> + <span className="font-mono text-sm">manifest.json</span>(sha256)을 만듭니다.</>,
            <>산출물을 매체로 반입해 MinIO <span className="font-mono text-sm">argus-models</span> 버킷에 올립니다(반입 명령 복사).
              업로드되면 이 화면에서 <span className="font-medium text-foreground">보유</span> 배지로 바뀝니다.</>,
            <>레지스트리에 없는 팩이 먼저 반입됐다면 아래 &lsquo;레지스트리 외 반입분&rsquo;에서 <span className="font-medium text-foreground">등록</span>으로 승격하십시오.</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={PackageCheck}>④ 배포에서 선택</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">에이전트 &gt; 서비스/배포 관리</span>에서 서비스를 배포할 때 여기 등록된
              모델을 선택합니다(비활성 모델은 목록에서 제외).</>,
            <><span className="font-medium text-foreground">보유</span> 모델은 대상 서버 볼륨에 자동 설치(pull)되어{" "}
              <span className="font-medium text-foreground">오프라인 서빙</span>됩니다 — sha256 검증·멱등(같은 팩은 스킵).</>,
            <><span className="font-medium text-foreground">미보유</span> 모델은 배포가 거부됩니다(반입 안내). 인터넷 되는 개발망에서만
              &lsquo;온라인 다운로드 허용&rsquo;으로 우회할 수 있습니다.</>,
          ]}
        />
      </section>

      <Callout icon={Wrench}>
        검출(PaddleOCR)은 HF 가 아닌 Paddle 저장소 배포라 팩 스크립트 미지원 — 볼륨에 수동 전개합니다.
      </Callout>
    </TabShell>
  )
}
