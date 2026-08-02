// PII Rule — 개인정보 정규식 규칙 관리(등록/수정/삭제 + 테스트). 인제스천 post_parse 의
// pii_regex transform 이 enabled 규칙을 적용한다.
"use client"

import { useCallback, useEffect, useState, type FormEvent } from "react"
import Link from "next/link"
import dynamic from "next/dynamic"
import { FlaskConical, GitBranch, HelpCircle, Plus, ShieldAlert, Pencil, Trash2 } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import { Badge } from "@workspace/ui/components/badge"
import { Textarea } from "@workspace/ui/components/textarea"
import { Checkbox } from "@workspace/ui/components/checkbox"
import { Switch } from "@workspace/ui/components/switch"
import { Card, CardContent, CardHeader, CardTitle } from "@workspace/ui/components/card"
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
import { DataTablePagination, useClientPagination } from "@/components/data-table"
import { useAuth } from "@/features/auth"
import {
  createPiiFunction,
  createPiiRule,
  deletePiiFunction,
  deletePiiRule,
  listPiiFunctions,
  listPiiRules,
  testPiiFunction,
  testPiiRules,
  updatePiiFunction,
  updatePiiRule,
} from "@/features/pii/api"
import type { PiiFunction, PiiRule, PiiTestResult } from "@/features/pii/data/schema"
import { UrlTabs } from "@/components/url-tabs"

// Monaco 코드 에디터(SSR 비활성)
const MonacoEditor = dynamic(() => import("@monaco-editor/react").then((m) => m.default), { ssr: false })

const BLANK = { name: "", category: "custom", pattern: "", flags: "", mask: "[REDACTED]", enabled: true, description: "" }
type FormState = typeof BLANK

const FN_TEMPLATE = `# redact(text) 를 정의하세요. 매칭/치환 결과 문자열을 반환합니다.
# 사용 가능: re, luhn_ok(s), bizno_ok(s), rrn_ok(s)  (import 불가)
def redact(text: str) -> str:
    # 예: 사번 형식(EMP-0001) 마스킹
    return re.sub(r"EMP-\\d{4}", "[EMP]", text)
`

export default function PiiRulesPage() {
  return (
    <>
      <DashboardHeader title="PII Rule" />
      <div className="flex flex-1 flex-col p-4">
        <UrlTabs defaultValue="rules" className="gap-4">
          <TabsList>
            <TabsTrigger value="rules">정규표현식 규칙</TabsTrigger>
            <TabsTrigger value="functions">확장 함수 규칙</TabsTrigger>
            <TabsTrigger value="custom">사용자 정의 함수 규칙</TabsTrigger>
            <TabsTrigger value="guide">PII Rule 사용법</TabsTrigger>
            <TabsTrigger value="regex">정규식 작성방법</TabsTrigger>
          </TabsList>
          <TabsContent value="rules">
            <PiiRuleManageTab />
          </TabsContent>
          <TabsContent value="guide">
            <PiiRuleUsageTab />
          </TabsContent>
          <TabsContent value="regex">
            <RegexGuideTab />
          </TabsContent>
          <TabsContent value="functions">
            <BuiltinFunctionsTab />
          </TabsContent>
          <TabsContent value="custom">
            <PiiFunctionsTab />
          </TabsContent>
        </UrlTabs>
      </div>
    </>
  )
}

