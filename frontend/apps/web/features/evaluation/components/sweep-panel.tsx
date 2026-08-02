/**
 * 설정 스윕 패널 — 데이터셋 상세에 임베드.
 *
 * 탐색 공간(쿼리 축 + 인덱스 축)을 토글로 정의해 스윕을 시작하고, 진행 중인 스윕을
 * 폴링하며, 완료된 스윕의 리더보드(설정 조합 → 메트릭 랭킹)를 보여준다. 우승(또는 선택)
 * 설정을 컬렉션에 적용할 수 있다.
 */
"use client"

import { useCallback, useEffect, useState } from "react"
import { ChevronDown, ChevronRight, Trophy, Wand2 } from "lucide-react"

import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import { Card, CardContent, CardHeader, CardTitle } from "@workspace/ui/components/card"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
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
import { toast } from "sonner"
import {
  applySweepConfig,
  cancelSweep,
  createSweep,
  getLeaderboard,
  listSweeps,
} from "@/features/evaluation/api"
import type { EvalSweep, Leaderboard, LeaderboardRow, SweepSearchSpace } from "@/features/evaluation/data/schema"

const MODES = [
  { v: "hybrid", l: "하이브리드" },
  { v: "vector", l: "벡터" },
  { v: "lexical", l: "렉시컬" },
]
const TOP_KS = [3, 5, 10]
const PARSE = ["auto", "text", "layout", "docai"]
const CHUNK = ["auto", "recursive", "markdown", "sentence", "paragraph", "section"]
const SIZES = [512, 1000]
const UNITS = ["char", "token"]
const METRICS = [
  { v: "hit_rate", l: "hit@k (검색 적중률)" },
  { v: "mrr", l: "MRR (순위)" },
  { v: "composite", l: "composite (합성)" },
  { v: "faithfulness", l: "faithfulness (judge)" },
  { v: "answer_relevance", l: "answer relevance (judge)" },
]
const STATUS_VARIANT: Record<string, "secondary" | "outline" | "default" | "destructive"> = {
  succeeded: "secondary",
  running: "default",
  indexing: "default",
  judging: "default",
  queued: "outline",
  failed: "destructive",
  canceled: "destructive",
}
const ACTIVE = new Set(["queued", "indexing", "running", "judging"])

/** 토글 가능한 칩 버튼 그룹. */
function ChipGroup<T extends string | number>({
  options,
  selected,
  onToggle,
  labels,
  disabled,
}: {
  options: T[]
  selected: Set<T>
  onToggle: (v: T) => void
  labels?: Record<string, string>
  disabled?: boolean
}) {
  return (
    <div className={`flex flex-wrap gap-1.5 ${disabled ? "opacity-50" : ""}`}>
      {options.map((o) => {
        const on = selected.has(o)
        return (
          <button
            key={String(o)}
            type="button"
            disabled={disabled}
            onClick={() => onToggle(o)}
            className={`rounded-md border px-2.5 py-1 text-xs transition-colors disabled:cursor-not-allowed ${
              on
                ? "border-primary bg-primary text-primary-foreground"
                : "border-input bg-background text-muted-foreground hover:bg-muted"
            }`}
          >
            {labels?.[String(o)] ?? String(o)}
          </button>
        )
      })}
    </div>
  )
}

function useToggleSet<T>(initial: T[]) {
  const [set, setSet] = useState<Set<T>>(new Set(initial))
  const toggle = (v: T) =>
    setSet((prev) => {
      const next = new Set(prev)
      if (next.has(v)) next.delete(v)
      else next.add(v)
      return next
    })
  return [set, toggle] as const
}

function num(v: number | null, d = 3): string {
  return v === null || v === undefined ? "—" : v.toFixed(d)
}

