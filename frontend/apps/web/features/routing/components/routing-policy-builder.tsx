// 라우팅 정책 빌더 — 기본 설정(mode/폴백/검토임계) + stage(라우터) 목록 편집.
// stage 설정은 빌트인 라우터(filename_rule/metadata_match)에 맞춘 규칙 표 편집기를 제공하고,
// 그 외 라우터는 config_schema 를 힌트로 한 JSON 편집기로 폴백한다(레지스트리 확장에 무코드 대응).
"use client"

import { useState, type ReactNode } from "react"
import { ArrowDown, ArrowUp, Check, ChevronsUpDown, HelpCircle, Plus, Trash2, X } from "lucide-react"
import { cn } from "@workspace/ui/lib/utils"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import { Badge } from "@workspace/ui/components/badge"
import { Switch } from "@workspace/ui/components/switch"
import dynamic from "next/dynamic"

import { Textarea } from "@workspace/ui/components/textarea"

// 사용자 정의 함수 코드 편집기 — PII 함수 편집과 동일한 Monaco(Python) 구성.
const MonacoEditor = dynamic(() => import("@monaco-editor/react").then((m) => m.default), { ssr: false })

import { ServiceEndpointPicker } from "@/features/deploy/components/service-endpoint-picker"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@workspace/ui/components/command"
import { Popover, PopoverContent, PopoverTrigger } from "@workspace/ui/components/popover"
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
import { Tooltip, TooltipContent, TooltipTrigger } from "@workspace/ui/components/tooltip"
import type { RouterInfo, RoutingPolicyConfig, RoutingStage } from "../data/schema"

// 항목 옆 ? 아이콘 + 상세 설명 tooltip.
function Help({ children }: { children: ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button type="button" className="text-muted-foreground hover:text-foreground" aria-label="설명">
          <HelpCircle className="size-3.5" />
        </button>
      </TooltipTrigger>
      {/* TooltipContent 가 inline-flex(gap)라 자식 노드가 각각 flex 아이템이 된다.
          단일 블록으로 감싸 인라인 내용도 연속 문자열로 흐르게 한다. */}
      <TooltipContent className="max-w-xs text-sm">
        <div className="flex flex-col gap-1.5 leading-relaxed">{children}</div>
      </TooltipContent>
    </Tooltip>
  )
}

// 라벨 + ? 아이콘(필드용).
function FieldLabel({ children, help }: { children: ReactNode; help: ReactNode }) {
  return (
    <Label className="flex items-center gap-1 text-sm text-muted-foreground">
      {children}
      <Help>{help}</Help>
    </Label>
  )
}

// 테이블 헤더 셀 라벨 + ? 아이콘.
function HeadLabel({ children, help }: { children: ReactNode; help: ReactNode }) {
  return (
    <span className="flex items-center gap-1">
      {children}
      <Help>{help}</Help>
    </span>
  )
}

// 섹션 제목 + ? 아이콘.
function SectionTitle({ children, help, count }: { children: ReactNode; help?: ReactNode; count?: number }) {
  return (
    <div className="flex items-center gap-1">
      <h3 className="text-sm font-semibold">{children}{count != null && <span className="ml-1 text-muted-foreground">({count})</span>}</h3>
      {help && <Help>{help}</Help>}
    </div>
  )
}

const NONE = "__none__"

// 라우터별 상세 설명(카드 헤더 ? tooltip). 레지스트리의 짧은 description 보다 풍부한 안내.
const ROUTER_INFO: Record<string, ReactNode> = {
  filename_rule: (
    <>
      <span><b>파일명 규칙</b> — 파일명/경로에 지정한 <b>키워드(부분일치)</b> 또는 <b>정규식</b>이 있으면 해당 컬렉션으로 라우팅합니다.</span>
      <span>예: 파일명에 &lsquo;제안요청서&rsquo; 포함 → RFP 지식베이스.</span>
    </>
  ),
  extension_rule: (
    <>
      <span><b>확장자 규칙</b> — 파일 <b>확장자</b>(점·대소문자 무시)로 컬렉션을 정합니다.</span>
      <span>예: pdf → 문서고, pptx → 발표자료고.</span>
    </>
  ),
  metadata_match: (
    <>
      <span><b>메타데이터 매칭</b> — 인제스천 메타추출·자동분류가 채운 <b>필드 값</b>(doc_type·부서·언어 등)이 지정 값과 같으면 해당 컬렉션으로 라우팅합니다.</span>
      <span>예: doc_type=rfp → RFP 지식베이스.</span>
    </>
  ),
  path_rule: (
    <>
      <span><b>경로 규칙</b> — 스토리지 소스에서 가져온(pull) 문서의 <b>소스 내 경로</b>가 패턴(프리픽스·글롭·정규식)과 맞으면 해당 컬렉션으로 라우팅합니다. 소스 이름으로도 거를 수 있습니다.</span>
      <span>예: contracts/ 아래 → 계약 지식베이스. 일반 업로드(경로 없음)에는 매칭되지 않습니다.</span>
    </>
  ),
}

// 라우터 id 옆 ? 설명 tooltip(트레이스 등 다른 화면에서도 재사용). 설명 없으면 표시 안 함.
export function RouterHelp({ id }: { id: string }) {
  const info = ROUTER_INFO[id]
  if (!info) return null
  return <Help>{info}</Help>
}

type CollectionOpt = { id: number; name: string }

type Props = {
  config: RoutingPolicyConfig
  onChange: (c: RoutingPolicyConfig) => void
  routers: RouterInfo[]
  collections: CollectionOpt[]
  sources?: string[] // 등록된 스토리지 소스 이름(path_rule 의 소스 필터 콤보용)
  disabled?: boolean
}