function PiiRuleManageTab() {
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser
  const [rules, setRules] = useState<PiiRule[]>([])
  const [loading, setLoading] = useState(true)

  // 생성/수정 다이얼로그
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<PiiRule | null>(null) // null = 신규
  const [form, setForm] = useState<FormState>(BLANK)
  const [submitting, setSubmitting] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<PiiRule | null>(null)

  // 테스트
  const [sample, setSample] = useState("")
  const [testResult, setTestResult] = useState<PiiTestResult | null>(null)
  const [testing, setTesting] = useState(false)

  const { table, pageItems } = useClientPagination(rules, 30)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setRules(await listPiiRules())
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  function openNew() {
    setEditing(null)
    setForm(BLANK)
    setEditOpen(true)
  }
  function openEdit(r: PiiRule) {
    setEditing(r)
    setForm({ name: r.name, category: r.category, pattern: r.pattern, flags: r.flags, mask: r.mask, enabled: r.enabled, description: r.description ?? "" })
    setEditOpen(true)
  }

  function toggleFlag(f: "i" | "m" | "s") {
    setForm((s) => ({ ...s, flags: s.flags.includes(f) ? s.flags.replace(f, "") : s.flags + f }))
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    try {
      const payload = { ...form, description: form.description.trim() || null }
      if (editing) await updatePiiRule(editing.rule_id, payload)
      else await createPiiRule(payload)
      toast.success(editing ? "규칙을 수정했습니다." : "규칙을 등록했습니다.")
      setEditOpen(false)
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "저장 실패")
    } finally {
      setSubmitting(false)
    }
  }

  async function toggleEnabled(r: PiiRule) {
    try {
      await updatePiiRule(r.rule_id, { enabled: !r.enabled })
      setRules((prev) => prev.map((x) => (x.id === r.id ? { ...x, enabled: !x.enabled } : x)))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "변경 실패")
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    try {
      await deletePiiRule(deleteTarget.rule_id)
      toast.success("규칙을 삭제했습니다.")
      setDeleteTarget(null)
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "삭제 실패")
    }
  }

  async function runTest() {
    if (!sample.trim()) return
    setTesting(true)
    try {
      setTestResult(await testPiiRules(sample))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "테스트 실패")
    } finally {
      setTesting(false)
    }
  }

  return (
    <>
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            개인정보 정규식 규칙을 등록합니다. 인제스천 파이프라인의 <span className="font-mono text-xs">pii_regex</span> 단계(파싱 후)가
            사용 중(enabled) 규칙을 적용해 본문을 마스킹합니다.
          </p>
          {canManage && (
            <Button size="sm" onClick={openNew}>
              <Plus className="size-4" />
              규칙 추가
            </Button>
          )}
        </div>

        {/* 목록 */}
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16 text-center">사용</TableHead>
                <TableHead>이름</TableHead>
                <TableHead className="w-28">분류</TableHead>
                <TableHead className="w-[40%]">패턴</TableHead>
                <TableHead className="w-28">마스크</TableHead>
                <TableHead className="w-20 text-right">작업</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-8 text-center text-muted-foreground">불러오는 중...</TableCell>
                </TableRow>
              ) : rules.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-8 text-center text-muted-foreground">
                    <ShieldAlert className="mx-auto mb-2 size-6 opacity-50" />
                    등록된 PII 규칙이 없습니다.
                  </TableCell>
                </TableRow>
              ) : (
                pageItems.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="text-center">
                      <Switch checked={r.enabled} onCheckedChange={() => toggleEnabled(r)} disabled={!canManage} />
                    </TableCell>
                    <TableCell className="text-sm">
                      {r.name}
                      {r.description && <p className="text-xs text-muted-foreground">{r.description}</p>}
                    </TableCell>
                    <TableCell><Badge variant="outline">{r.category}</Badge></TableCell>
                    <TableCell className="max-w-0">
                      <span className="block truncate font-mono text-sm" title={r.pattern}>{r.pattern}</span>
                      {r.flags && <span className="text-xs text-muted-foreground">flags: {r.flags}</span>}
                    </TableCell>
                    <TableCell className="font-mono text-sm">{r.mask}</TableCell>
                    <TableCell className="text-right">
                      {canManage && (
                        <div className="flex justify-end gap-1">
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => openEdit(r)}>
                                <Pencil className="size-4" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>수정</TooltipContent>
                          </Tooltip>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button variant="ghost" size="sm" className="h-7 px-2 text-muted-foreground" onClick={() => setDeleteTarget(r)}>
                                <Trash2 className="size-4" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>삭제</TooltipContent>
                          </Tooltip>
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
        {rules.length > 0 && <DataTablePagination table={table} />}

        {/* 테스트 */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">규칙 테스트</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="text-xs text-muted-foreground">
              샘플 텍스트에 사용 중(enabled) 규칙을 적용한 결과를 미리 봅니다(실제 인제스천과 동일 로직).
            </p>
            <Textarea
              value={sample}
              onChange={(e) => setSample(e.target.value)}
              placeholder="예: 홍길동 010-1234-5678 / hong@example.com / 900101-1234567"
              className="min-h-20 font-mono text-sm"
            />
            <div>
              <Button size="sm" onClick={runTest} disabled={testing || !sample.trim()}>
                {testing ? "테스트 중..." : "테스트"}
              </Button>
            </div>
            {testResult && (
              <div className="flex flex-col gap-2">
                <div className="rounded-md border bg-muted/30 p-3">
                  <p className="mb-1 text-xs font-medium text-muted-foreground">마스킹 결과</p>
                  <p className="whitespace-pre-wrap font-mono text-sm">{testResult.masked}</p>
                </div>
                <div className="flex flex-wrap gap-1.5 text-xs">
                  {testResult.matches.length === 0 ? (
                    <span className="text-muted-foreground">매치된 규칙이 없습니다.</span>
                  ) : (
                    testResult.matches.map((m) => (
                      <Badge key={m.rule_id} variant="secondary" className="font-normal">{m.name} · {m.count}건</Badge>
                    ))
                  )}
                </div>
                {testResult.invalid.length > 0 && (
                  <p className="text-xs text-destructive">컴파일 실패 규칙 {testResult.invalid.length}개(무시됨).</p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* 생성/수정 */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <DialogHeader>
              <DialogTitle>{editing ? "PII 규칙 수정" : "PII 규칙 등록"}</DialogTitle>
              <DialogDescription>파이썬 정규식(re)으로 매칭된 부분이 마스크 문자열로 치환됩니다.</DialogDescription>
            </DialogHeader>
            <div className="flex gap-3">
              <div className="flex flex-1 flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">이름</Label>
                <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required autoFocus />
              </div>
              <div className="flex w-40 flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">분류</Label>
                <Input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} placeholder="rrn·email·phone·custom" />
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">정규식 패턴</Label>
              <Input className="font-mono" value={form.pattern} onChange={(e) => setForm({ ...form, pattern: e.target.value })} required placeholder="\\d{6}-\\d{7}" />
            </div>
            <div className="flex items-end gap-3">
              <div className="flex flex-1 flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">마스크 문자열</Label>
                <Input className="font-mono" value={form.mask} onChange={(e) => setForm({ ...form, mask: e.target.value })} placeholder="[RRN]" />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="flex items-center gap-1 text-xs text-muted-foreground">
                  플래그
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button type="button" className="text-muted-foreground hover:text-foreground" aria-label="플래그 설명">
                        <HelpCircle className="size-3.5" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent className="max-w-xs">
                      <div className="flex flex-col gap-1">
                        <span><span className="font-mono">i</span> — 대소문자 무시 (IGNORECASE): ABC = abc</span>
                        <span><span className="font-mono">m</span> — 여러 줄 (MULTILINE): <span className="font-mono">^</span>/<span className="font-mono">$</span> 가 각 줄의 처음/끝에 매칭</span>
                        <span><span className="font-mono">s</span> — 줄바꿈 포함 (DOTALL): <span className="font-mono">.</span> 이 개행 문자도 매칭</span>
                      </div>
                    </TooltipContent>
                  </Tooltip>
                </Label>
                <div className="flex gap-3 pb-2 text-sm">
                  <label className="flex items-center gap-1"><Checkbox checked={form.flags.includes("i")} onCheckedChange={() => toggleFlag("i")} /> i</label>
                  <label className="flex items-center gap-1"><Checkbox checked={form.flags.includes("m")} onCheckedChange={() => toggleFlag("m")} /> m</label>
                  <label className="flex items-center gap-1"><Checkbox checked={form.flags.includes("s")} onCheckedChange={() => toggleFlag("s")} /> s</label>
                </div>
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">설명 (선택)</Label>
              <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </div>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setEditOpen(false)}>취소</Button>
              <Button type="submit" disabled={submitting || !form.name.trim() || !form.pattern.trim()}>
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
            <DialogTitle>PII 규칙 삭제</DialogTitle>
            <DialogDescription>이 규칙을 삭제할까요? 이 작업은 되돌릴 수 없습니다.</DialogDescription>
          </DialogHeader>
          {deleteTarget && <p className="rounded-md border bg-muted/40 p-2 text-sm">{deleteTarget.name}</p>}
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

function PiiRuleUsageTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={ShieldAlert}>PII Rule — 본문 개인정보 정규식 마스킹</Heading>
        <p className="text-muted-foreground">
          PII Rule은 문서 본문에서 개인정보(주민등록번호·이메일·전화번호 등)를 <span className="font-medium text-foreground">정규식으로
          찾아 마스킹</span>하는 규칙을 등록하는 곳입니다. 여기서 등록한 규칙은 전역 자산으로, 인제스천 파이프라인의{" "}
          <span className="font-mono text-sm">pii_regex</span> 단계(파싱 직후)가 <span className="font-medium text-foreground">사용 중(enabled)</span>
          규칙을 적용합니다. <span className="font-medium text-foreground">등록·수정·삭제는 관리자</span>만 가능합니다.
        </p>
      </section>

      <section>
        <Sub icon={Plus}>① 규칙 등록</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">이름</span> — 규칙 식별용(예: 주민등록번호).</>,
            <><span className="font-medium text-foreground">분류(category)</span> — rrn·email·phone·card·custom 등. 파이프라인 단계에서 분류로 일부만 골라 적용할 수 있습니다.</>,
            <><span className="font-medium text-foreground">정규식 패턴</span> — 파이썬 <span className="font-mono text-sm">re</span> 문법. 등록 시 컴파일 검증되어 잘못된 식은 저장되지 않습니다.</>,
            <><span className="font-medium text-foreground">플래그</span> — <span className="font-mono text-sm">i</span>(대소문자 무시)·<span className="font-mono text-sm">m</span>(여러 줄)·<span className="font-mono text-sm">s</span>(줄바꿈 포함).</>,
            <><span className="font-medium text-foreground">마스크 문자열</span> — 매칭 부분을 치환할 값(예: <span className="font-mono text-sm">[RRN]</span>).</>,
            <><span className="font-medium text-foreground">사용(enabled)</span> — 꺼두면 등록돼 있어도 적용되지 않습니다(목록에서 토글).</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={FlaskConical}>② 테스트로 검증</Sub>
        <p className="text-muted-foreground">
          규칙 탭 하단의 <span className="font-medium text-foreground">규칙 테스트</span>에 샘플 텍스트를 넣으면, 사용 중 규칙을 적용한
          <span className="font-medium text-foreground"> 마스킹 결과와 규칙별 매치 수</span>를 미리 봅니다. 실제 인제스천과 동일한 로직(파이썬 re)이라 결과가 일치합니다. 패턴을 저장하기 전·후로 꼭 확인하십시오.
        </p>
      </section>

      <section>
        <Sub icon={GitBranch}>③ 파이프라인에 연결</Sub>
        <Bullets
          items={[
            <><Link href="/dashboard/collections" className="text-primary hover:underline">지식베이스</Link> 상세의 인제스천 파이프라인에서 <span className="font-mono text-sm">pii_regex</span> 단계를 <span className="font-medium text-foreground">파싱 후(post_parse)</span> 에 추가합니다.</>,
            <>단계 설정의 <span className="font-mono text-sm">categories</span>(쉼표 구분)로 일부 분류만 적용할 수 있고, 비우면 전체 enabled 규칙을 적용합니다.</>,
            <><span className="font-medium text-foreground">실패 정책</span> — <span className="font-mono text-sm">on_error=fail</span>(기본 권장)이면 마스킹 단계 실패 시 인제스천 잡을 실패시켜 <span className="font-medium text-foreground">개인정보가 무음으로 누락 저장되는 것을 방지</span>합니다.</>,
            <>여러 PII 단계를 둘 수 있어, 정규식(pii_regex) 후에 모델 기반 단계를 <span className="font-medium text-foreground">후행</span>으로 붙이는 식의 조합도 가능합니다.</>,
          ]}
        />
      </section>

      <Callout>
        PII 마스킹은 <span className="font-medium text-foreground">파싱된 본문을 바꾸므로</span> 이후 청킹·임베딩·색인에 그대로 반영됩니다. 즉
        규칙을 바꾸면 <span className="font-medium text-foreground">기존 문서에 소급 적용되지 않고</span>, 해당 문서를 <span className="font-medium text-foreground">재인덱싱</span>해야 새 규칙이 반영됩니다.
      </Callout>
    </TabShell>
  )
}

// ---------------------------------------------------------------------------
// 정규식 작성 가이드
// ---------------------------------------------------------------------------

const REGEX_TOKENS: { token: string; desc: string }[] = [
  { token: "\\d", desc: "숫자 한 글자 (0~9). \\D 는 숫자가 아닌 글자" },
  { token: "\\w", desc: "단어 글자 (영문·숫자·_). \\W 는 그 외" },
  { token: "\\s", desc: "공백(스페이스·탭·개행). \\S 는 공백이 아닌 글자" },
  { token: ".", desc: "임의의 한 글자(개행 제외). 점 자체는 \\. 로" },
  { token: "[abc]", desc: "집합 — a 또는 b 또는 c 중 하나" },
  { token: "[0-9]", desc: "범위 — 0~9 중 하나 ([가-힣] 한글, [A-Za-z] 영문)" },
  { token: "[^0-9]", desc: "부정 집합 — 0~9 가 아닌 한 글자" },
  { token: "*", desc: "앞 패턴 0회 이상" },
  { token: "+", desc: "앞 패턴 1회 이상" },
  { token: "?", desc: "앞 패턴 0 또는 1회 (있어도 없어도)" },
  { token: "{3}", desc: "정확히 3회. {2,4}=2~4회, {2,}=2회 이상" },
  { token: "^ $", desc: "줄/문자열의 시작(^)·끝($)" },
  { token: "\\b", desc: "단어 경계 — 숫자/문자 덩어리의 가장자리(오탐 줄이기 핵심)" },
  { token: "( )", desc: "그룹. (?:...) 는 캡처 안 하는 그룹" },
  { token: "|", desc: "OR — 010|011 = 010 또는 011" },
  { token: "\\. \\- \\(", desc: "특수문자는 \\ 로 이스케이프해 글자 그대로 매칭" },
]

const REGEX_EXAMPLES: { name: string; pattern: string; note: string }[] = [
  { name: "휴대전화", pattern: "\\b01[0-9]-?\\d{3,4}-?\\d{4}\\b", note: "01X - 3~4자리 - 4자리, 하이픈은 있어도/없어도(-?)" },
  { name: "주민등록번호", pattern: "\\b\\d{6}-[1-4]\\d{6}\\b", note: "앞 6자리-성별(1~4)+6자리. 월·일까지 검증하면 오탐↓" },
  { name: "이메일", pattern: "[\\w.%+-]+@[\\w.-]+\\.[A-Za-z]{2,}", note: "아이디@도메인.최상위(2자 이상)" },
  { name: "신용카드", pattern: "\\b(?:\\d{4}[\\s-]?){3}\\d{4}\\b", note: "4자리 묶음 4번(사이 공백/하이픈 허용)" },
]

function RegexGuideTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={HelpCircle}>정규 표현식(Regex) 작성 방법</Heading>
        <p className="text-muted-foreground">
          PII 규칙의 패턴은 <span className="font-medium text-foreground">파이썬 정규식(re)</span> 문법을 씁니다. 패턴에
          <span className="font-medium text-foreground"> 매칭된 부분</span>이 규칙의 마스크 문자열로 치환됩니다. 아래 기호를 조합해
          개인정보의 형태를 묘사하면 됩니다.
        </p>
      </section>

      <section>
        <Sub icon={HelpCircle}>자주 쓰는 기호</Sub>
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="w-28 p-2">기호</th>
                <th className="p-2">의미</th>
              </tr>
            </thead>
            <tbody>
              {REGEX_TOKENS.map((t) => (
                <tr key={t.token} className="border-t align-top">
                  <td className="p-2 font-mono text-foreground">{t.token}</td>
                  <td className="p-2 text-muted-foreground">{t.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <Sub icon={ShieldAlert}>한국 PII 패턴 예시</Sub>
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="w-24 p-2">대상</th>
                <th className="w-[40%] p-2">패턴</th>
                <th className="p-2">설명</th>
              </tr>
            </thead>
            <tbody>
              {REGEX_EXAMPLES.map((e) => (
                <tr key={e.name} className="border-t align-top">
                  <td className="p-2 text-foreground">{e.name}</td>
                  <td className="p-2 font-mono text-xs text-foreground">{e.pattern}</td>
                  <td className="p-2 text-muted-foreground">{e.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <Sub icon={FlaskConical}>작성 팁</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">단어 경계 <span className="font-mono">\b</span></span> 로 앞뒤를 막으면, 더 긴 숫자열의 일부가 잘못 매칭되는 오탐을 줄입니다.</>,
            <><span className="font-medium text-foreground">하이픈 선택 <span className="font-mono">-?</span></span> 으로 <span className="font-mono">010-1234-5678</span> 과 <span className="font-mono">01012345678</span> 을 모두 잡을 수 있습니다.</>,
            <>너무 느슨하면(<span className="font-mono">\d+</span> 만 등) 일반 숫자까지 마스킹됩니다. <span className="font-medium text-foreground">자릿수·구분자·범위를 구체적으로</span> 적으십시오.</>,
            <>대소문자를 무시하려면 패턴 대신 <span className="font-medium text-foreground">플래그 <span className="font-mono">i</span></span> 를 켜는 게 깔끔합니다(여러 줄=<span className="font-mono">m</span>, 점이 개행 포함=<span className="font-mono">s</span>).</>,
            <>특수문자(<span className="font-mono">. - ( ) [ ]</span> 등)를 글자 그대로 찾으려면 앞에 <span className="font-mono">\</span> 를 붙이십시오.</>,
          ]}
        />
      </section>

      <Callout icon={FlaskConical}>
        패턴을 저장하기 전·후로 <span className="font-medium text-foreground">규칙 탭의 &lsquo;규칙 테스트&rsquo;</span> 에 샘플을 넣어 결과를
        확인하십시오. 잘못된 정규식은 저장 시 검증으로 막히고, 실행 중 컴파일 실패 규칙은 자동으로 건너뜁니다.
      </Callout>
    </TabShell>
  )
}

// ---------------------------------------------------------------------------
// 내장 함수 라이브러리
// ---------------------------------------------------------------------------

const BUILTIN_FUNCTIONS: { value: string; label: string; mask: string; desc: string }[] = [
  { value: "card", label: "신용카드 (Luhn 검증)", mask: "[CARD]", desc: "13~19자리 숫자열 중 Luhn(modulo 10) 검증을 통과한 카드 번호만 마스킹. 임의 16자리는 거르므로 정규식보다 오탐이 적습니다." },
  { value: "bizno", label: "사업자등록번호 (검증식)", mask: "[BIZNO]", desc: "10자리 사업자등록번호 검증식을 통과한 값만 마스킹." },
  { value: "rrn", label: "주민/외국인등록번호 (검증)", mask: "[RRN]", desc: "월·일·성별 + 체크섬을 검증한 값만 마스킹. 2020년 이후 부여분은 미탐 가능 → 형식 정규식 규칙 병행 권장." },
]

function BuiltinFunctionsTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={FlaskConical}>확장 함수</Heading>
        <p className="text-muted-foreground">
          정규식으로 표현하기 어려운 <span className="font-medium text-foreground">체크섬·형식 검증</span> 기반 마스킹을 미리 만들어 둔
          함수입니다. 후보를 느슨히 찾은 뒤 <span className="font-medium text-foreground">검증을 통과한 값만</span> 마스킹하므로 정규식 단독보다
          오탐이 적습니다. 인제스천 파이프라인에 <span className="font-mono text-xs">PII 확장 함수</span> 단계 하나를 추가하고, 본문 보강에서 함수를 콤보로 선택합니다.
        </p>
      </section>

      <section>
        <Sub icon={ShieldAlert}>제공 함수</Sub>
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="w-52 p-2">함수</th>
                <th className="w-24 p-2">마스크</th>
                <th className="p-2">설명</th>
              </tr>
            </thead>
            <tbody>
              {BUILTIN_FUNCTIONS.map((f) => (
                <tr key={f.value} className="border-t align-top">
                  <td className="p-2 font-medium text-foreground">{f.label}</td>
                  <td className="p-2 font-mono text-xs">{f.mask}</td>
                  <td className="p-2 text-muted-foreground">{f.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <Sub icon={GitBranch}>사용 방법</Sub>
        <Bullets
          items={[
            <><Link href="/dashboard/collections" className="text-primary hover:underline">지식베이스</Link> 인제스천 파이프라인의 <span className="font-medium text-foreground">파싱 후(post_parse)</span> 단계에 <span className="font-mono text-xs">PII 확장 함수</span> 를 추가하고 <span className="font-medium text-foreground">함수를 콤보로 선택</span>합니다.</>,
            <>여러 함수를 쓰려면 <span className="font-mono text-xs">PII 확장 함수</span> 단계를 여러 개 추가해 각각 다른 함수를 고르면 됩니다(순서 자유).</>,
            <>단계별로 <span className="font-mono text-xs">mask</span>(치환 문자열, 비우면 기본값)와 <span className="font-mono text-xs">on_error</span>(skip|fail)만 설정합니다. 등록·관리할 데이터가 없습니다(코드 내장).</>,
            <><span className="font-medium text-foreground">정규식 규칙과 함께</span> 쓸 수 있습니다 — 예: 검증 함수로 정밀 마스킹 + 형식 정규식으로 재현율 보완(선행/후행 자유).</>,
          ]}
        />
      </section>

      <Callout>
        함수도 본문을 바꾸므로 변경/추가 시 해당 문서를 <span className="font-medium text-foreground">재인덱싱</span>해야 반영됩니다. 직접 코드를 작성하는
        함수는 <span className="font-medium text-foreground">사용자 함수</span> 탭에서 관리합니다(샌드박스 실행).
      </Callout>
    </TabShell>
  )
}

// ---------------------------------------------------------------------------
// 사용자 정의 함수 (샌드박스)
// ---------------------------------------------------------------------------

const FN_BLANK = { name: "", code: FN_TEMPLATE, timeout_ms: 2000, enabled: true, description: "" }
type FnForm = typeof FN_BLANK

function PiiFunctionsTab() {
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser
  const [fns, setFns] = useState<PiiFunction[]>([])
  const [loading, setLoading] = useState(true)
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<PiiFunction | null>(null)
  const [form, setForm] = useState<FnForm>(FN_BLANK)
  const [submitting, setSubmitting] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<PiiFunction | null>(null)
  const [sample, setSample] = useState("EMP-0042 사번 테스트")
  const [testOut, setTestOut] = useState<{ result: string | null; error: string | null } | null>(null)
  const [testing, setTesting] = useState(false)

  const { table, pageItems } = useClientPagination(fns, 30)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setFns(await listPiiFunctions())
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => {
    refresh()
  }, [refresh])

  function openNew() {
    setEditing(null)
    setForm(FN_BLANK)
    setTestOut(null)
    setEditOpen(true)
  }
  function openEdit(f: PiiFunction) {
    setEditing(f)
    setForm({ name: f.name, code: f.code, timeout_ms: f.timeout_ms, enabled: f.enabled, description: f.description ?? "" })
    setTestOut(null)
    setEditOpen(true)
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    try {
      const payload = { ...form, description: form.description.trim() || null }
      if (editing) await updatePiiFunction(editing.function_id, payload)
      else await createPiiFunction(payload)
      toast.success(editing ? "함수를 수정했습니다." : "함수를 등록했습니다.")
      setEditOpen(false)
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "저장 실패")
    } finally {
      setSubmitting(false)
    }
  }

  async function toggleEnabled(f: PiiFunction) {
    try {
      await updatePiiFunction(f.function_id, { enabled: !f.enabled })
      setFns((prev) => prev.map((x) => (x.id === f.id ? { ...x, enabled: !x.enabled } : x)))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "변경 실패")
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    try {
      await deletePiiFunction(deleteTarget.function_id)
      toast.success("함수를 삭제했습니다.")
      setDeleteTarget(null)
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "삭제 실패")
    }
  }

  async function runTest() {
    setTesting(true)
    try {
      setTestOut(await testPiiFunction(form.code, sample, form.timeout_ms))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "테스트 실패")
    } finally {
      setTesting(false)
    }
  }

  return (
    <>
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            관리자가 작성한 파이썬 함수(<span className="font-mono text-xs">redact(text)</span>)를 <span className="font-medium text-foreground">샌드박스</span>(별도 프로세스·import 차단·시간/자원 제한)에서 실행합니다.
            인제스천의 <span className="font-mono text-xs">pii_function</span> 단계가 사용 중 함수를 적용합니다.
          </p>
          {canManage && (
            <Button size="sm" onClick={openNew}>
              <Plus className="size-4" />
              함수 추가
            </Button>
          )}
        </div>

        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16 text-center">사용</TableHead>
                <TableHead>이름</TableHead>
                <TableHead className="w-24 text-right">timeout</TableHead>
                <TableHead className="w-20 text-right">작업</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow><TableCell colSpan={4} className="py-8 text-center text-muted-foreground">불러오는 중...</TableCell></TableRow>
              ) : fns.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="py-8 text-center text-muted-foreground">
                    <FlaskConical className="mx-auto mb-2 size-6 opacity-50" />
                    등록된 사용자 함수가 없습니다.
                  </TableCell>
                </TableRow>
              ) : (
                pageItems.map((f) => (
                  <TableRow key={f.id}>
                    <TableCell className="text-center">
                      <Switch checked={f.enabled} onCheckedChange={() => toggleEnabled(f)} disabled={!canManage} />
                    </TableCell>
                    <TableCell className="text-sm">
                      {f.name}
                      {f.description && <p className="text-xs text-muted-foreground">{f.description}</p>}
                    </TableCell>
                    <TableCell className="text-right text-sm tabular-nums">{f.timeout_ms}ms</TableCell>
                    <TableCell className="text-right">
                      {canManage && (
                        <div className="flex justify-end gap-1">
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button variant="ghost" size="sm" className="h-7 px-2" onClick={() => openEdit(f)}><Pencil className="size-4" /></Button>
                            </TooltipTrigger>
                            <TooltipContent>수정</TooltipContent>
                          </Tooltip>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button variant="ghost" size="sm" className="h-7 px-2 text-muted-foreground" onClick={() => setDeleteTarget(f)}><Trash2 className="size-4" /></Button>
                            </TooltipTrigger>
                            <TooltipContent>삭제</TooltipContent>
                          </Tooltip>
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
        {fns.length > 0 && <DataTablePagination table={table} />}

        <Callout>
          코드는 <span className="font-medium text-foreground">별도 프로세스 샌드박스</span>에서 실행되며 <span className="font-mono text-xs">import</span>·위험 빌트인(open/eval 등)은 차단되고 시간/자원 제한이 적용됩니다.
          다만 OS 레벨 완전 격리는 아니므로, 인제스천 워커를 네트워크·파일시스템이 제한된 환경에서 운영하길 권장합니다.
        </Callout>
      </div>

      {/* 생성/수정 — 코드 에디터 + 테스트 */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="max-w-3xl">
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <DialogHeader>
              <DialogTitle>{editing ? "사용자 함수 수정" : "사용자 함수 등록"}</DialogTitle>
              <DialogDescription><span className="font-mono">def redact(text: str) -&gt; str</span> 를 정의하세요. re·luhn_ok·bizno_ok·rrn_ok 사용 가능(import 불가).</DialogDescription>
            </DialogHeader>
            <div className="flex gap-3">
              <div className="flex flex-1 flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">이름</Label>
                <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required autoFocus />
              </div>
              <div className="flex w-32 flex-col gap-1.5">
                <Label className="text-xs text-muted-foreground">timeout(ms)</Label>
                <Input type="number" value={form.timeout_ms} onChange={(e) => setForm({ ...form, timeout_ms: parseInt(e.target.value, 10) || 2000 })} />
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">코드 (Python)</Label>
              <div className="overflow-hidden rounded-md border">
                <MonacoEditor
                  height="240px"
                  language="python"
                  value={form.code}
                  onChange={(v) => setForm({ ...form, code: v ?? "" })}
                  options={{ minimap: { enabled: false }, fontSize: 14, scrollBeyondLastLine: false, lineNumbers: "on" }}
                />
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">설명 (선택)</Label>
              <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </div>
            <div className="flex items-center justify-end gap-2">
              <Input className="w-56" value={sample} onChange={(e) => setSample(e.target.value)} placeholder="테스트 입력" />
              <Button type="button" variant="outline" size="sm" onClick={runTest} disabled={testing}>
                {testing ? "실행 중..." : "테스트"}
              </Button>
            </div>
            {testOut && (
              <div className="rounded-md border bg-muted/30 p-2 text-sm">
                {testOut.error ? (
                  <p className="text-destructive">오류: {testOut.error}</p>
                ) : (
                  <p className="whitespace-pre-wrap font-mono">{testOut.result}</p>
                )}
              </div>
            )}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setEditOpen(false)}>취소</Button>
              <Button type="submit" disabled={submitting || !form.name.trim() || !form.code.trim()}>
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
            <DialogTitle>사용자 함수 삭제</DialogTitle>
            <DialogDescription>이 함수를 삭제할까요? 이 작업은 되돌릴 수 없습니다.</DialogDescription>
          </DialogHeader>
          {deleteTarget && <p className="rounded-md border bg-muted/40 p-2 text-sm">{deleteTarget.name}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setDeleteTarget(null)}>취소</Button>
            <Button type="button" variant="destructive" onClick={confirmDelete}>삭제</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
