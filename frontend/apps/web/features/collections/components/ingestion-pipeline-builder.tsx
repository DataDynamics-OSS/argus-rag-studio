// 인제스천 파이프라인 구성 UI — 레지스트리(GET /ingestion/transforms) 구동 스테이지 빌더.
// 본문 보강(post_parse) → 청킹 → 청크 보강(post_chunk) 단계를 추가/순서변경/설정하고,
// 드래프트 미리보기(저장 없이) 후 "저장 후 재인덱싱"으로 컬렉션에 적용한다.
"use client"

import { Fragment, useCallback, useEffect, useMemo, useState } from "react"
import { ArrowDown, ArrowRight, ArrowUp, HelpCircle, Loader2, Play, Save, X } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import { Badge } from "@workspace/ui/components/badge"
import { Card, CardContent } from "@workspace/ui/components/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { Tooltip, TooltipContent, TooltipTrigger } from "@workspace/ui/components/tooltip"
import { cn } from "@workspace/ui/lib/utils"
import { toast } from "sonner"
import { ServiceEndpointPicker } from "@/features/deploy/components/service-endpoint-picker"
import { getIngestionTransforms, reindexCollection } from "@/features/collections/api"
import type {
  Collection,
  PipelineStage,
  TransformInfo,
  TransformPhase,
} from "@/features/collections/data/schema"
import { previewPipeline } from "@/features/ingestion/api"
import type { ChunkPreview } from "@/features/ingestion/data/schema"
import { listPiiFunctions, listPiiRules } from "@/features/pii/api"
import type { PiiFunction, PiiRule } from "@/features/pii/data/schema"

type DocLite = { document_id: string; name: string }

// config 키 → 한글 표시 라벨(없으면 키 그대로).
const CONFIG_KEY_LABELS: Record<string, string> = {
  min_chars: "최소 문자수",
}

// 이미지 내용 주입(image_captions) 유형 옵션 — 백엔드 DEFAULT_TYPES/_TYPE_LABEL 과 매칭.
const CAPTION_TYPES = [
  { value: "chart", label: "차트" },
  { value: "table", label: "표" },
  { value: "diagram", label: "다이어그램" },
  { value: "screenshot", label: "화면 캡처" },
  { value: "formula", label: "수식" },
  { value: "photo", label: "사진" },
  { value: "logo", label: "로고" },
  { value: "other", label: "기타" },
]
const CAPTION_DEFAULT_TYPES = ["chart", "table", "diagram", "screenshot", "formula"]

// PII 확장 함수(pii_builtin) 선택 옵션 — 백엔드 _BUILTINS 와 매칭(value·기본 마스크).
const BUILTIN_PII_FUNCS = [
  { value: "card", label: "신용카드 (Luhn 검증)", mask: "[CARD]" },
  { value: "bizno", label: "사업자등록번호 (검증식)", mask: "[BIZNO]" },
  { value: "rrn", label: "주민/외국인등록번호 (검증)", mask: "[RRN]" },
]