export function RoutingPolicyBuilder({ config, onChange, routers, collections, sources, disabled }: Props) {
  // 확신도 입력 모드 — 기본은 의미 등급(셀렉트), 고급은 숫자 직접 입력.
  const [advancedScore, setAdvancedScore] = useState(false)
  function patch(p: Partial<RoutingPolicyConfig>) {
    onChange({ ...config, ...p })
  }
  function patchStage(idx: number, p: Partial<RoutingStage>) {
    onChange({ ...config, stages: config.stages.map((s, i) => (i === idx ? { ...s, ...p } : s)) })
  }
  function addStage() {
    const first = routers[0]?.id ?? "filename_rule"
    patch({ stages: [...config.stages, { id: first, config: {}, weight: 1, min_confidence: 0.7 }] })
  }
  function removeStage(idx: number) {
    patch({ stages: config.stages.filter((_, i) => i !== idx) })
  }
  function moveStage(idx: number, dir: -1 | 1) {
    const next = [...config.stages]
    const j = idx + dir
    if (j < 0 || j >= next.length) return
    ;[next[idx], next[j]] = [next[j]!, next[idx]!]
    patch({ stages: next })
  }

  return (
    <div className="flex flex-col gap-6">
      {/* ── 기본 설정 ─────────────────────────────────────────────── */}
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <SectionTitle help={
            <>
              <span>정책 전반에 적용되는 설정입니다. 아래 라우터 단계의 후보를 어떻게 합치고, 실패·저신뢰를 어떻게 처리할지 정합니다.</span>
            </>
          }>기본 설정</SectionTitle>
          {/* 확신도·검토 임계 공통 — 기본은 의미 등급 셀렉트, 고급은 0~1 숫자 직접 입력 */}
          <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <Switch checked={advancedScore} onCheckedChange={setAdvancedScore} /> 숫자 입력(고급)
          </label>
        </div>
        <div className="overflow-hidden rounded-md border bg-background">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-1/3">
                  <HeadLabel help={
                    <>
                      <span>여러 라우터 단계의 결과를 합치는 방식입니다.</span>
                      <span><b>first_match</b> — 단계를 위에서부터 평가해, 최고 후보 점수가 그 단계의 &lsquo;채택 임계&rsquo; 이상이면 그 컬렉션으로 <b>즉시 확정</b>(나머지는 기록만). 규칙 우선순위가 명확할 때.</span>
                      <span><b>weighted_vote</b> — 모든 단계를 실행해 컬렉션별로 <b>(점수 × 가중치)를 합산</b>하고 최고 득점 컬렉션 선택. 여러 약한 신호를 종합할 때. 신뢰도 = 합산 ÷ 가중치 합.</span>
                    </>
                  }>조합 방식(mode)</HeadLabel>
                </TableHead>
                <TableHead className="w-1/3">
                  <HeadLabel help={
                    <>
                      <span>어떤 라우터도 매칭하지 못했을 때(또는 first_match에서 모든 단계가 임계 미달일 때) 보낼 <b>기본 지식베이스</b>입니다.</span>
                      <span><b>없음</b>이면 매칭 실패 시 인테이크가 <b>422로 거부</b>됩니다. 미분류/Inbox 컬렉션 지정을 권장합니다. 폴백으로 간 문서는 &lsquo;검토 필요&rsquo;로 표시됩니다.</span>
                    </>
                  }>폴백 컬렉션</HeadLabel>
                </TableHead>
                <TableHead className="w-1/3">
                  <HeadLabel help={
                    <>
                      <span>최종 <b>신뢰도가 이 값 미만</b>이면 결정은 유지하되 <b>&lsquo;검토 필요&rsquo;</b>로 표시합니다(결정 로그 review=true).</span>
                      <span>폴백으로 보낸 문서도 검토 대상입니다. 0~1 범위이며, 낮출수록 검토 표시가 줄어듭니다. 검토 큐에서 잘못 배분된 문서를 골라내는 기준입니다.</span>
                    </>
                  }>검토 임계(review_below)</HeadLabel>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow className="hover:bg-transparent">
                <TableCell className="align-top">
                  <Select value={config.mode} onValueChange={(v) => patch({ mode: v as RoutingPolicyConfig["mode"] })} disabled={disabled}>
                    <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="first_match">first_match — 위에서부터 첫 확정</SelectItem>
                      <SelectItem value="weighted_vote">weighted_vote — 가중 합산</SelectItem>
                    </SelectContent>
                  </Select>
                </TableCell>
                <TableCell className="align-top">
                  <Select
                    value={config.fallback_collection_id != null ? String(config.fallback_collection_id) : NONE}
                    onValueChange={(v) => patch({ fallback_collection_id: v === NONE ? null : Number(v) })}
                    disabled={disabled}
                  >
                    <SelectTrigger className="w-full"><SelectValue placeholder="없음" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NONE}>없음(실패 시 422)</SelectItem>
                      {collections.map((c) => (
                        <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </TableCell>
                <TableCell className="align-top">
                  {advancedScore ? (
                    <Input
                      type="number" step="0.05" min={0} max={1} className="w-full"
                      value={config.review_below}
                      onChange={(e) => patch({ review_below: clamp01(parseFloat(e.target.value)) })}
                      disabled={disabled}
                    />
                  ) : (
                    <ReviewSelect value={config.review_below} disabled={disabled}
                      onChange={(v) => patch({ review_below: v })} />
                  )}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </section>

      {/* ── 라우터 단계 ───────────────────────────────────────────── */}
      <section className="flex flex-col gap-3 border-t pt-5">
        <div className="flex items-center justify-between">
          <SectionTitle count={config.stages.length} help={
            <>
              <span>문서를 보고 후보 컬렉션을 제안하는 <b>라우터들의 순서 있는 목록</b>입니다.</span>
              <span>first_match에서는 위에서부터 평가하므로 <b>순서가 우선순위</b>입니다(↑↓로 조정). weighted_vote에서는 순서와 무관하게 모두 합산합니다. 단계가 없으면 모든 문서가 폴백으로 갑니다.</span>
            </>
          }>라우터 단계</SectionTitle>
          {!disabled && (
            <Button size="sm" variant="outline" onClick={addStage} disabled={routers.length === 0}>
              <Plus className="size-4" /> 단계 추가
            </Button>
          )}
        </div>

        {config.stages.length === 0 ? (
          <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
            단계가 없습니다 — 모든 문서가 폴백 컬렉션으로 갑니다. &lsquo;단계 추가&rsquo;로 라우터를 구성하십시오.
          </p>
        ) : (
          <div className="flex flex-col gap-3">
            {config.stages.map((stage, idx) => {
              const meta = routers.find((r) => r.id === stage.id)
              return (
                <div key={idx} className="overflow-hidden rounded-lg border">
                  {/* 헤더바: 번호 · 라우터 / 파라미터 · 액션 */}
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/40 px-3 py-2">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="text-sm tabular-nums">#{idx + 1}</Badge>
                      <Select value={stage.id} onValueChange={(v) => patchStage(idx, { id: v, config: {} })} disabled={disabled}>
                        <SelectTrigger className="h-8 w-52"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {routers.map((r) => (
                            <SelectItem key={r.id} value={r.id} disabled={!r.available}>
                              {r.label}{!r.available ? " (미가용)" : ""}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Help>{ROUTER_INFO[stage.id] ?? <span>{meta?.description ?? "이 라우터의 설명이 없습니다."}</span>}</Help>
                      <StageOutcomeBadge config={config} stage={stage} />
                    </div>
                    <div className="flex items-center gap-3">
                      {config.mode === "weighted_vote" && (
                        <div className="flex items-center gap-1.5">
                          <span className="text-sm text-muted-foreground">가중치</span>
                          <Input type="number" step="0.5" min={0} className="h-8 w-20 text-sm" value={stage.weight}
                            onChange={(e) => patchStage(idx, { weight: Math.max(0, parseFloat(e.target.value) || 0) })} disabled={disabled} />
                          <Help><span>weighted_vote에서 이 라우터 점수에 곱할 <b>비중</b>입니다. 신뢰도 = Σ(점수 × 가중치) ÷ Σ(가중치). 더 신뢰하는 라우터에 큰 값을 주십시오.</span></Help>
                        </div>
                      )}
                      {config.mode === "first_match" && (
                        <div className="flex items-center gap-1.5">
                          <span className="text-sm text-muted-foreground">채택 임계</span>
                          <Input type="number" step="0.05" min={0} max={1} className="h-8 w-20 text-sm" value={stage.min_confidence}
                            onChange={(e) => patchStage(idx, { min_confidence: clamp01(parseFloat(e.target.value)) })} disabled={disabled} />
                          <Help><span>first_match에서 이 단계의 <b>최고 후보 점수가 이 값 이상</b>이어야 채택하고 즉시 확정합니다. 미만이면 다음 단계로 넘어갑니다(0~1, 예: 0.7).</span></Help>
                        </div>
                      )}
                      {!disabled && (
                        <div className="flex gap-0.5">
                          <Button variant="ghost" size="sm" className="h-8 px-2" onClick={() => moveStage(idx, -1)} disabled={idx === 0}><ArrowUp className="size-4" /></Button>
                          <Button variant="ghost" size="sm" className="h-8 px-2" onClick={() => moveStage(idx, 1)} disabled={idx === config.stages.length - 1}><ArrowDown className="size-4" /></Button>
                          <Button variant="ghost" size="sm" className="h-8 px-2 text-muted-foreground" onClick={() => removeStage(idx)}><Trash2 className="size-4" /></Button>
                        </div>
                      )}
                    </div>
                  </div>
                  {/* 본문: 설정(설명은 헤더 ? tooltip 으로 이동) */}
                  <div className="p-3">
                    <StageConfigEditor stage={stage} collections={collections} sources={sources} disabled={disabled}
                      advancedScore={advancedScore} onChange={(cfg) => patchStage(idx, { config: cfg })} />
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </section>
    </div>
  )
}

function clamp01(n: number): number {
  if (Number.isNaN(n)) return 0
  return Math.max(0, Math.min(1, n))
}

// ---------------------------------------------------------------------------
// 확신도(점수) — 숫자 대신 의미 등급으로 입력 + 단독 매칭 결과 미리보기
// ---------------------------------------------------------------------------

// 규칙 미지정 시 백엔드가 쓰는 라우터별 기본 확신도(빌트인 route() 의 기본값과 일치).
const ROUTER_DEFAULT_SCORE: Record<string, number> = {
  filename_rule: 0.9,
  extension_rule: 0.9,
  metadata_match: 0.8,
  path_rule: 0.95,
}

// 의미 등급 — 내부 저장은 지금과 동일한 숫자(하위호환). "0.95 vs 0.9" 를 사용자가 발명하지
// 않도록 어휘로 고르게 한다. 정확한 수치가 필요하면 '숫자 입력(고급)' 토글로 전환.
const SCORE_LEVELS: { label: string; value: number }[] = [
  { label: "확실", value: 0.95 },
  { label: "높음", value: 0.85 },
  { label: "보통", value: 0.7 },
  { label: "낮음", value: 0.5 },
]

const SCORE_DEFAULT = "__default__"

function ScoreSelect({ value, defaultScore, onChange, disabled }: {
  value: number | undefined
  defaultScore: number
  onChange: (v: number | undefined) => void
  disabled?: boolean
}) {
  const matched = value != null && SCORE_LEVELS.some((l) => Math.abs(l.value - value) < 1e-9)
  const current = value == null ? SCORE_DEFAULT : String(value)
  return (
    <Select
      value={current}
      onValueChange={(v) => onChange(v === SCORE_DEFAULT ? undefined : parseFloat(v))}
      disabled={disabled}
    >
      <SelectTrigger className="h-8 w-full text-sm"><SelectValue /></SelectTrigger>
      <SelectContent>
        <SelectItem value={SCORE_DEFAULT}>기본 ({defaultScore.toFixed(2)})</SelectItem>
        {SCORE_LEVELS.map((l) => (
          <SelectItem key={l.value} value={String(l.value)}>{l.label} ({l.value.toFixed(2)})</SelectItem>
        ))}
        {/* 고급 모드에서 직접 입력한 값 — 등급에 없더라도 그대로 표시(정보 손실 방지) */}
        {value != null && !matched && (
          <SelectItem value={String(value)}>직접 입력 ({value})</SelectItem>
        )}
      </SelectContent>
    </Select>
  )
}

// 검토 임계(review_below)도 같은 어휘로 — 저장은 숫자(하위호환), 고급 토글에서 숫자 입력.
// 양 끝단(검토 안 함/항상 검토)은 자동 수집 정착기 운영 시나리오를 셀렉트 한 번으로 표현한다.
const REVIEW_LEVELS: { label: string; value: number }[] = [
  { label: "검토 표시 안 함", value: 0 },
  { label: "'낮음' 이상이면 통과 (기본)", value: 0.5 },
  { label: "'보통' 이상이면 통과", value: 0.7 },
  { label: "'높음' 이상이면 통과", value: 0.85 },
  { label: "항상 검토", value: 1 },
]

function ReviewSelect({ value, onChange, disabled }: {
  value: number
  onChange: (v: number) => void
  disabled?: boolean
}) {
  const matched = REVIEW_LEVELS.some((l) => Math.abs(l.value - value) < 1e-9)
  return (
    <Select value={String(value)} onValueChange={(v) => onChange(parseFloat(v))} disabled={disabled}>
      <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
      <SelectContent>
        {REVIEW_LEVELS.map((l) => (
          <SelectItem key={l.value} value={String(l.value)}>{l.label}</SelectItem>
        ))}
        {!matched && <SelectItem value={String(value)}>직접 입력 ({value})</SelectItem>}
      </SelectContent>
    </Select>
  )
}

// "이 단계만 매칭됐을 때" 최종 신뢰도와 그 결과(확정/검토/채택 불가)를 즉석 계산한다.
// weighted_vote 는 Σ(점수×가중치)÷Σ가중치 정규화 때문에 단독 매칭이 크게 희석된다 —
// 사용자가 이 상호작용을 암산하지 않도록 결과를 미리 보여주는 것이 목적.
function stageSoloOutcome(config: RoutingPolicyConfig, stage: RoutingStage) {
  const rules = (stage.config.rules as { score?: number }[] | undefined) ?? []
  const def = ROUTER_DEFAULT_SCORE[stage.id] ?? 0.9
  const score = rules.length ? Math.max(...rules.map((r) => r.score ?? def)) : def
  if (config.mode === "weighted_vote") {
    const wsum = config.stages.reduce((a, s) => a + (s.weight || 0), 0)
    const conf = wsum > 0 ? (score * (stage.weight || 0)) / wsum : 0
    return { conf, status: conf < config.review_below ? ("review" as const) : ("ok" as const) }
  }
  if (score < stage.min_confidence) return { conf: score, status: "ignored" as const }
  return { conf: score, status: score < config.review_below ? ("review" as const) : ("ok" as const) }
}

function StageOutcomeBadge({ config, stage }: { config: RoutingPolicyConfig; stage: RoutingStage }) {
  const o = stageSoloOutcome(config, stage)
  const badge =
    o.status === "ignored" ? (
      <Badge variant="destructive" className="text-sm font-normal">채택 임계 미달</Badge>
    ) : o.status === "review" ? (
      <Badge variant="warning" className="text-sm font-normal">단독 매칭 ≈{o.conf.toFixed(2)} · 검토 필요</Badge>
    ) : (
      <Badge variant="success" className="text-sm font-normal">단독 매칭 ≈{o.conf.toFixed(2)} · 확정</Badge>
    )
  return (
    <Tooltip>
      <TooltipTrigger asChild>{badge}</TooltipTrigger>
      <TooltipContent className="max-w-xs text-sm">
        <div className="flex flex-col gap-1.5 leading-relaxed">
          {o.status === "ignored" ? (
            <span>이 단계의 최고 확신도({o.conf.toFixed(2)})가 <b>채택 임계({stage.min_confidence})보다 낮아</b>, first_match 에서 매칭돼도 항상 통과(무시)됩니다. 확신도를 올리거나 임계를 낮추십시오.</span>
          ) : config.mode === "weighted_vote" ? (
            <>
              <span><b>이 단계만 매칭됐을 때</b>의 최종 신뢰도입니다: 최고 확신도 × 가중치 ÷ 가중치 합 ≈ {o.conf.toFixed(2)}.</span>
              <span>{o.status === "review"
                ? <>검토 임계({config.review_below}) 미만이라 이 단계 단독으로 배분된 문서는 <b>&lsquo;검토 필요&rsquo;</b>로 표시됩니다. 확실한 규칙이라면 가중치를 키우십시오.</>
                : <>검토 임계({config.review_below}) 이상이라 이 단계 단독으로도 검토 표시 없이 확정됩니다.</>}</span>
            </>
          ) : (
            <span>first_match 에서 이 단계가 채택되면 신뢰도는 최고 확신도({o.conf.toFixed(2)})이며, {o.status === "review"
              ? <>검토 임계({config.review_below}) 미만이라 <b>&lsquo;검토 필요&rsquo;</b>로 표시됩니다.</>
              : <>검토 표시 없이 확정됩니다.</>}</span>
          )}
        </div>
      </TooltipContent>
    </Tooltip>
  )
}

// ---------------------------------------------------------------------------
// stage 별 config 편집기
// ---------------------------------------------------------------------------

type CfgProps = {
  stage: RoutingStage
  collections: CollectionOpt[]
  sources?: string[]
  disabled?: boolean
  advancedScore?: boolean
  onChange: (cfg: Record<string, unknown>) => void
}

function StageConfigEditor({ stage, collections, sources, disabled, advancedScore, onChange }: CfgProps) {
  if (stage.id === "filename_rule") return <FilenameRuleEditor {...{ stage, collections, disabled, advancedScore, onChange }} />
  if (stage.id === "extension_rule") return <ExtensionRuleEditor {...{ stage, collections, disabled, advancedScore, onChange }} />
  if (stage.id === "metadata_match") return <MetadataMatchEditor {...{ stage, collections, disabled, advancedScore, onChange }} />
  if (stage.id === "path_rule") return <PathRuleEditor {...{ stage, collections, sources, disabled, advancedScore, onChange }} />
  if (stage.id === "custom_function") return <CustomFunctionEditor {...{ stage, collections, disabled, advancedScore, onChange }} />
  if (stage.id === "content_embedding") return <ContentEmbeddingEditor {...{ stage, collections, disabled, advancedScore, onChange }} />
  if (stage.id === "llm_classify") return <LlmClassifyEditor {...{ stage, collections, disabled, advancedScore, onChange }} />
  return <JsonConfigEditor {...{ stage, disabled, onChange }} />
}

type FRule = { keywords?: string[]; collection_id?: number; score?: number }
type ERule = { extensions?: string[]; collection_id?: number; score?: number }
type MRule = { field?: string; equals?: string; collection_id?: number; score?: number }
type PRule = { patterns?: string[]; storage?: string; collection_id?: number; score?: number }

function CollectionPicker({ value, onChange, collections, disabled }: {
  value: number | undefined
  onChange: (id: number) => void
  collections: CollectionOpt[]
  disabled?: boolean
}) {
  return (
    <Select value={value != null ? String(value) : ""} onValueChange={(v) => onChange(Number(v))} disabled={disabled}>
      <SelectTrigger className="h-8"><SelectValue placeholder="컬렉션 선택" /></SelectTrigger>
      <SelectContent>
        {collections.map((c) => <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>)}
      </SelectContent>
    </Select>
  )
}

// 키워드 태그 입력 — 입력 후 Enter(또는 쉼표)로 배지 추가, x 로 삭제. 빈 입력에서 Backspace 면
// 마지막 배지 삭제. 글꼴은 기본형(monospace 아님).
function KeywordsInput({ value, onChange, disabled, placeholder = "키워드 입력 후 Enter" }: {
  value: string[]
  onChange: (v: string[]) => void
  disabled?: boolean
  placeholder?: string
}) {
  const [draft, setDraft] = useState("")
  function add(raw: string) {
    const parts = splitCsv(raw)
    if (!parts.length) return
    const next = [...value]
    for (const p of parts) if (!next.includes(p)) next.push(p)
    onChange(next)
    setDraft("")
  }
  function removeAt(i: number) {
    onChange(value.filter((_, j) => j !== i))
  }
  return (
    <div className={cn(
      "flex min-h-8 flex-wrap items-center gap-1 rounded-md border border-input bg-transparent px-2 py-1 text-sm focus-within:ring-1 focus-within:ring-ring",
      disabled && "opacity-50"
    )}>
      {value.map((kw, i) => (
        <Badge key={i} variant="secondary" className="gap-1 text-sm font-normal">
          {kw}
          {!disabled && (
            <button type="button" aria-label={`${kw} 삭제`} className="text-muted-foreground hover:text-foreground"
              onClick={() => removeAt(i)}>
              <X className="size-3" />
            </button>
          )}
        </Badge>
      ))}
      {!disabled && (
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault()
              add(draft)
            } else if (e.key === "Backspace" && draft === "" && value.length > 0) {
              removeAt(value.length - 1)
            }
          }}
          onBlur={() => { if (draft.trim()) add(draft) }}
          placeholder={value.length ? "" : placeholder}
          className="h-6 min-w-28 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
      )}
    </div>
  )
}

function FilenameRuleEditor({ stage, collections, disabled, advancedScore, onChange }: CfgProps) {
  const match = (stage.config.match as string) || "substring"
  const rules = (stage.config.rules as FRule[]) || []
  const setRules = (next: FRule[]) => onChange({ ...stage.config, match, rules: next })
  return (
    <div className="flex flex-col gap-2 rounded-md bg-muted/30 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <span className="text-sm font-medium">규칙</span>
          <Help>
            <span><b>매칭 방식</b> — 부분일치(파일명에 키워드 포함, 대소문자 무시) / 정규식(파이썬 re).</span>
            <span><b>부분일치</b> 모드 — 키워드를 입력 후 Enter 로 배지 추가(하나라도 맞으면 매칭). 예: 제안요청서, rfp</span>
            <span><b>정규식</b> 모드 — 정규표현식 한 개를 입력. 예: <span className="font-mono">rfp[-_]\d+</span></span>
            <span><b>컬렉션</b> — 매칭 시 보낼 지식베이스. <b>확신도</b> — 이 규칙을 얼마나 믿을지(등급 선택, 고급 토글로 숫자 입력). 단계 헤더의 배지가 최종 검토 여부를 미리 보여줍니다.</span>
          </Help>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5">
            <span className="text-sm text-muted-foreground">매칭</span>
            <Select value={match} onValueChange={(v) => onChange({ ...stage.config, match: v, rules })} disabled={disabled}>
              <SelectTrigger className="h-8 w-28"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="substring">부분일치</SelectItem>
                <SelectItem value="regex">정규식</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {!disabled && (
            <Button variant="outline" size="sm" onClick={() => setRules([...rules, {}])}>
              <Plus className="size-3.5" /> 규칙 추가
            </Button>
          )}
        </div>
      </div>
      <div className="overflow-hidden rounded-md border bg-background">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{match === "regex" ? "정규표현식" : "키워드"}</TableHead>
              <TableHead className="w-52">컬렉션</TableHead>
              <TableHead className="w-32">
                <HeadLabel help={
                  <>
                    <span><b>확신도</b> — 이 규칙이 매칭됐을 때 그 배분을 <b>얼마나 믿을지</b>입니다(내부값 0~1). 등급: 확실 0.95 · 높음 0.85 · 보통 0.7 · 낮음 0.5. &lsquo;기본&rsquo;은 라우터별 기본값이며, 정확한 수치는 상단 &lsquo;숫자 입력(고급)&rsquo; 토글로 입력합니다.</span>
                    <span><b>first_match</b> 모드 — 채택된 규칙의 확신도가 <b>그대로 최종 신뢰도</b>가 됩니다. 단계의 채택 임계 미만이면 매칭돼도 무시되고, 검토 임계 미만이면 &lsquo;검토 필요&rsquo;로 표시됩니다.</span>
                    <span><b>weighted_vote</b> 모드 — 최종 신뢰도 = 컬렉션별 <b>Σ(확신도 × 단계 가중치) ÷ 가중치 합</b>. 여러 단계가 같은 컬렉션을 지지할수록 올라가고, 단독 매칭은 희석됩니다 — 단계 헤더의 배지가 &lsquo;이 단계 단독 매칭 시&rsquo; 결과를 미리 계산해 보여줍니다.</span>
                  </>
                }>확신도</HeadLabel>
              </TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rules.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="py-6 text-center text-sm text-muted-foreground">
                  규칙이 없습니다. 우측 위 &lsquo;규칙 추가&rsquo;로 시작하십시오.
                </TableCell>
              </TableRow>
            ) : (
              rules.map((r, i) => (
                <TableRow key={i}>
                  <TableCell className="align-middle">
                    {match === "regex" ? (
                      <Input className="h-8 font-mono text-sm" placeholder="rfp[-_]\d+"
                        value={r.keywords?.[0] ?? ""}
                        onChange={(e) => setRules(rules.map((x, j) => j === i ? { ...x, keywords: e.target.value ? [e.target.value] : [] } : x))}
                        disabled={disabled} />
                    ) : (
                      <KeywordsInput value={r.keywords || []} disabled={disabled}
                        onChange={(kws) => setRules(rules.map((x, j) => j === i ? { ...x, keywords: kws } : x))} />
                    )}
                  </TableCell>
                  <TableCell className="align-middle">
                    <CollectionPicker value={r.collection_id} collections={collections} disabled={disabled}
                      onChange={(id) => setRules(rules.map((x, j) => j === i ? { ...x, collection_id: id } : x))} />
                  </TableCell>
                  <TableCell className="align-middle">
                    {advancedScore ? (
                      <Input className="h-8 text-sm" type="number" step="0.05" min={0} max={1} placeholder="0.9"
                      value={r.score ?? ""}
                      onChange={(e) => setRules(rules.map((x, j) => j === i ? { ...x, score: e.target.value === "" ? undefined : clamp01(parseFloat(e.target.value)) } : x))}
                      disabled={disabled} />
                    ) : (
                      <ScoreSelect value={r.score} defaultScore={0.9} disabled={disabled}
                        onChange={(v) => setRules(rules.map((x, j) => j === i ? { ...x, score: v } : x))} />
                    )}
                  </TableCell>
                  <TableCell className="text-right align-middle">
                    <Button variant="ghost" size="sm" className="h-8 px-1 text-muted-foreground" onClick={() => setRules(rules.filter((_, j) => j !== i))} disabled={disabled}><Trash2 className="size-3.5" /></Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

function ExtensionRuleEditor({ stage, collections, disabled, advancedScore, onChange }: CfgProps) {
  const rules = (stage.config.rules as ERule[]) || []
  const setRules = (next: ERule[]) => onChange({ ...stage.config, rules: next })
  return (
    <div className="flex flex-col gap-2 rounded-md bg-muted/30 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <span className="text-sm font-medium">규칙</span>
          <Help>
            <span><b>확장자</b> — 파일 확장자(점·대소문자 무시). 입력 후 Enter 로 추가, 하나라도 맞으면 매칭. 예: pdf, pptx</span>
            <span><b>컬렉션</b> — 매칭 시 보낼 지식베이스. <b>확신도</b> — 이 규칙을 얼마나 믿을지(등급 선택, 고급 토글로 숫자 입력). 단계 헤더의 배지가 최종 검토 여부를 미리 보여줍니다.</span>
          </Help>
        </div>
        {!disabled && (
          <Button variant="outline" size="sm" onClick={() => setRules([...rules, {}])}>
            <Plus className="size-3.5" /> 규칙 추가
          </Button>
        )}
      </div>
      <div className="overflow-hidden rounded-md border bg-background">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>확장자</TableHead>
              <TableHead className="w-52">컬렉션</TableHead>
              <TableHead className="w-32">
                <HeadLabel help={
                  <>
                    <span><b>확신도</b> — 이 규칙이 매칭됐을 때 그 배분을 <b>얼마나 믿을지</b>입니다(내부값 0~1). 등급: 확실 0.95 · 높음 0.85 · 보통 0.7 · 낮음 0.5. &lsquo;기본&rsquo;은 라우터별 기본값이며, 정확한 수치는 상단 &lsquo;숫자 입력(고급)&rsquo; 토글로 입력합니다.</span>
                    <span><b>first_match</b> 모드 — 채택된 규칙의 확신도가 <b>그대로 최종 신뢰도</b>가 됩니다. 단계의 채택 임계 미만이면 매칭돼도 무시되고, 검토 임계 미만이면 &lsquo;검토 필요&rsquo;로 표시됩니다.</span>
                    <span><b>weighted_vote</b> 모드 — 최종 신뢰도 = 컬렉션별 <b>Σ(확신도 × 단계 가중치) ÷ 가중치 합</b>. 여러 단계가 같은 컬렉션을 지지할수록 올라가고, 단독 매칭은 희석됩니다 — 단계 헤더의 배지가 &lsquo;이 단계 단독 매칭 시&rsquo; 결과를 미리 계산해 보여줍니다.</span>
                  </>
                }>확신도</HeadLabel>
              </TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rules.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="py-6 text-center text-sm text-muted-foreground">
                  규칙이 없습니다. 우측 위 &lsquo;규칙 추가&rsquo;로 시작하십시오.
                </TableCell>
              </TableRow>
            ) : (
              rules.map((r, i) => (
                <TableRow key={i}>
                  <TableCell className="align-middle">
                    <KeywordsInput value={r.extensions || []} placeholder="예: pdf 입력 후 Enter" disabled={disabled}
                      onChange={(exts) => setRules(rules.map((x, j) => j === i ? { ...x, extensions: exts } : x))} />
                  </TableCell>
                  <TableCell className="align-middle">
                    <CollectionPicker value={r.collection_id} collections={collections} disabled={disabled}
                      onChange={(id) => setRules(rules.map((x, j) => j === i ? { ...x, collection_id: id } : x))} />
                  </TableCell>
                  <TableCell className="align-middle">
                    {advancedScore ? (
                      <Input className="h-8 text-sm" type="number" step="0.05" min={0} max={1} placeholder="0.9"
                      value={r.score ?? ""}
                      onChange={(e) => setRules(rules.map((x, j) => j === i ? { ...x, score: e.target.value === "" ? undefined : clamp01(parseFloat(e.target.value)) } : x))}
                      disabled={disabled} />
                    ) : (
                      <ScoreSelect value={r.score} defaultScore={0.9} disabled={disabled}
                        onChange={(v) => setRules(rules.map((x, j) => j === i ? { ...x, score: v } : x))} />
                    )}
                  </TableCell>
                  <TableCell className="text-right align-middle">
                    <Button variant="ghost" size="sm" className="h-8 px-1 text-muted-foreground" onClick={() => setRules(rules.filter((_, j) => j !== i))} disabled={disabled}><Trash2 className="size-3.5" /></Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

// 알려진 메타데이터/분류 키(인제스천 메타추출·자동분류가 채우는 표준 키). 목록에서 선택하거나
// 직접 입력(커스텀 필드)할 수 있다.
const META_FIELDS = ["doc_type", "dept", "source_system", "language", "author", "format", "title"]

// 표준 필드 설명 — 의미 / 예시 값 / 포맷·출처 의존성(드롭다운 항목 hover tooltip).
const META_FIELD_INFO: Record<string, { desc: string; values: string; note?: string }> = {
  doc_type: {
    desc: "문서 유형 — 인제스천 자동분류가 채우는 통제어휘 키.",
    values: "report(보고서) · rfp(제안요청서) · proposal(제안서) · presentation(발표자료) · minutes(회의록) · other(기타)",
    note: "파일명·내용으로 자동 판별하며, 통제어휘 외 값은 들어가지 않습니다.",
  },
  dept: {
    desc: "작성/소관 부서 — 출처가 제공한 값(자유 텍스트).",
    values: "예) 영업본부, 법무팀, R&D센터",
    note: "NiFi·업로드 등 출처가 줄 때만 존재합니다(자동 추출 아님).",
  },
  source_system: {
    desc: "원천 시스템/출처 경로 — 출처가 제공한 값.",
    values: "예) confluence, notion, nifi:flow-12, s3",
    note: "출처 파이프라인이 지정할 때만 존재합니다.",
  },
  language: {
    desc: "문서 언어 — 정규화된 코드.",
    values: "ko · en · ja · zh",
    note: "표기 흔들림(korean/KO 등)은 위 코드로 정규화됩니다.",
  },
  author: {
    desc: "작성자 — 문서 내부 속성에서 추출.",
    values: "예) 홍길동, hong@corp",
    note: "PDF·Office·HWP 등 포맷별 속성에서 추출되며, 포맷·문서에 따라 비어 있을 수 있습니다.",
  },
  format: {
    desc: "파일 형식 — 확장자/MIME 기반.",
    values: "pdf · hwp · hwpx · docx · pptx · xlsx · html 등",
    note: "파일 자체에서 결정됩니다. 포맷마다 이후 파싱·속성 추출 경로가 다릅니다.",
  },
  title: {
    desc: "문서 제목 — 파일 내부 속성(파일명이 아님).",
    values: "예) 2026년 사업계획서",
    note: "포맷별 속성에서 추출되며, 종종 비어 있거나 앱 기본 제목이 들어갑니다.",
  },
}

// 드롭다운 항목용 필드 설명 아이콘 — hover 시 의미·예시 값 tooltip. 클릭이 항목 선택으로
// 번지지 않도록 pointer 이벤트 전파를 막는다.
function FieldInfo({ field }: { field: string }) {
  const info = META_FIELD_INFO[field]
  if (!info) return null
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button" aria-label={`${field} 설명`}
          className="ml-auto text-muted-foreground hover:text-foreground"
          onClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
        >
          <HelpCircle className="size-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="right" className="max-w-xs text-sm">
        <div className="flex flex-col gap-1 leading-relaxed">
          <span className="font-mono font-semibold">{field}</span>
          <span>{info.desc}</span>
          <span><b>예시 값</b>: {info.values}</span>
          {info.note && <span>{info.note}</span>}
        </div>
      </TooltipContent>
    </Tooltip>
  )
}

// 필드 콤보박스 — 다른 Select 와 동일한 룩(트리거 버튼 + chevron). 표준 키를 목록에서 고르거나
// 검색창에 입력해 커스텀 필드를 추가할 수 있다(Select 로는 커스텀 입력이 안 되므로 Popover+Command).
function FieldCombobox({ value, onChange, disabled }: {
  value: string | undefined
  onChange: (v: string) => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const current = value ?? ""
  const q = query.trim().toLowerCase()
  const filtered = META_FIELDS.filter((f) => f.toLowerCase().includes(q))
  const exact = META_FIELDS.some((f) => f.toLowerCase() === q)
  const showCustom = q !== "" && !exact

  function pick(v: string) {
    onChange(v)
    setOpen(false)
    setQuery("")
  }

  return (
    <Popover open={open} onOpenChange={(o) => { setOpen(o); if (!o) setQuery("") }}>
      <PopoverTrigger asChild>
        <Button
          type="button" variant="outline" role="combobox" aria-expanded={open} disabled={disabled}
          className="h-8 w-full justify-between gap-1 px-3 font-mono text-sm font-normal"
        >
          <span className={cn("truncate", !current && "font-sans text-muted-foreground")}>{current || "필드 선택"}</span>
          <ChevronsUpDown className="size-3.5 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[var(--radix-popover-trigger-width)] min-w-44 p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput placeholder="필드 검색 또는 입력" value={query} onValueChange={setQuery} className="h-9" />
          <CommandList>
            {showCustom && (
              <CommandGroup heading="직접 입력">
                <CommandItem value={`__custom__:${query}`} onSelect={() => pick(query.trim())}>
                  <Plus className="size-3.5" />
                  <span className="font-mono">&ldquo;{query.trim()}&rdquo;</span> 추가
                </CommandItem>
              </CommandGroup>
            )}
            {filtered.length > 0 && (
              <CommandGroup heading="표준 필드">
                {filtered.map((f) => (
                  <CommandItem key={f} value={f} onSelect={() => pick(f)} className="font-mono text-sm">
                    <Check className={cn("size-3.5", current === f ? "opacity-100" : "opacity-0")} />
                    {f}
                    <FieldInfo field={f} />
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
            {filtered.length === 0 && !showCustom && (
              <CommandEmpty>필드명을 입력하십시오.</CommandEmpty>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

function ContentEmbeddingEditor({ stage, disabled, onChange }: CfgProps) {
  // 내용 임베딩(Phase 2) — 서버 설정 없음(전역 임베딩 = 라우팅 공간). 숫자 옵션만.
  const minSim = (stage.config.min_similarity as number) ?? 0.3
  const topK = (stage.config.top_k as number) ?? 3
  return (
    <div className="flex flex-col gap-2 rounded-md bg-muted/30 p-3 text-sm">
      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2">
          최소 유사도(코사인)
          <Help>
            <span>선두 텍스트와 컬렉션 기준 벡터의 <b>코사인 유사도 하한</b>(-1~1)입니다. 미만이면 후보에서 제외됩니다. 높일수록 확실한 것만 배분됩니다.</span>
          </Help>
          <Input
            type="number" step="0.05" min={-1} max={1}
            className="h-8 w-24" value={minSim} disabled={disabled}
            onChange={(e) => onChange({ ...stage.config, min_similarity: Number(e.target.value) })}
          />
        </label>
        <label className="flex items-center gap-2">
          후보 수(top_k)
          <Input
            type="number" min={1} className="h-8 w-20" value={topK} disabled={disabled}
            onChange={(e) => onChange({ ...stage.config, top_k: Number(e.target.value) || 3 })}
          />
        </label>
      </div>
      <p className="text-muted-foreground">
        비교 공간은 <b>전역 임베딩 설정</b>을 따릅니다(별도 서버 지정 없음). 컬렉션별 기준
        벡터는 <b>내용 라우팅 기준</b> 탭에서 먼저 계산해 두어야 하며, 없거나 재계산 필요
        상태인 컬렉션은 이 단계에서 제외됩니다.
      </p>
    </div>
  )
}

function LlmClassifyEditor({ stage, disabled, onChange }: CfgProps) {
  // LLM 분류(Phase 3) — 배포된 서비스(vlm)에서 선택하거나 전역 llm 설정/직접 입력.
  const serverUrl = (stage.config.server_url as string) || ""
  const model = (stage.config.model as string) || ""
  const apiKey = (stage.config.api_key as string) || ""
  const timeout = (stage.config.timeout as number) ?? 30
  // null 기준 판정 — 서비스 미선택(빈 URL) 상태도 '서비스 지정' 모드로 유지한다.
  const usingGlobal = stage.config.server_url == null && stage.config.model == null
  return (
    <div className="flex flex-col gap-2 rounded-md bg-muted/30 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex items-center gap-1">
          LLM 서버
          <Help>
            <span><b>전역 설정(기본)</b> — 설정 화면의 <span className="font-mono">llm.*</span> 을 따릅니다.</span>
            <span><b>서비스 선택</b> — 배포되어 실행 중인 VLM(OpenAI 호환) 서비스에서 고릅니다. URL·모델명이 자동으로 채워지며, 등록되지 않은 서버는 사용할 수 없습니다(전역 설정으로 지정하려면 관리자에게 문의).</span>
          </Help>
        </span>
        <Select
          value={usingGlobal ? "global" : "service"}
          onValueChange={(v) => {
            if (v === "global") onChange({ ...stage.config, server_url: undefined, model: undefined, api_key: undefined })
            // 빈 URL = 서비스 미선택 상태 — 백엔드는 빈 값을 전역 llm 설정으로 폴백하므로 안전.
            else onChange({ ...stage.config, server_url: serverUrl })
          }}
        >
          <SelectTrigger className="h-8 w-40 text-sm"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="global">전역 llm 설정(기본)</SelectItem>
            <SelectItem value="service">서비스 지정</SelectItem>
          </SelectContent>
        </Select>
        {!usingGlobal && (
          <ServiceEndpointPicker
            kind="vlm"
            value={serverUrl}
            disabled={disabled}
            allowCustom={false}
            onPick={(svc) => {
              if (svc) onChange({ ...stage.config, server_url: svc.url, model: svc.model ?? model })
            }}
          />
        )}
      </div>
      {!usingGlobal && (
        <div className="flex flex-wrap items-center gap-3">
          {/* URL·모델은 서비스 선택으로만 지정(등록 외 서버 금지 방침) — 키·타임아웃만 노출 */}
          <label className="flex items-center gap-2">
            API 키
            <Input className="h-8 w-36 font-mono text-xs" type="password" value={apiKey} disabled={disabled}
              placeholder="(비우면 전역 키)"
              onChange={(e) => onChange({ ...stage.config, api_key: e.target.value || undefined })} />
          </label>
          <label className="flex items-center gap-2">
            타임아웃(초)
            <Input type="number" className="h-8 w-20" value={timeout} disabled={disabled}
              onChange={(e) => onChange({ ...stage.config, timeout: Number(e.target.value) || 30 })} />
          </label>
        </div>
      )}
      <p className="text-muted-foreground">
        컬렉션 이름·설명 목록을 근거로 LLM 이 zero-shot 선택합니다 — 문서당 LLM 1회(수 초)
        비용이라 <b>맨 마지막 단계</b>로 두세요. 컬렉션 설명을 잘 써 둘수록 정확합니다.
      </p>
    </div>
  )
}

function CustomFunctionEditor({ stage, collections, disabled, onChange }: CfgProps) {
  // 사용자 정의 함수(Phase 3) — 코드는 정책 버전과 함께 저장·롤백된다(별도 함수 저장소 없음).
  const code = (stage.config.code as string) || ""
  const timeoutMs = (stage.config.timeout_ms as number) ?? 2000
  const defaultScore = (stage.config.default_score as number) ?? 0.9
  return (
    <div className="flex flex-col gap-2 rounded-md bg-muted/30 p-3">
      <div className="flex items-center gap-1">
        <span className="text-sm font-medium">route(doc) 함수</span>
        <Help>
          <span><b>계약</b> — <span className="font-mono">def route(doc)</span> 를 정의합니다. doc 은 <span className="font-mono">{"{filename, metadata, lead_text, source_path, storage}"}</span> 딕셔너리입니다.</span>
          <span><b>반환</b> — 컬렉션 id(정수), <span className="font-mono">(id, 0~1 확신도)</span>, 해당 없으면 <span className="font-mono">None</span>. 활성 컬렉션에 없는 id 는 무시됩니다.</span>
          <span><b>제약</b> — import 금지(<span className="font-mono">re</span> 는 기본 제공), 위험 빌트인 차단, 별도 프로세스에서 시간/메모리 제한으로 실행됩니다.</span>
        </Help>
      </div>
      <div className="flex gap-2">
        <div className="flex-1 overflow-hidden rounded-md border bg-background">
          <MonacoEditor
            height="400px"
            language="python"
            value={code || 'def route(doc):\n    # 예: 파일명에 "계약" 이 들어가면 41 번 컬렉션으로\n    # if "계약" in doc["filename"]:\n    #     return 41\n    return None\n'}
            onChange={(v) => onChange({ ...stage.config, code: v ?? "" })}
            options={{
              minimap: { enabled: false },
              fontSize: 14,
              scrollBeyondLastLine: false,
              lineNumbers: "on",
              readOnly: disabled,
              tabSize: 4,
            }}
          />
        </div>
        {/* 함수 작성 참고 정보 — 컬렉션 ID, doc 필드, 반환 규약 */}
        <div className="flex h-[400px] w-96 shrink-0 flex-col gap-3 overflow-y-auto rounded-md border bg-background p-3 text-sm">
          <div>
            <div className="mb-1 font-medium">컬렉션 ID</div>
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b">
                  <th className="w-14 px-2 py-1 text-left font-medium">ID</th>
                  <th className="px-2 py-1 text-left font-medium">컬렉션</th>
                </tr>
              </thead>
              <tbody>
                {collections.map((c) => (
                  <tr key={c.id} className="border-b last:border-0">
                    <td className="px-2 py-1 font-mono tabular-nums">{c.id}</td>
                    <td className="truncate px-2 py-1">{c.name}</td>
                  </tr>
                ))}
                {collections.length === 0 && (
                  <tr><td colSpan={2} className="px-2 py-1 text-muted-foreground">활성 컬렉션 없음</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <div>
            <div className="mb-1 font-medium">doc 필드</div>
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b">
                  <th className="w-28 px-2 py-1 text-left font-medium">필드</th>
                  <th className="px-2 py-1 text-left font-medium">내용</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ["filename", "파일명(예: 계약서.hwpx)"],
                  ["metadata", "자동분류 결과 dict(doc_type·language 등)"],
                  ["lead_text", "문서 선두 텍스트(최대 2,000자)"],
                  ["source_path", "소스 내 경로(참조 인테이크만)"],
                  ["storage", "스토리지 소스 논리명"],
                  ["source_type", "upload | storage_ref"],
                ].map(([k, v]) => (
                  <tr key={k} className="border-b last:border-0">
                    <td className="px-2 py-1 font-mono">{k}</td>
                    <td className="px-2 py-1 text-muted-foreground">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <div className="mb-1 font-medium">반환</div>
            <table className="w-full border-collapse text-sm">
              <tbody>
                {[
                  ["41", "컬렉션 ID(확신도=기본 확신도)"],
                  ["(41, 0.95)", "ID + 확신도(0~1)"],
                  ["None", "해당 없음(다음 단계로)"],
                ].map(([k, v]) => (
                  <tr key={k} className="border-b last:border-0">
                    <td className="w-28 px-2 py-1 font-mono">{k}</td>
                    <td className="px-2 py-1 text-muted-foreground">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="text-sm text-muted-foreground">
            import 금지(<span className="font-mono text-foreground">re</span> 기본 제공) ·
            별도 프로세스에서 시간/메모리 제한 실행 · 활성 컬렉션 밖 ID 는 무시
          </div>
        </div>
      </div>
      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2 text-sm">
          시간 제한(ms)
          <Input
            type="number"
            className="h-8 w-28"
            value={timeoutMs}
            disabled={disabled}
            onChange={(e) => onChange({ ...stage.config, timeout_ms: Number(e.target.value) || 2000 })}
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          기본 확신도
          <Input
            type="number"
            step="0.05"
            min={0}
            max={1}
            className="h-8 w-24"
            value={defaultScore}
            disabled={disabled}
            onChange={(e) => onChange({ ...stage.config, default_score: Number(e.target.value) })}
          />
        </label>
      </div>
    </div>
  )
}

function MetadataMatchEditor({ stage, collections, disabled, advancedScore, onChange }: CfgProps) {
  const rules = (stage.config.rules as MRule[]) || []
  const setRules = (next: MRule[]) => onChange({ ...stage.config, rules: next })
  return (
    <div className="flex flex-col gap-2 rounded-md bg-muted/30 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <span className="text-sm font-medium">규칙</span>
          <Help>
            <span><b>필드</b> — 비교할 메타데이터/분류 키. 목록에서 고르거나 직접 입력(커스텀)할 수 있습니다. 예: <span className="font-mono">doc_type</span>, <span className="font-mono">dept</span>, <span className="font-mono">source_system</span>, <span className="font-mono">language</span>.</span>
            <span><b>일치하는 값</b> — 필드 값이 이 값과 같으면(대소문자 무시) 매칭.</span>
            <span><b>컬렉션</b> — 매칭 시 보낼 지식베이스. <b>확신도</b> — 이 규칙을 얼마나 믿을지(등급 선택, 고급 토글로 숫자 입력). 단계 헤더의 배지가 최종 검토 여부를 미리 보여줍니다.</span>
          </Help>
        </div>
        {!disabled && (
          <Button variant="outline" size="sm" onClick={() => setRules([...rules, {}])}>
            <Plus className="size-3.5" /> 규칙 추가
          </Button>
        )}
      </div>
      <div className="overflow-hidden rounded-md border bg-background">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-44">필드</TableHead>
              <TableHead>일치하는 값</TableHead>
              <TableHead className="w-52">컬렉션</TableHead>
              <TableHead className="w-32">
                <HeadLabel help={
                  <>
                    <span><b>확신도</b> — 이 규칙이 매칭됐을 때 그 배분을 <b>얼마나 믿을지</b>입니다(내부값 0~1). 등급: 확실 0.95 · 높음 0.85 · 보통 0.7 · 낮음 0.5. &lsquo;기본&rsquo;은 라우터별 기본값이며, 정확한 수치는 상단 &lsquo;숫자 입력(고급)&rsquo; 토글로 입력합니다.</span>
                    <span><b>first_match</b> 모드 — 채택된 규칙의 확신도가 <b>그대로 최종 신뢰도</b>가 됩니다. 단계의 채택 임계 미만이면 매칭돼도 무시되고, 검토 임계 미만이면 &lsquo;검토 필요&rsquo;로 표시됩니다.</span>
                    <span><b>weighted_vote</b> 모드 — 최종 신뢰도 = 컬렉션별 <b>Σ(확신도 × 단계 가중치) ÷ 가중치 합</b>. 여러 단계가 같은 컬렉션을 지지할수록 올라가고, 단독 매칭은 희석됩니다 — 단계 헤더의 배지가 &lsquo;이 단계 단독 매칭 시&rsquo; 결과를 미리 계산해 보여줍니다.</span>
                  </>
                }>확신도</HeadLabel>
              </TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rules.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="py-6 text-center text-sm text-muted-foreground">
                  규칙이 없습니다. 우측 위 &lsquo;규칙 추가&rsquo;로 시작하십시오.
                </TableCell>
              </TableRow>
            ) : (
              rules.map((r, i) => (
                <TableRow key={i}>
                  <TableCell className="align-middle">
                    <FieldCombobox value={r.field} disabled={disabled}
                      onChange={(v) => setRules(rules.map((x, j) => j === i ? { ...x, field: v } : x))} />
                  </TableCell>
                  <TableCell className="align-middle">
                    <Input className="h-8 text-sm" placeholder="rfp"
                      value={r.equals ?? ""}
                      onChange={(e) => setRules(rules.map((x, j) => j === i ? { ...x, equals: e.target.value } : x))} disabled={disabled} />
                  </TableCell>
                  <TableCell className="align-middle">
                    <CollectionPicker value={r.collection_id} collections={collections} disabled={disabled}
                      onChange={(id) => setRules(rules.map((x, j) => j === i ? { ...x, collection_id: id } : x))} />
                  </TableCell>
                  <TableCell className="align-middle">
                    {advancedScore ? (
                      <Input className="h-8 text-sm" type="number" step="0.05" min={0} max={1} placeholder="0.8"
                      value={r.score ?? ""}
                      onChange={(e) => setRules(rules.map((x, j) => j === i ? { ...x, score: e.target.value === "" ? undefined : clamp01(parseFloat(e.target.value)) } : x))} disabled={disabled} />
                    ) : (
                      <ScoreSelect value={r.score} defaultScore={0.8} disabled={disabled}
                        onChange={(v) => setRules(rules.map((x, j) => j === i ? { ...x, score: v } : x))} />
                    )}
                  </TableCell>
                  <TableCell className="text-right align-middle">
                    <Button variant="ghost" size="sm" className="h-8 px-1 text-muted-foreground" onClick={() => setRules(rules.filter((_, j) => j !== i))} disabled={disabled}><Trash2 className="size-3.5" /></Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

const PATH_MATCH_LABEL: Record<string, string> = { prefix: "프리픽스", glob: "글롭", regex: "정규식" }

function PathRuleEditor({ stage, collections, sources, disabled, advancedScore, onChange }: CfgProps) {
  const match = (stage.config.match as string) || "prefix"
  const rules = (stage.config.rules as PRule[]) || []
  const setRules = (next: PRule[]) => onChange({ ...stage.config, match, rules: next })
  const sourceNames = sources ?? []
  return (
    <div className="flex flex-col gap-2 rounded-md bg-muted/30 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <span className="text-sm font-medium">규칙</span>
          <Help>
            <span><b>매칭 방식</b> — 프리픽스(디렉터리 경계 기준 시작 일치) / 글롭(<span className="font-mono">*</span>=폴더 내, <span className="font-mono">**</span>=하위 전체) / 정규식(파이썬 re, 부분 일치).</span>
            <span><b>프리픽스</b> 모드 — 경로 프리픽스를 입력 후 Enter 로 배지 추가. 예: <span className="font-mono">contracts/</span> (contracts-old 는 미매칭)</span>
            <span><b>글롭</b> 모드 — 예: <span className="font-mono">hr/**/policy/*.pdf</span></span>
            <span><b>소스</b> — 지정하면 그 스토리지 소스에서 온 문서만 매칭(비우면 모든 소스). 스토리지 소스 메뉴에서 등록합니다.</span>
            <span><b>컬렉션</b> — 매칭 시 보낼 지식베이스. <b>점수</b> — 매칭 시 부여할 신뢰도(0~1, 기본 0.95).</span>
            <span>경로는 참조 인테이크(소스에서 가져오기)에서만 채워지므로, 일반 업로드에는 매칭되지 않습니다.</span>
          </Help>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5">
            <span className="text-sm text-muted-foreground">매칭</span>
            <Select value={match} onValueChange={(v) => onChange({ ...stage.config, match: v, rules })} disabled={disabled}>
              <SelectTrigger className="h-8 w-28"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="prefix">프리픽스</SelectItem>
                <SelectItem value="glob">글롭</SelectItem>
                <SelectItem value="regex">정규식</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {!disabled && (
            <Button variant="outline" size="sm" onClick={() => setRules([...rules, {}])}>
              <Plus className="size-3.5" /> 규칙 추가
            </Button>
          )}
        </div>
      </div>
      <div className="overflow-hidden rounded-md border bg-background">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{match === "regex" ? "정규표현식" : `경로 패턴(${PATH_MATCH_LABEL[match]})`}</TableHead>
              <TableHead className="w-40">소스</TableHead>
              <TableHead className="w-52">컬렉션</TableHead>
              <TableHead className="w-32">
                <HeadLabel help={
                  <>
                    <span><b>확신도</b> — 이 규칙이 매칭됐을 때 그 배분을 <b>얼마나 믿을지</b>입니다(내부값 0~1). 등급: 확실 0.95 · 높음 0.85 · 보통 0.7 · 낮음 0.5. &lsquo;기본&rsquo;은 라우터별 기본값이며, 정확한 수치는 상단 &lsquo;숫자 입력(고급)&rsquo; 토글로 입력합니다.</span>
                    <span><b>first_match</b> 모드 — 채택된 규칙의 확신도가 <b>그대로 최종 신뢰도</b>가 됩니다. 단계의 채택 임계 미만이면 매칭돼도 무시되고, 검토 임계 미만이면 &lsquo;검토 필요&rsquo;로 표시됩니다.</span>
                    <span><b>weighted_vote</b> 모드 — 최종 신뢰도 = 컬렉션별 <b>Σ(확신도 × 단계 가중치) ÷ 가중치 합</b>. 여러 단계가 같은 컬렉션을 지지할수록 올라가고, 단독 매칭은 희석됩니다 — 단계 헤더의 배지가 &lsquo;이 단계 단독 매칭 시&rsquo; 결과를 미리 계산해 보여줍니다.</span>
                  </>
                }>확신도</HeadLabel>
              </TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rules.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="py-6 text-center text-sm text-muted-foreground">
                  규칙이 없습니다. 우측 위 &lsquo;규칙 추가&rsquo;로 시작하십시오.
                </TableCell>
              </TableRow>
            ) : (
              rules.map((r, i) => (
                <TableRow key={i}>
                  <TableCell className="align-middle">
                    {match === "regex" ? (
                      <Input className="h-8 font-mono text-sm" placeholder="contracts/\d{4}/"
                        value={r.patterns?.[0] ?? ""}
                        onChange={(e) => setRules(rules.map((x, j) => j === i ? { ...x, patterns: e.target.value ? [e.target.value] : [] } : x))}
                        disabled={disabled} />
                    ) : (
                      <KeywordsInput value={r.patterns || []} disabled={disabled}
                        placeholder={match === "glob" ? "예: hr/**/policy/*.pdf 입력 후 Enter" : "예: contracts/ 입력 후 Enter"}
                        onChange={(ps) => setRules(rules.map((x, j) => j === i ? { ...x, patterns: ps } : x))} />
                    )}
                  </TableCell>
                  <TableCell className="align-middle">
                    <Select
                      value={r.storage || NONE}
                      onValueChange={(v) => setRules(rules.map((x, j) => j === i ? { ...x, storage: v === NONE ? undefined : v } : x))}
                      disabled={disabled}
                    >
                      <SelectTrigger className="h-8"><SelectValue placeholder="모든 소스" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value={NONE}>모든 소스</SelectItem>
                        {sourceNames.map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}
                        {/* 목록에 없는 이름(삭제된 소스 등)이 규칙에 남아 있으면 그대로 노출 */}
                        {r.storage && !sourceNames.includes(r.storage) && (
                          <SelectItem value={r.storage}>{r.storage} (미등록)</SelectItem>
                        )}
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell className="align-middle">
                    <CollectionPicker value={r.collection_id} collections={collections} disabled={disabled}
                      onChange={(id) => setRules(rules.map((x, j) => j === i ? { ...x, collection_id: id } : x))} />
                  </TableCell>
                  <TableCell className="align-middle">
                    {advancedScore ? (
                      <Input className="h-8 text-sm" type="number" step="0.05" min={0} max={1} placeholder="0.95"
                      value={r.score ?? ""}
                      onChange={(e) => setRules(rules.map((x, j) => j === i ? { ...x, score: e.target.value === "" ? undefined : clamp01(parseFloat(e.target.value)) } : x))}
                      disabled={disabled} />
                    ) : (
                      <ScoreSelect value={r.score} defaultScore={0.95} disabled={disabled}
                        onChange={(v) => setRules(rules.map((x, j) => j === i ? { ...x, score: v } : x))} />
                    )}
                  </TableCell>
                  <TableCell className="text-right align-middle">
                    <Button variant="ghost" size="sm" className="h-8 px-1 text-muted-foreground" onClick={() => setRules(rules.filter((_, j) => j !== i))} disabled={disabled}><Trash2 className="size-3.5" /></Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

function JsonConfigEditor({ stage, disabled, onChange }: { stage: RoutingStage; disabled?: boolean; onChange: (cfg: Record<string, unknown>) => void }) {
  const [text, setText] = useState(() => JSON.stringify(stage.config ?? {}, null, 2))
  const [err, setErr] = useState<string | null>(null)
  return (
    <div className="flex flex-col gap-1.5">
      <FieldLabel help={
        <>
          <span>이 라우터의 설정을 <b>JSON</b>으로 직접 입력합니다(전용 편집기가 없는 라우터용 폴백).</span>
          <span>키·형식은 라우터의 <span className="font-mono">config_schema</span>를 따릅니다. 형식 오류 시 저장되지 않습니다.</span>
        </>
      }>설정(JSON)</FieldLabel>
      <Textarea
        className={`min-h-24 font-mono text-sm ${err ? "border-destructive" : ""}`}
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          try {
            const parsed = JSON.parse(e.target.value || "{}")
            setErr(null)
            onChange(parsed)
          } catch {
            setErr("JSON 형식 오류")
          }
        }}
        disabled={disabled}
      />
      {err && <span className="text-sm text-destructive">{err}</span>}
    </div>
  )
}

function splitCsv(s: string): string[] {
  return s.split(",").map((x) => x.trim()).filter(Boolean)
}

// 시맨틱 상태색 규약 — 초록=정상 확정(매칭), 호박=사람 확인 필요(폴백·검토), 빨강=실패/오류.
export function DecisionBadges({ matched, fallback, review }: { matched: string | null; fallback: boolean; review: boolean }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {matched && <Badge variant="success" className="text-sm font-normal">매칭: {matched}</Badge>}
      {fallback && <Badge variant="warning" className="text-sm font-normal">폴백 사용</Badge>}
      {review && <Badge variant="warning" className="text-sm font-normal">검토 필요</Badge>}
    </div>
  )
}