export function SweepPanel({
  datasetId,
  defaultCollectionId,
}: {
  datasetId: number
  defaultCollectionId: number | null
}) {
  const [sweeps, setSweeps] = useState<EvalSweep[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)
  const [board, setBoard] = useState<Leaderboard | null>(null)
  const [creating, setCreating] = useState(false)

  // 폼 상태
  const [name, setName] = useState("")
  const [primary, setPrimary] = useState("hit_rate")
  const [judge, setJudge] = useState(false)
  const [judgeTopN, setJudgeTopN] = useState(3) // judge 게이팅 상위 N개
  const [holdoutPct, setHoldoutPct] = useState(0) // 홀드아웃 비율(%)
  const [maxRuns, setMaxRuns] = useState(64)
  const [modes, toggleMode] = useToggleSet<string>(["hybrid", "vector", "lexical"])
  const [topks, toggleTopk] = useToggleSet<number>([3, 5])
  const [rerankOn, toggleRerank] = useToggleSet<string>(["off"])
  // 인덱스 축(고급, P2 — 재인덱싱)
  const [showIndex, setShowIndex] = useState(false)
  const [parses, toggleParse] = useToggleSet<string>([])
  const [chunks, toggleChunk] = useToggleSet<string>([])
  const [sizes, toggleSize] = useToggleSet<number>([])
  const [units, toggleUnit] = useToggleSet<string>([])

  const refresh = useCallback(async () => {
    try {
      setSweeps(await listSweeps(datasetId))
    } catch {
      /* noop */
    }
  }, [datasetId])

  useEffect(() => {
    refresh()
  }, [refresh])

  // 활성 스윕이 있으면 폴링
  useEffect(() => {
    if (!sweeps.some((s) => ACTIVE.has(s.status))) return
    const t = setInterval(() => {
      refresh()
      if (expanded) getLeaderboard(expanded).then(setBoard).catch(() => {})
    }, 2000)
    return () => clearInterval(t)
  }, [sweeps, expanded, refresh])

  function buildSearchSpace(): { space: SweepSearchSpace; estimate: number } {
    const query_axis: Record<string, (string | number | boolean)[]> = {}
    if (modes.size) query_axis.mode = [...modes]
    if (topks.size) query_axis.top_k = [...topks]
    const rr: boolean[] = []
    if (rerankOn.has("off")) rr.push(false)
    if (rerankOn.has("on")) rr.push(true)
    if (rr.length) query_axis.rerank = rr

    const index_axis: Record<string, (string | number | boolean)[]> = {}
    if (parses.size) index_axis.parse_strategy = [...parses]
    if (chunks.size) index_axis.chunk_strategy = [...chunks]
    if (sizes.size) index_axis.chunk_size = [...sizes]
    if (units.size) index_axis.chunk_unit = [...units]

    const space: SweepSearchSpace = { query_axis }
    if (Object.keys(index_axis).length) space.index_axis = index_axis

    const prod = (o: object) =>
      Object.values(o).reduce((a, v) => a * (Array.isArray(v) ? v.length || 1 : 1), 1)
    const estimate = prod(query_axis) * (Object.keys(index_axis).length ? prod(index_axis) : 1)
    return { space, estimate }
  }

  const { space, estimate } = buildSearchSpace()
  const indexSelected = parses.size + chunks.size + sizes.size + units.size > 0
  const canStart = modes.size > 0 && topks.size > 0 && estimate <= maxRuns

  async function handleCreate() {
    setCreating(true)
    try {
      const sw = await createSweep(datasetId, {
        name: name.trim() || `스윕 ${new Date().toISOString().slice(0, 16).replace("T", " ")}`,
        base_collection_id: defaultCollectionId,
        search_space: space,
        primary_metric: primary,
        judge,
        judge_top_n: judge ? judgeTopN : null,
        holdout_ratio: holdoutPct > 0 ? holdoutPct / 100 : 0,
        max_runs: maxRuns,
      })
      toast.success(`스윕 시작 — ${sw.total_runs}개 조합`)
      setName("")
      await refresh()
      setExpanded(sw.sweep_id)
      getLeaderboard(sw.sweep_id).then(setBoard).catch(() => {})
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "스윕 생성 실패")
    } finally {
      setCreating(false)
    }
  }

  async function toggleExpand(sweepId: string) {
    if (expanded === sweepId) {
      setExpanded(null)
      setBoard(null)
      return
    }
    setExpanded(sweepId)
    setBoard(null)
    try {
      setBoard(await getLeaderboard(sweepId))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "리더보드 조회 실패")
    }
  }

  async function handleApply(sweepId: string, row: LeaderboardRow) {
    try {
      const r = await applySweepConfig(sweepId, row.run_id)
      const q = r.recommended_runtime as Record<string, unknown>
      const runtime = `mode=${q.mode}, top_k=${q.top_k}, rerank=${q.rerank}`
      if (r.reindexed) {
        toast.success(`인덱스 설정 적용 + 재인덱싱 시작 (${r.applied_fields.join(", ")}). 권장 검색: ${runtime}`)
      } else {
        toast.success(`권장 검색 설정: ${runtime} (인덱스 변경 없음)`)
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "적용 실패")
    }
  }

  async function handleCancel(sweepId: string) {
    try {
      await cancelSweep(sweepId)
      toast.success("스윕을 취소했습니다.")
      await refresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "취소 실패")
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* 생성 폼 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm font-medium">
            <Wand2 className="size-4" /> 설정 스윕 (옵션 조합 자동 탐색)
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="grid gap-3 sm:grid-cols-[1fr_auto_auto]">
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">이름</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="(자동 생성)" />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">기준 메트릭</Label>
              <Select value={primary} onValueChange={setPrimary}>
                <SelectTrigger className="w-52"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {METRICS.map((m) => (
                    <SelectItem key={m.v} value={m.v}>{m.l}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">최대 Run</Label>
              <Input
                type="number"
                className="w-24"
                value={maxRuns}
                onChange={(e) => setMaxRuns(Math.max(1, Number(e.target.value) || 1))}
              />
            </div>
          </div>

          {/* 쿼리 축 */}
          <div className="rounded-md border p-3">
            <p className="mb-2 text-xs font-medium">쿼리 축 <span className="text-muted-foreground">(재인덱싱 불필요 · 싸고 효과 큼)</span></p>
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-3">
                <span className="w-16 text-xs text-muted-foreground">검색 방식</span>
                <ChipGroup options={MODES.map((m) => m.v)} selected={modes} onToggle={toggleMode}
                  labels={Object.fromEntries(MODES.map((m) => [m.v, m.l]))} />
              </div>
              <div className="flex items-center gap-3">
                <span className="w-16 text-xs text-muted-foreground">top_k</span>
                <ChipGroup options={TOP_KS} selected={topks} onToggle={toggleTopk} />
              </div>
              <div className="flex items-center gap-3">
                <span className="w-16 text-xs text-muted-foreground">리랭크</span>
                <ChipGroup options={["off", "on"]} selected={rerankOn} onToggle={toggleRerank}
                  labels={{ off: "끄기", on: "켜기" }} />
              </div>
            </div>
          </div>

          {/* 인덱스 축(고급) */}
          <div className="rounded-md border p-3">
            <button type="button" className="flex items-center gap-1 text-xs font-medium"
              onClick={() => setShowIndex((v) => !v)}>
              {showIndex ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
              인덱스 축 <span className="text-muted-foreground">(재인덱싱 필요 · 비쌈)</span>
            </button>
            {showIndex && (
              <div className="mt-2 flex flex-col gap-2">
                <div className="flex items-center gap-3">
                  <span className="w-16 text-xs text-muted-foreground">파싱</span>
                  <ChipGroup options={PARSE} selected={parses} onToggle={toggleParse} />
                </div>
                <div className="flex items-center gap-3">
                  <span className="w-16 text-xs text-muted-foreground">청킹</span>
                  <ChipGroup options={CHUNK} selected={chunks} onToggle={toggleChunk} />
                </div>
                <div className="flex items-center gap-3">
                  <span className="w-16 text-xs text-muted-foreground">청크 크기</span>
                  <ChipGroup options={SIZES} selected={sizes} onToggle={toggleSize} />
                </div>
                <div className="flex items-center gap-3">
                  <span className="w-16 text-xs text-muted-foreground">단위</span>
                  <ChipGroup options={UNITS} selected={units} onToggle={toggleUnit} />
                </div>
                <p className="text-xs text-muted-foreground">
                  선택한 인덱스 조합마다 임시 컬렉션을 만들어 원본 문서를 재인덱싱한 뒤 평가합니다.
                  조합이 늘수록 인덱싱 시간·비용이 크게 증가하니 후보를 좁게 잡으세요.
                  스윕이 끝나면 임시 컬렉션은 자동 정리됩니다.
                </p>
              </div>
            )}
          </div>

          {/* 신뢰성·비용 (P3) */}
          <div className="rounded-md border p-3">
            <p className="mb-2 text-xs font-medium">신뢰성·비용 <span className="text-muted-foreground">(스마트 탐색 · 홀드아웃)</span></p>
            <div className="flex flex-col gap-2">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={judge} onChange={(e) => setJudge(e.target.checked)} />
                LLM judge 생성 지표(faithfulness 등)
              </label>
              {judge && (
                <div className="flex items-center gap-2 pl-6 text-sm">
                  <span className="text-xs text-muted-foreground">judge 게이팅 — 검색 점수 상위</span>
                  <Input
                    type="number"
                    className="h-7 w-16"
                    value={judgeTopN}
                    min={1}
                    onChange={(e) => setJudgeTopN(Math.max(1, Number(e.target.value) || 1))}
                  />
                  <span className="text-xs text-muted-foreground">개 조합만 judge 실행(비싼 LLM 절감)</span>
                </div>
              )}
              <div className="flex items-center gap-2 text-sm">
                <span className="text-xs text-muted-foreground">홀드아웃</span>
                <Input
                  type="number"
                  className="h-7 w-16"
                  value={holdoutPct}
                  min={0}
                  max={90}
                  onChange={(e) => setHoldoutPct(Math.min(90, Math.max(0, Number(e.target.value) || 0)))}
                />
                <span className="text-xs text-muted-foreground">
                  % 를 검증용으로 분리 — train 으로 선정하고 holdout 으로 일반화 검증(과적합 감지). 0 = 미사용
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <span className={`text-xs ${estimate > maxRuns ? "text-destructive" : "text-muted-foreground"}`}>
              예상 {estimate}개 Run {indexSelected ? "(임시 컬렉션 인덱싱 포함)" : ""}
              {judge && judgeTopN ? ` · judge 상위 ${judgeTopN}개` : ""}
              {holdoutPct > 0 ? ` · holdout ${holdoutPct}%` : ""}
              {estimate > maxRuns ? ` — 최대 ${maxRuns} 초과` : ""}
            </span>
            <Button className="ml-auto" disabled={!canStart || creating} onClick={handleCreate}>
              <Wand2 className="size-4" /> {creating ? "시작 중..." : "스윕 시작"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* 스윕 목록 + 리더보드 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">스윕 결과</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {sweeps.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">아직 스윕이 없습니다.</p>
          ) : (
            sweeps.map((s) => (
              <div key={s.sweep_id} className="rounded-md border">
                <div className="flex items-center gap-2 px-3 py-2">
                  <button type="button" className="flex flex-1 items-center gap-2 text-left"
                    onClick={() => toggleExpand(s.sweep_id)}>
                    {expanded === s.sweep_id ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                    <span className="font-medium">{s.name}</span>
                    <Badge variant={STATUS_VARIANT[s.status] ?? "outline"} className="font-normal">{s.status}</Badge>
                    <span className="text-xs text-muted-foreground">
                      {s.completed_runs}/{s.total_runs} Run · {s.primary_metric}
                    </span>
                  </button>
                  {ACTIVE.has(s.status) && (
                    <Button variant="outline" size="sm" onClick={() => handleCancel(s.sweep_id)}>취소</Button>
                  )}
                </div>

                {expanded === s.sweep_id && (
                  <div className="border-t p-3">
                    {s.error && (
                      <p className="mb-2 rounded border border-destructive/40 bg-destructive/5 px-2 py-1 text-xs text-destructive">
                        {s.error}
                      </p>
                    )}
                    {!board || board.sweep.sweep_id !== s.sweep_id ? (
                      <p className="py-4 text-center text-sm text-muted-foreground">불러오는 중...</p>
                    ) : (
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead className="w-10">#</TableHead>
                            <TableHead>설정 (mode · k · rerank)</TableHead>
                            <TableHead className="text-right">hit@k</TableHead>
                            <TableHead className="text-right">MRR</TableHead>
                            <TableHead className="text-right">faithful</TableHead>
                            <TableHead className="text-right">{board.holdout_ratio > 0 ? "점수(train)" : "점수"}</TableHead>
                            {board.holdout_ratio > 0 && <TableHead className="text-right">holdout</TableHead>}
                            <TableHead className="w-16" />
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {board.rows.map((r) => {
                            const q = r.query_config as Record<string, unknown>
                            const idx = r.index_config as Record<string, unknown>
                            return (
                              <TableRow key={r.run_id} className={r.is_best ? "bg-secondary/40" : ""}>
                                <TableCell className="tabular-nums">
                                  {r.is_best ? <Trophy className="size-3.5 text-amber-500" /> : r.rank}
                                </TableCell>
                                <TableCell className="text-xs">
                                  <span className="font-medium text-black">
                                    {String(q.mode)} · k{String(q.top_k)} · {q.rerank ? "rerank" : "no-rerank"}
                                  </span>
                                  {r.ephemeral && (
                                    <span className="ml-1 text-muted-foreground">
                                      [{String(idx.parse_strategy)}·{String(idx.chunk_strategy)}·{String(idx.chunk_size)}{String(idx.chunk_unit)}]
                                    </span>
                                  )}
                                </TableCell>
                                <TableCell className="text-right tabular-nums">{num(r.hit_rate)}</TableCell>
                                <TableCell className="text-right tabular-nums">{num(r.mrr)}</TableCell>
                                <TableCell className="text-right tabular-nums">
                                  {num(r.faithfulness)}
                                  {r.judged && <span className="ml-1 text-[10px] text-muted-foreground" title="LLM judge 실행됨">J</span>}
                                </TableCell>
                                <TableCell className="text-right font-medium tabular-nums">
                                  {num(r.score)}
                                  {r.overfit && (
                                    <Badge variant="destructive" className="ml-1 px-1 py-0 text-[10px] font-normal" title="train 대비 holdout 점수 격차가 큼 — 과적합 의심">
                                      과적합
                                    </Badge>
                                  )}
                                </TableCell>
                                {board.holdout_ratio > 0 && (
                                  <TableCell className={`text-right tabular-nums ${r.overfit ? "text-destructive" : ""}`}>
                                    {num(r.holdout_score)}
                                  </TableCell>
                                )}
                                <TableCell>
                                  {r.status === "succeeded" && (
                                    <Button variant="ghost" size="sm" onClick={() => handleApply(s.sweep_id, r)}>
                                      적용
                                    </Button>
                                  )}
                                </TableCell>
                              </TableRow>
                            )
                          })}
                        </TableBody>
                      </Table>
                    )}
                  </div>
                )}
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  )
}