export function IngestionPipelineBuilder({
  collection,
  documents,
  onReindexed,
}: {
  collection: Collection
  documents: DocLite[]
  onReindexed?: () => void
}) {
  const [transforms, setTransforms] = useState<TransformInfo[]>([])
  const [piiFunctions, setPiiFunctions] = useState<PiiFunction[]>([])
  const [piiRules, setPiiRules] = useState<PiiRule[]>([])
  const [postParse, setPostParse] = useState<PipelineStage[]>(
    collection.ingestion_pipeline?.post_parse ?? [{ id: "table_row_cleanup" }]
  )
  const [postChunk, setPostChunk] = useState<PipelineStage[]>(
    collection.ingestion_pipeline?.post_chunk ?? []
  )
  const [docUuid, setDocUuid] = useState<string>(documents[0]?.document_id ?? "")
  const [preview, setPreview] = useState<ChunkPreview | null>(null)
  const [busy, setBusy] = useState<"preview" | "save" | null>(null)
  const [highlight, setHighlight] = useState<string | null>(null)

  // 그래프 노드/칩 클릭 → 해당 편집기로 스크롤 + (개별 단계면) 잠깐 하이라이트.
  function navigate(phase: TransformPhase, idx?: number) {
    const id = idx != null ? `stage-${phase}-${idx}` : `phase-${phase}`
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "center" })
    if (idx != null) {
      setHighlight(`${phase}-${idx}`)
      setTimeout(() => setHighlight(null), 1600)
    }
  }

  useEffect(() => {
    getIngestionTransforms()
      .then((r) => setTransforms(r.transforms))
      .catch(() => {})
    listPiiFunctions()
      .then((fns) => setPiiFunctions(fns))
      .catch(() => {})
    listPiiRules()
      .then((rules) => setPiiRules(rules))
      .catch(() => {})
  }, [])

  const info = useCallback((id: string) => transforms.find((t) => t.id === id), [transforms])
  const byPhase = (phase: TransformPhase) => transforms.filter((t) => t.phase === phase)

  function setStages(phase: TransformPhase, next: PipelineStage[]) {
    if (phase === "post_parse") setPostParse(next)
    else setPostChunk(next)
  }

  function addStage(phase: TransformPhase, id: string) {
    const stages = phase === "post_parse" ? postParse : postChunk
    setStages(phase, [...stages, { id, config: {} }])
  }
  function removeStage(phase: TransformPhase, idx: number) {
    const stages = (phase === "post_parse" ? postParse : postChunk).slice()
    stages.splice(idx, 1)
    setStages(phase, stages)
  }
  function moveStage(phase: TransformPhase, idx: number, dir: -1 | 1) {
    const stages = (phase === "post_parse" ? postParse : postChunk).slice()
    const j = idx + dir
    if (j < 0 || j >= stages.length) return
    ;[stages[idx], stages[j]] = [stages[j]!, stages[idx]!]
    setStages(phase, stages)
  }
  function setConfig(phase: TransformPhase, idx: number, key: string, value: unknown) {
    const stages = (phase === "post_parse" ? postParse : postChunk).slice()
    stages[idx] = { ...stages[idx]!, config: { ...(stages[idx]!.config ?? {}), [key]: value } }
    setStages(phase, stages)
  }

  // 여러 키 동시 패치 — 연속 setConfig 는 stale state 로 서로 덮어쓴다(예: 서비스 선택 시
  // server_url+model, 전역 복귀 시 3키 초기화). 원자적으로 한 번에 반영한다.
  function setConfigMany(phase: TransformPhase, idx: number, patch: Record<string, unknown>) {
    const stages = (phase === "post_parse" ? postParse : postChunk).slice()
    stages[idx] = { ...stages[idx]!, config: { ...(stages[idx]!.config ?? {}), ...patch } }
    setStages(phase, stages)
  }

  const draft = useMemo(
    () => ({ post_parse: postParse, post_chunk: postChunk }),
    [postParse, postChunk]
  )

  async function runPreview() {
    if (!docUuid) {
      toast.error("미리볼 문서가 없습니다(문서를 먼저 업로드하세요).")
      return
    }
    setBusy("preview")
    try {
      setPreview(await previewPipeline(docUuid, draft))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "미리보기 실패")
    } finally {
      setBusy(null)
    }
  }

  async function save() {
    setBusy("save")
    try {
      const res = await reindexCollection(collection.id, {
        post_parse: postParse,
        post_chunk: postChunk,
      })
      toast.success(`파이프라인 저장 + 재인덱싱 시작 — 문서 ${res.document_count}개`)
      onReindexed?.()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "저장/재인덱싱 실패")
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-muted-foreground">
        파싱 → <span className="font-medium text-foreground">본문 보강</span> → 청킹 →{" "}
        <span className="font-medium text-foreground">청크 보강</span> → 임베딩 → 색인. 보강 단계를
        추가·정렬하고 미리보기로 확인한 뒤 저장하면 전체 재인덱싱됩니다.
      </p>

      <PipelineGraph
        postParse={postParse}
        postChunk={postChunk}
        info={info}
        piiRules={piiRules}
        piiFunctions={piiFunctions}
        onNavigate={navigate}
      />

      <PhaseEditor
        title="① 본문 보강 (파싱 후, 텍스트 보강 및 변경)"
        phase="post_parse"
        stages={postParse}
        options={byPhase("post_parse")}
        info={info}
        piiFunctions={piiFunctions}
        piiRules={piiRules}
        highlight={highlight}
        onAdd={(id) => addStage("post_parse", id)}
        onRemove={(i) => removeStage("post_parse", i)}
        onMove={(i, d) => moveStage("post_parse", i, d)}
        onConfig={(i, k, v) => setConfig("post_parse", i, k, v)}
        onConfigMany={(i, patch) => setConfigMany("post_parse", i, patch)}
      />

      <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
        ② 청킹 — {collection.chunk_strategy} · {collection.chunk_unit} · size {collection.chunk_size} /
        overlap {collection.chunk_overlap} (청킹 설정은 재인덱싱 다이얼로그에서 변경)
      </div>

      <PhaseEditor
        title="③ 청크 보강 (청크 처리 후, 청크 보강)"
        phase="post_chunk"
        stages={postChunk}
        options={byPhase("post_chunk")}
        info={info}
        piiFunctions={piiFunctions}
        piiRules={piiRules}
        highlight={highlight}
        onAdd={(id) => addStage("post_chunk", id)}
        onRemove={(i) => removeStage("post_chunk", i)}
        onMove={(i, d) => moveStage("post_chunk", i, d)}
        onConfig={(i, k, v) => setConfig("post_chunk", i, k, v)}
        onConfigMany={(i, patch) => setConfigMany("post_chunk", i, patch)}
      />

      <div className="flex flex-wrap items-end gap-2 border-t pt-3">
        <div className="flex flex-col gap-1">
          <Label className="text-xs text-muted-foreground">미리보기 문서</Label>
          <Select value={docUuid} onValueChange={setDocUuid}>
            <SelectTrigger className="w-64">
              <SelectValue placeholder={documents.length ? "문서 선택" : "문서 없음"} />
            </SelectTrigger>
            <SelectContent>
              {documents.map((d) => (
                <SelectItem key={d.document_id} value={d.document_id}>
                  {d.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button variant="outline" onClick={runPreview} disabled={busy !== null || !docUuid}>
          {busy === "preview" ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
          미리보기
        </Button>
        <Button onClick={save} disabled={busy !== null} className="ml-auto">
          {busy === "save" ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
          저장 후 재인덱싱
        </Button>
      </div>

      {preview && (
        <Card>
          <CardContent className="flex flex-col gap-2 pt-4 text-xs">
            <div className="flex items-center gap-2">
              <Badge variant="secondary">청크 {preview.chunk_total}</Badge>
              <span className="text-muted-foreground">전문 {preview.char_count}자 · 드래프트 적용 결과</span>
            </div>
            <div className="flex max-h-72 flex-col gap-2 overflow-auto">
              {preview.chunks.slice(0, 20).map((c, i) => (
                <div key={i} className="rounded border p-2">
                  <span className="text-muted-foreground">#{i + 1}</span>{" "}
                  <span className="whitespace-pre-wrap">{c.text.slice(0, 200)}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function PhaseEditor({
  title,
  phase,
  stages,
  options,
  info,
  piiFunctions,
  piiRules,
  highlight,
  onAdd,
  onRemove,
  onMove,
  onConfig,
  onConfigMany,
}: {
  title: string
  phase: TransformPhase
  stages: PipelineStage[]
  options: TransformInfo[]
  info: (id: string) => TransformInfo | undefined
  piiFunctions: PiiFunction[]
  piiRules: PiiRule[]
  highlight: string | null
  onAdd: (id: string) => void
  onRemove: (i: number) => void
  onMove: (i: number, dir: -1 | 1) => void
  onConfig: (i: number, key: string, value: unknown) => void
  onConfigMany: (i: number, patch: Record<string, unknown>) => void
}) {
  return (
    <div id={`phase-${phase}`} className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">{title}</span>
        <Select value="" onValueChange={onAdd}>
          <SelectTrigger className="ml-auto h-8 w-40 text-xs">
            <SelectValue placeholder="+ 보강 추가" />
          </SelectTrigger>
          <SelectContent>
            {options.map((t) => (
              <SelectItem key={t.id} value={t.id} disabled={!t.available}>
                {t.label}
                {!t.available ? " (미설치)" : ""}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {stages.length === 0 ? (
        <p className="rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground">
          보강 없음 — 위에서 추가하세요.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {stages.map((st, i) => {
            const meta = info(st.id)
            const schema = (meta?.config_schema ?? {}) as Record<string, Record<string, unknown>>
            return (
              <div
                key={`${st.id}-${i}`}
                id={`stage-${phase}-${i}`}
                className={cn(
                  "flex items-start gap-2 rounded-md border p-2 transition-shadow",
                  highlight === `${phase}-${i}` && "ring-2 ring-primary"
                )}
              >
                <div className="flex flex-col">
                  <button
                    type="button"
                    className="text-muted-foreground hover:text-foreground disabled:opacity-30"
                    disabled={i === 0}
                    onClick={() => onMove(i, -1)}
                  >
                    <ArrowUp className="size-3.5" />
                  </button>
                  <button
                    type="button"
                    className="text-muted-foreground hover:text-foreground disabled:opacity-30"
                    disabled={i === stages.length - 1}
                    onClick={() => onMove(i, 1)}
                  >
                    <ArrowDown className="size-3.5" />
                  </button>
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-sm">
                    <span className="font-medium">{meta?.label ?? st.id}</span>
                    {meta && !meta.available && (
                      <Badge variant="destructive" className="h-4 px-1 text-[10px]">미설치</Badge>
                    )}
                  </div>
                  {meta?.description && (
                    <p className="text-sm">{meta.description}</p>
                  )}
                  {(st.id === "pii_regex" || st.id === "pii_function" || st.id === "pii_builtin" || Object.keys(schema).length > 0) && (
                    <div className="mt-1 flex flex-wrap items-center gap-2">
                      {st.id === "pii_regex" && (
                        <label className="flex items-center gap-1 text-sm">
                          <span>규칙</span>
                          <Select
                            value={(st.config?.rule_id as string) ?? "__all__"}
                            onValueChange={(v) => onConfig(i, "rule_id", v === "__all__" ? undefined : v)}
                          >
                            <SelectTrigger className="h-7 w-56 text-sm">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="__all__">전체(enabled)</SelectItem>
                              {piiRules.map((r) => (
                                <SelectItem key={r.rule_id} value={r.rule_id} disabled={!r.enabled}>
                                  {r.name}{!r.enabled ? " · 미사용" : ""}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </label>
                      )}
                      {st.id === "pii_regex" && st.config?.rule_id != null && (
                        <label className="flex items-center gap-1 text-sm">
                          <span>마스킹</span>
                          <HelpTip>
                            <span>매칭된 값을 치환할 문자열입니다. 비우면 규칙에 등록된 마스크를 사용합니다. 예: <span className="font-mono">[EMAIL]</span>, <span className="font-mono">***</span></span>
                          </HelpTip>
                          <Input
                            className="h-7 w-52 text-sm"
                            value={(st.config?.mask as string) ?? ""}
                            placeholder={(() => {
                              const def = piiRules.find((r) => r.rule_id === st.config?.rule_id)?.mask
                              return def ? `비우면 기본값(${def}) 사용` : "비우면 규칙 기본값 사용"
                            })()}
                            onChange={(e) => onConfig(i, "mask", e.target.value || undefined)}
                          />
                        </label>
                      )}
                      {st.id === "pii_function" && (
                        <label className="flex items-center gap-1 text-sm">
                          <span>함수</span>
                          <Select
                            value={(st.config?.function_id as string) ?? "__all__"}
                            onValueChange={(v) => onConfig(i, "function_id", v === "__all__" ? undefined : v)}
                          >
                            <SelectTrigger className="h-7 w-56 text-sm">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="__all__">전체(enabled)</SelectItem>
                              {piiFunctions.map((f) => (
                                <SelectItem key={f.function_id} value={f.function_id} disabled={!f.enabled}>
                                  {f.name}{!f.enabled ? " · 미사용" : ""}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </label>
                      )}
                      {st.id === "image_captions" && (
                        <ImageCaptionsConfig
                          config={st.config ?? {}}
                          onSet={(key, value) => onConfig(i, key, value)}
                          onSetMany={(patch) => onConfigMany(i, patch)}
                        />
                      )}
                      {st.id === "pii_builtin" && (
                        <label className="flex items-center gap-1 text-sm">
                          <span>함수</span>
                          <Select
                            value={(st.config?.function as string) ?? ""}
                            onValueChange={(v) => onConfig(i, "function", v)}
                          >
                            <SelectTrigger className="h-7 w-56 text-sm">
                              <SelectValue placeholder="함수 선택" />
                            </SelectTrigger>
                            <SelectContent>
                              {BUILTIN_PII_FUNCS.map((f) => (
                                <SelectItem key={f.value} value={f.value}>{f.label}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </label>
                      )}
                      {Object.entries(schema).map(([key, spec]) => {
                        // image_captions 는 전용 폼(ImageCaptionsConfig)이 전부 담당.
                        if (st.id === "image_captions") return null
                        const val = (st.config ?? {})[key]
                        if (key === "on_error") {
                          return (
                            <label key={key} className="flex items-center gap-1 text-sm">
                              <span>실패 시</span>
                              <HelpTip>
                                <div className="flex flex-col gap-1">
                                  <span><span className="font-mono">skip</span> — 이 단계 실패를 무시하고 다음 단계로 계속(마스킹 일부 누락 가능)</span>
                                  <span><span className="font-mono">fail</span> — 단계 실패 시 인제스천 잡을 실패 처리(개인정보 무음 누락 방지 · PII 권장)</span>
                                </div>
                              </HelpTip>
                              <Select value={(val as string) ?? "skip"} onValueChange={(v) => onConfig(i, "on_error", v)}>
                                <SelectTrigger className="h-7 w-44 text-sm">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="skip">건너뛰기 (skip)</SelectItem>
                                  <SelectItem value="fail">잡 실패 (fail)</SelectItem>
                                </SelectContent>
                              </Select>
                            </label>
                          )
                        }
                        if (key === "mask") {
                          return (
                            <label key={key} className="flex items-center gap-1 text-sm">
                              <span>마스킹</span>
                              <HelpTip>
                                <span>매칭된 개인정보를 치환할 문자열입니다. 비우면 기본값(신용카드 [CARD]·사업자 [BIZNO]·주민 [RRN])을 씁니다. 예: <span className="font-mono">[카드]</span>, <span className="font-mono">***</span></span>
                              </HelpTip>
                              <Input
                                className="h-7 w-52 text-sm"
                                value={val == null ? "" : String(val)}
                                placeholder={(() => {
                                  const def = BUILTIN_PII_FUNCS.find((f) => f.value === st.config?.function)?.mask
                                  return def ? `비우면 기본값(${def}) 사용` : "비우면 기본값 사용"
                                })()}
                                onChange={(e) => onConfig(i, key, e.target.value || undefined)}
                              />
                            </label>
                          )
                        }
                        const isNum = spec?.type === "int" || spec?.type === "number"
                        return (
                          <label key={key} className="flex items-center gap-1 text-sm">
                            <span>{CONFIG_KEY_LABELS[key] ?? key}</span>
                            <Input
                              className="h-7 w-24 text-sm"
                              type={isNum ? "number" : "text"}
                              value={val == null ? "" : String(val)}
                              placeholder={spec?.default != null ? String(spec.default) : ""}
                              onChange={(e) =>
                                onConfig(
                                  i,
                                  key,
                                  isNum
                                    ? (e.target.value === "" ? undefined : Number(e.target.value))
                                    : e.target.value
                                )
                              }
                            />
                          </label>
                        )
                      })}
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  className="text-muted-foreground hover:text-destructive"
                  onClick={() => onRemove(i)}
                  aria-label="remove"
                >
                  <X className="size-4" />
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// 라벨 옆 도움말 — ? 아이콘 hover 시 설명 툴팁.
function HelpTip({ children }: { children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button type="button" className="text-muted-foreground hover:text-foreground" aria-label="설명">
          <HelpCircle className="size-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-[26rem]">{children}</TooltipContent>
    </Tooltip>
  )
}

// 이미지 내용 주입(image_captions) 전용 설정 폼 — 범용 텍스트 입력 대신 유형 토글·의미
// 셀렉트·설명 툴팁으로 옵션의 의미를 드러낸다(값 미지정 = 백엔드 기본값).
function ImageCaptionsConfig({
  config,
  onSet,
  onSetMany,
}: {
  config: Record<string, unknown>
  onSet: (key: string, value: unknown) => void
  onSetMany: (patch: Record<string, unknown>) => void
}) {

  // types: 콤마 문자열(비우면 기본 = chart,table,diagram,screenshot,formula)
  const raw = String(config.types ?? "").trim()
  const selected = raw
    ? raw.split(",").map((t) => t.trim().toLowerCase()).filter(Boolean)
    : CAPTION_DEFAULT_TYPES
  function toggleType(t: string) {
    const next = selected.includes(t) ? selected.filter((x) => x !== t) : [...selected, t]
    // 기본값과 동일해지면 저장값을 비운다(설정 최소화).
    const isDefault =
      next.length === CAPTION_DEFAULT_TYPES.length &&
      CAPTION_DEFAULT_TYPES.every((d) => next.includes(d))
    onSet("types", isDefault ? undefined : next.join(","))
  }
  const conf = config.min_confidence == null ? "0.5" : String(config.min_confidence)
  const boolVal = (key: string) => config[key] === false ? "off" : "on" // 기본 켬

  return (
    <div className="flex w-full flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-1.5 text-sm">
        <span className="flex items-center gap-1">
          주입 유형
          <HelpTip>
            <div className="flex flex-col gap-1">
              <span>VLM이 판별한 이미지 유형 중 <b>어떤 것의 내용을 본문에 넣을지</b>입니다. 켜진 유형만 주입됩니다.</span>
              <span>기본은 정보성 유형(차트·표·다이어그램·화면 캡처·수식)만입니다 — 사진·로고는 검색 가치 대비 노이즈가 커서 제외돼 있습니다.</span>
            </div>
          </HelpTip>
        </span>
        {CAPTION_TYPES.map((t) => {
          const on = selected.includes(t.value)
          return (
            <button
              key={t.value}
              type="button"
              onClick={() => toggleType(t.value)}
              className={cn(
                "rounded-full border px-2 py-0.5 text-sm transition-colors",
                on
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted/50"
              )}
            >
              {t.label}
            </button>
          )
        })}
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-1">
          <span>최소 확신도</span>
          <HelpTip>
            <span>VLM 판별 확신도가 이 값 <b>미만인 이미지는 주입하지 않습니다</b> — 잘못 인식된 내용이 본문·검색을 오염시키는 것을 막는 문턱입니다. 확실한 것만 넣으려면 높이세요.</span>
          </HelpTip>
          <Select value={conf} onValueChange={(v) => onSet("min_confidence", v === "0.5" ? undefined : Number(v))}>
            <SelectTrigger className="h-7 w-40 text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="0.3">낮게 (0.3) — 많이 주입</SelectItem>
              <SelectItem value="0.5">보통 (0.5) — 기본</SelectItem>
              <SelectItem value="0.7">높게 (0.7) — 확실한 것만</SelectItem>
              {!["0.3", "0.5", "0.7"].includes(conf) && (
                <SelectItem value={conf}>직접 입력 ({conf})</SelectItem>
              )}
            </SelectContent>
          </Select>
        </label>
        <label className="flex items-center gap-1">
          <span>OCR 텍스트</span>
          <HelpTip>
            <span>이미지 안 글자(축 라벨·수치·범례 등)를 <b>원문 그대로</b> 본문에 포함합니다. 가장 사실성이 높은 부분이라 기본 켬 — 차트/표 속 수치 검색의 핵심입니다.</span>
          </HelpTip>
          <Select value={boolVal("include_ocr")} onValueChange={(v) => onSet("include_ocr", v === "on" ? undefined : false)}>
            <SelectTrigger className="h-7 w-24 text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="on">포함</SelectItem>
              <SelectItem value="off">제외</SelectItem>
            </SelectContent>
          </Select>
        </label>
        <label className="flex items-center gap-1">
          <span>표·수식 구조화</span>
          <HelpTip>
            <span>표는 마크다운 표, 수식은 LaTeX 로 <b>구조화한 내용</b>을 포함합니다(VLM 심층 분석 산출). 원본이 복잡하면 부정확할 수 있어, 오염이 우려되면 끄고 OCR 만 쓰세요.</span>
          </HelpTip>
          <Select value={boolVal("include_details")} onValueChange={(v) => onSet("include_details", v === "on" ? undefined : false)}>
            <SelectTrigger className="h-7 w-24 text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="on">포함</SelectItem>
              <SelectItem value="off">제외</SelectItem>
            </SelectContent>
          </Select>
        </label>
        <label className="flex items-center gap-1">
          <span>문서당 상한</span>
          <HelpTip>
            <span>한 문서에서 <b>최대 몇 장까지 주입할지</b>입니다(기본 20). 이미지가 아주 많은 문서의 본문 비대화와 처리 시간을 막습니다 — 이미지당 VLM 호출 1회가 든다는 점을 기억하세요.</span>
          </HelpTip>
          <Input
            className="h-7 w-20 text-sm"
            type="number"
            min={1}
            placeholder="20"
            value={config.max_images == null ? "" : String(config.max_images)}
            onChange={(e) => onSet("max_images", e.target.value === "" ? undefined : Number(e.target.value))}
          />
        </label>
      </div>
      {/* VLM 지정 — 비우면 전역 설정(image_classification.*). 배포 관리에서 VLM 을 새로 배포하면
          전역 설정이 그 서버로 연결되므로, 여기는 특정 지식베이스만 다른 VLM 으로 비교 테스트할 때 쓴다. */}
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="flex items-center gap-1">
          VLM 서버
          <HelpTip>
            <div className="flex flex-col gap-1">
              <span><b>이 지식베이스의 이미지 인식에 쓸 VLM</b> 입니다. <b>전역 설정(기본)</b>은 설정 화면의 <span className="font-mono">image_classification.*</span> 을 따르며, 에이전트 &gt; 서비스/배포 관리에서 VLM 을 배포하면 전역 설정이 새 서버로 자동 연결됩니다.</span>
              <span><b>직접 지정</b>하면 이 지식베이스만 다른 VLM 으로 처리합니다 — 모델 비교 테스트용. 변경 후에는 재인덱싱해야 기존 문서에 반영됩니다.</span>
            </div>
          </HelpTip>
        </span>
        <Select
          value={config.server_url != null || config.model != null ? "custom" : "global"}
          onValueChange={(v) => {
            if (v === "global") {
              // 전역 복귀 — 관련 키를 원자적으로 전부 제거(연속 onSet 은 서로 덮어씀).
              onSetMany({ server_url: undefined, model: undefined, api_key: undefined })
            } else {
              // 빈 URL = 서비스 미선택 상태 — 워커는 빈 값을 전역 설정으로 폴백하므로 안전.
              onSetMany({ server_url: String(config.server_url ?? "") })
            }
          }}
        >
          <SelectTrigger className="h-7 w-36 text-sm"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="global">전역 설정(기본)</SelectItem>
            <SelectItem value="custom">직접 지정</SelectItem>
          </SelectContent>
        </Select>
        {(config.server_url != null || config.model != null) && (
          /* 배포된 VLM 서비스에서만 선택 — URL·모델이 함께 config 에 들어간다(등록 외 서버 금지 방침). */
          <ServiceEndpointPicker
            kind="vlm"
            value={config.server_url == null ? "" : String(config.server_url)}
            className="h-7 w-96 text-sm"
            allowCustom={false}
            onPick={(svc) => {
              if (svc) onSetMany({ server_url: svc.url, model: svc.model ?? undefined, api_key: undefined })
            }}
          />
        )}
      </div>
    </div>
  )
}

// 파이프라인 시각화(읽기 전용) — 6단계 레일 + 본문/청크 보강 단계의 구성 transform 을 세로로 펼침.
const PII_IDS = new Set(["pii_regex", "pii_builtin", "pii_function"])

function PipelineGraph({
  postParse,
  postChunk,
  info,
  piiRules,
  piiFunctions,
  onNavigate,
}: {
  postParse: PipelineStage[]
  postChunk: PipelineStage[]
  info: (id: string) => TransformInfo | undefined
  piiRules: PiiRule[]
  piiFunctions: PiiFunction[]
  onNavigate: (phase: TransformPhase, idx?: number) => void
}) {
  function summarize(st: PipelineStage): string {
    const cfg = st.config ?? {}
    if (st.id === "pii_regex") {
      const name = cfg.rule_id
        ? piiRules.find((r) => r.rule_id === cfg.rule_id)?.name ?? "규칙"
        : "전체(enabled)"
      return `규칙: ${name}${cfg.mask ? ` · ${cfg.mask}` : ""}`
    }
    if (st.id === "pii_builtin") {
      const f = BUILTIN_PII_FUNCS.find((x) => x.value === cfg.function)
      return f ? `함수: ${f.label}${cfg.mask ? ` · ${cfg.mask}` : ""}` : "함수 미선택"
    }
    if (st.id === "pii_function") {
      const name = cfg.function_id
        ? piiFunctions.find((x) => x.function_id === cfg.function_id)?.name ?? "함수"
        : "전체(enabled)"
      return `함수: ${name}`
    }
    return Object.entries(cfg)
      .filter(([, v]) => v != null && v !== "")
      .map(([k, v]) => `${CONFIG_KEY_LABELS[k] ?? k}: ${v}`)
      .join(" · ")
  }

  const stages: { label: string; items?: PipelineStage[]; accent?: boolean; phase?: TransformPhase }[] = [
    { label: "파싱" },
    { label: "본문 보강", items: postParse, accent: true, phase: "post_parse" },
    { label: "청킹" },
    { label: "청크 보강", items: postChunk, accent: true, phase: "post_chunk" },
    { label: "임베딩" },
    { label: "색인" },
  ]

  return (
    <div className="overflow-x-auto rounded-lg border bg-muted/20 p-3">
      <div className="flex items-start gap-1">
        {stages.map((s, idx) => (
          <Fragment key={idx}>
            <div className="flex min-w-[120px] flex-col items-center gap-1.5">
              <div
                role={s.phase ? "button" : undefined}
                onClick={s.phase ? () => onNavigate(s.phase!) : undefined}
                className={cn(
                  "flex h-11 w-full items-center justify-center rounded-md border px-2 text-center text-sm font-medium",
                  s.accent ? "border-primary/40 bg-primary/5 text-foreground" : "bg-background text-muted-foreground",
                  s.phase && "cursor-pointer hover:border-primary hover:bg-primary/10"
                )}
              >
                {s.label}
              </div>
              {s.items &&
                (s.items.length === 0 ? (
                  <>
                    <ArrowDown className="size-3.5 text-muted-foreground/60" />
                    <div className="w-full rounded-md border border-dashed px-2 py-1 text-center text-[11px] text-muted-foreground">
                      보강 없음
                    </div>
                  </>
                ) : (
                  s.items.map((st, i) => (
                    <Fragment key={i}>
                      <ArrowDown className="size-3.5 text-muted-foreground/60" />
                      <div
                        role="button"
                        onClick={() => s.phase && onNavigate(s.phase, i)}
                        className={cn(
                          "w-full cursor-pointer rounded-md border px-2 py-1 hover:border-primary",
                          PII_IDS.has(st.id) ? "border-primary/40 bg-primary/5" : "bg-background"
                        )}
                      >
                        <div className="truncate text-xs font-medium">{info(st.id)?.label ?? st.id}</div>
                        {summarize(st) && (
                          <div className="truncate text-[11px] text-muted-foreground">{summarize(st)}</div>
                        )}
                      </div>
                    </Fragment>
                  ))
                ))}
            </div>
            {idx < stages.length - 1 && (
              <ArrowRight className="mt-3 size-4 shrink-0 text-muted-foreground" />
            )}
          </Fragment>
        ))}
      </div>
    </div>
  )
}
