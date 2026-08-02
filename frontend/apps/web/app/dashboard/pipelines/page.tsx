// 파이프라인 — 목록/생성 탭 + 사용법 탭. 사용법은 RAG 개요와 같은 안내 블록을 공유한다.
"use client"

import { useCallback, useEffect, useState, type FormEvent } from "react"
import Link from "next/link"
import { GitBranch, GitCompare, History, Plus, Settings2, SlidersHorizontal } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import { Badge } from "@workspace/ui/components/badge"
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
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { TabsContent, TabsList, TabsTrigger } from "@workspace/ui/components/tabs"
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard-header"
import { DataTablePagination, useClientPagination } from "@/components/data-table"
import { Bullets, Callout, Heading, StrategyTable, Sub, TabShell, type StrategyRow } from "@/components/doc-blocks"
import { useAuth } from "@/features/auth"
import { createPipeline, listPipelines } from "@/features/pipelines/api"
import type { Pipeline } from "@/features/pipelines/data/schema"
import { formatDateTime, relativeTime } from "@/lib/format"
import { UrlTabs } from "@/components/url-tabs"

const SEARCH_MODE_LABELS: Record<string, string> = {
  hybrid: "하이브리드",
  vector: "벡터",
  lexical: "렉시컬",
}

export default function PipelinesPage() {
  return (
    <>
      <DashboardHeader title="파이프라인" />
      <div className="flex flex-1 flex-col p-4">
        <UrlTabs defaultValue="list" className="gap-4">
          <TabsList>
            <TabsTrigger value="list">목록</TabsTrigger>
            <TabsTrigger value="guide">사용법</TabsTrigger>
          </TabsList>
          <TabsContent value="list">
            <PipelineListTab />
          </TabsContent>
          <TabsContent value="guide">
            <PipelineUsageTab />
          </TabsContent>
        </UrlTabs>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// 목록 / 생성
// ---------------------------------------------------------------------------

function PipelineListTab() {
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser
  const [pipelines, setPipelines] = useState<Pipeline[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setPipelines(await listPipelines())
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    try {
      await createPipeline({ name })
      toast.success("파이프라인을 생성했습니다.")
      setOpen(false)
      setName("")
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "생성 실패")
    } finally {
      setSubmitting(false)
    }
  }

  const { table, pageItems } = useClientPagination(pipelines, 30)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          검색·리랭크·생성 설정을 버전 가능한 자산으로 관리합니다(버전·롤백·비교).
        </p>
        {canManage && (
          <Button size="sm" onClick={() => setOpen(true)}>
            <Plus className="size-4" />
            파이프라인 생성
          </Button>
        )}
      </div>

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>이름</TableHead>
              <TableHead className="text-center">스테이지</TableHead>
              <TableHead className="text-center">검색</TableHead>
              <TableHead className="text-center">리랭크</TableHead>
              <TableHead className="text-center">생성 모델</TableHead>
              <TableHead className="text-center">활성/버전</TableHead>
              <TableHead className="text-right">수정일</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                  불러오는 중...
                </TableCell>
              </TableRow>
            ) : pipelines.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                  <GitBranch className="mx-auto mb-2 size-6 opacity-50" />
                  파이프라인이 없습니다.
                </TableCell>
              </TableRow>
            ) : (
              pageItems.map((p) => (
                <TableRow key={p.id}>
                  <TableCell>
                    <Link href={`/dashboard/pipelines/${p.pipeline_id}`} className="font-medium hover:underline">
                      {p.name}
                    </Link>
                    {p.description && (
                      <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground" title={p.description}>
                        {p.description}
                      </p>
                    )}
                  </TableCell>
                  <TableCell className="text-center">
                    <Badge variant="outline">{p.stage}</Badge>
                  </TableCell>
                  <TableCell className="text-center">
                    {SEARCH_MODE_LABELS[p.config.retrieval.mode] ?? p.config.retrieval.mode}
                    {p.config.retrieval.distance_metric ? ` · ${p.config.retrieval.distance_metric}` : ""}
                  </TableCell>
                  <TableCell className="text-center">
                    {p.config.rerank.enabled ? (
                      <Badge variant="secondary" className="font-normal">{p.config.rerank.provider}</Badge>
                    ) : (
                      <span className="text-muted-foreground">off</span>
                    )}
                  </TableCell>
                  <TableCell className="text-center">
                    {p.config.generation.model || <span className="italic">전역</span>}
                  </TableCell>
                  <TableCell className="text-center">
                    v{p.active_version} / {p.version_count}
                  </TableCell>
                  <TableCell className="text-right" title={formatDateTime(p.updated_at)}>
                    {relativeTime(p.updated_at)}
                    {p.created_by ? <span className="block text-xs">{p.created_by}</span> : null}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {pipelines.length > 0 && <DataTablePagination table={table} />}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>파이프라인 생성</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreate} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="p-name">이름</Label>
              <Input id="p-name" value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
            </div>
            <p className="text-xs text-muted-foreground">
              현재 전역 설정값으로 v1 이 생성됩니다. 이후 상세 화면에서 설정을 수정하면 새 버전이 만들어집니다.
            </p>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
                취소
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? "생성 중..." : "생성"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 사용법
// ---------------------------------------------------------------------------

// 프리셋 — 상세 화면의 PRESETS 와 의미를 맞춘다(질의 시점 설정이라 재인덱싱 불필요).
const PRESET_ROWS: StrategyRow[] = [
  { name: "권장 (균형)", desc: "하이브리드 검색 + 리랭크. 대부분의 경우에 적합한 기본값입니다.", cost: "query" },
  { name: "정밀 (품질↑)", desc: "후보·반환 수를 늘리고 리랭크. 품질을 우선합니다(느리고 비용↑).", cost: "query" },
  { name: "저비용 (속도↓)", desc: "벡터 검색만·리랭크 끔·짧은 응답. 빠르고 저렴합니다.", cost: "query" },
]

function PipelineUsageTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={GitBranch}>파이프라인 — 설정을 버전으로 관리</Heading>
        <p className="text-muted-foreground">
          파이프라인은 검색·리랭크·생성 설정을 <span className="font-medium text-foreground">하나의 묶음으로, 버전을 매겨
          저장</span>하는 곳입니다. 전역 설정과 별개로 용도별 설정을 만들고 → 버전을 쌓고 → 문제가 생기면 이전 버전으로
          되돌리거나 비교할 수 있습니다. 이 설정들은 모두 <span className="font-medium text-foreground">질의 시점</span> 설정이라
          재인덱싱이 필요 없습니다. <span className="font-medium text-foreground">생성·수정·삭제는 관리자</span>만 가능하며, 일반
          사용자는 조회만 됩니다.
        </p>
      </section>

      <section>
        <Sub icon={GitBranch}>① 목록 — 만들고 살펴보기</Sub>
        <Bullets
          items={[
            <>테이블에 <span className="font-medium text-foreground">이름 · 스테이지 · 활성 버전(v활성/전체) · 검색 방식</span>이 표시됩니다. 이름을 누르면 상세 화면으로 이동합니다.</>,
            <><span className="font-medium text-foreground">파이프라인 생성</span> 버튼으로 이름을 정해 만들면, <span className="font-medium text-foreground">현재 전역 설정값으로 v1</span>이 자동 생성됩니다.</>,
            <>이후 상세 화면에서 설정을 바꿔 저장할 때마다 <span className="font-medium text-foreground">새 버전</span>이 쌓입니다.</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={SlidersHorizontal}>② 설정 편집 — 프리셋으로 시작</Sub>
        <p className="mb-2 text-muted-foreground">
          상세 화면의 <span className="font-medium text-foreground">프리셋</span>은 검색·리랭크·생성 값을 한 번에 채웁니다(생성
          모델은 건드리지 않아 전역/사용자 값이 유지됩니다). 값을 직접 바꾸면 <span className="font-medium text-foreground">사용자
          지정</span>으로 표시됩니다.
        </p>
        <StrategyTable rows={PRESET_ROWS} col1="프리셋" />
      </section>

      <section>
        <Sub icon={Settings2}>③ 고급 설정 — 직접 조정</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">검색</span> — 방식(하이브리드/벡터/렉시컬), 거리 메트릭(컬렉션 상속/cosine/l2/inner_product), <span className="font-mono text-sm">top_k · vector_k · lexical_k · rrf_k</span>.</>,
            <><span className="font-medium text-foreground">리랭크</span> — 사용 여부, provider(none/llm/local/cross_encoder), <span className="font-mono text-sm">top_n</span>.</>,
            <><span className="font-medium text-foreground">생성</span> — 모델(빈 값=전역), <span className="font-mono text-sm">max_tokens · temperature</span>.</>,
            <>아래 <span className="font-medium text-foreground">새 버전으로 저장</span>을 누르면 변경이 새 버전으로 기록됩니다.</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={History}>④ 버전 · 롤백 · diff</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">버전</span> — 설정을 바꿀 때마다 새 버전으로 남습니다. <span className="font-medium text-foreground">활성 버전</span>이 실제로 사용됩니다.</>,
            <><span className="font-medium text-foreground">롤백</span> — 버전 목록에서 <span className="font-medium text-foreground">이 버전 활성화</span>로 이전 설정으로 즉시 되돌립니다.</>,
            <><span className="font-medium text-foreground">diff</span> — 두 버전을 골라 설정 차이(<span className="font-mono text-sm">경로: 이전값 → 새값</span>)를 확인합니다.</>,
            <><span className="font-medium text-foreground">단계(stage)</span> — dev/staging/prod로 실험 설정과 검증된 운영 설정을 구분합니다(버전을 만들지 않는 메타 변경).</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={GitCompare}>⑤ 버전 비교 (실험)</Sub>
        <p className="text-muted-foreground">
          <span className="font-medium text-foreground">동일 질의를 두 버전으로 검색</span>해 결과를 나란히 비교합니다. 지식베이스와
          버전 A·B를 고르고 질문을 입력하면, 버전별 검색 결과(문서명 · 스코어 · 본문 미리보기)를 좌우로 보여줍니다. 설정을
          확정하기 전에 실제 검색 품질을 눈으로 확인하는 용도입니다.
        </p>
      </section>

      <Callout>
        권장 흐름: <span className="font-medium text-foreground">생성(v1) → 프리셋 선택·조정 → 새 버전 저장 → 버전 비교로
        검증</span>. 객관적으로 비교하려면 <Link href="/dashboard/evaluation" className="text-primary hover:underline">평가</Link>로
        버전별 점수(Hit Rate·MRR)를 측정한 뒤, 가장 좋은 버전을 활성화하십시오. 문제가 생기면 언제든 이전 버전으로 롤백할 수 있습니다.
      </Callout>
    </TabShell>
  )
}
