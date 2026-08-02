// 파이프라인 상세 — 설정 편집(새 버전) + 버전 목록/롤백 + diff + 버전 비교(실험).
"use client"

import { useCallback, useEffect, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import { ArrowLeft, ChevronDown, ChevronRight, FileImage, FileText, GitCompare, Loader2, Save, Trash2 } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import { Badge } from "@workspace/ui/components/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@workspace/ui/components/card"
import { Checkbox } from "@workspace/ui/components/checkbox"
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
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { Tooltip, TooltipContent, TooltipTrigger } from "@workspace/ui/components/tooltip"
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard-header"
import { useAuth } from "@/features/auth"
import {
  activateVersion,
  compare,
  deletePipeline,
  getDiff,
  getPipeline,
  listVersions,
  updateConfig,
  updateMeta,
} from "@/features/pipelines/api"
import type {
  CompareResult,
  Diff,
  Pipeline,
  PipelineConfig,
  PipelineVersion,
} from "@/features/pipelines/data/schema"
import { listCollections } from "@/features/collections/api"
import type { Collection } from "@/features/collections/data/schema"
import type { ChunkHit } from "@/features/search/data/schema"
import { getChunkEvidence, getDocumentPageImage } from "@/features/search/api"
import { ChunkImageRefs, ImageTypeBadges } from "@/features/search/components/image-type-badges"
import { DocumentInspectDialog } from "@/features/documents/components/document-inspect-dialog"

// 프리셋 — 검색/리랭크/생성 값을 한 번에 채운다. generation.model 은 건드리지 않는다(전역/사용자 유지).
type PresetPatch = {
  retrieval: Partial<PipelineConfig["retrieval"]>
  rerank: Partial<PipelineConfig["rerank"]>
  generation: Partial<PipelineConfig["generation"]>
}
const PRESETS: Record<string, { label: string; desc: string; patch: PresetPatch }> = {
  recommended: {
    label: "권장 (균형)",
    desc: "하이브리드 검색 + 리랭크. 대부분의 경우에 적합한 기본값.",
    patch: {
      retrieval: { mode: "hybrid", top_k: 5, vector_k: 20, lexical_k: 20, rrf_k: 60, distance_metric: "" },
      rerank: { enabled: true, provider: "cross_encoder", top_n: 5 },
      generation: { max_tokens: 2048, temperature: 0.2 },
    },
  },
  precise: {
    label: "정밀 (품질↑)",
    desc: "후보·반환 수를 늘리고 리랭크. 품질 우선(느리고 비용↑).",
    patch: {
      retrieval: { mode: "hybrid", top_k: 8, vector_k: 40, lexical_k: 40, rrf_k: 60, distance_metric: "" },
      rerank: { enabled: true, provider: "cross_encoder", top_n: 8 },
      generation: { max_tokens: 4096, temperature: 0.1 },
    },
  },
  cheap: {
    label: "저비용 (속도·비용↓)",
    desc: "벡터 검색만·리랭크 끔·짧은 응답. 빠르고 저렴.",
    patch: {
      retrieval: { mode: "vector", top_k: 3, vector_k: 12, lexical_k: 10, rrf_k: 60, distance_metric: "" },
      rerank: { enabled: false, provider: "none", top_n: 3 },
      generation: { max_tokens: 1024, temperature: 0.2 },
    },
  },
}

// 현재 설정이 어느 프리셋과 일치하는지 — 일치 항목이 모두 같으면 그 프리셋, 아니면 "custom".
function detectPreset(cfg: PipelineConfig): string {
  for (const [key, p] of Object.entries(PRESETS)) {
    const r = p.patch
    const eq =
      (Object.keys(r.retrieval) as (keyof PipelineConfig["retrieval"])[]).every((k) => cfg.retrieval[k] === r.retrieval[k]) &&
      (Object.keys(r.rerank) as (keyof PipelineConfig["rerank"])[]).every((k) => cfg.rerank[k] === r.rerank[k]) &&
      (Object.keys(r.generation) as (keyof PipelineConfig["generation"])[]).every((k) => cfg.generation[k] === r.generation[k])
    if (eq) return key
  }
  return "custom"
}

export default function PipelineDetailPage() {
  const params = useParams()
  const router = useRouter()
  // 외부 노출은 파이프라인 UUID. 내부 작업은 해석된 pipeline.id(정수 PK)를 쓴다.
  const uuid = String(params.id)
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser

  const [pipeline, setPipeline] = useState<Pipeline | null>(null)
  const [versions, setVersions] = useState<PipelineVersion[]>([])
  const [cfg, setCfg] = useState<PipelineConfig | null>(null)
  const [collections, setCollections] = useState<Collection[]>([])
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [note, setNote] = useState("") // 저장 시 남길 비고(변경 사유)

  // diff
  const [diffA, setDiffA] = useState("")
  const [diffB, setDiffB] = useState("")
  const [diff, setDiff] = useState<Diff | null>(null)
  // compare
  const [cmpCol, setCmpCol] = useState("")
  const [cmpQuery, setCmpQuery] = useState("")
  const [cmpA, setCmpA] = useState("")
  const [cmpB, setCmpB] = useState("")
  const [cmp, setCmp] = useState<CompareResult | null>(null)
  const [inspectDoc, setInspectDoc] = useState<{ uuid: string; name: string; text: string } | null>(null)

  const refresh = useCallback(async () => {
    try {
      const p = await getPipeline(uuid) // UUID 로 파이프라인 해석(내부 PK 포함)
      const [vs, cols] = await Promise.all([
        listVersions(p.id),
        listCollections({ page_size: 100 }),
      ])
      setPipeline(p)
      setCfg(p.config)
      setVersions(vs)
      setCollections(cols.items)
      if (cols.items.length && !cmpCol) setCmpCol(String(cols.items[0]!.id))
      if (vs.length >= 2) {
        setDiffA(String(vs[vs.length - 1]!.version))
        setDiffB(String(vs[0]!.version))
        setCmpA(String(vs[vs.length - 1]!.version))
        setCmpB(String(vs[0]!.version))
      } else if (vs.length === 1) {
        setCmpA(String(vs[0]!.version))
        setCmpB(String(vs[0]!.version))
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "조회 실패")
    }
  }, [uuid, cmpCol])

  useEffect(() => {
    if (uuid && uuid !== "undefined") refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uuid])

  function setR<K extends keyof PipelineConfig["retrieval"]>(k: K, v: PipelineConfig["retrieval"][K]) {
    setCfg((c) => (c ? { ...c, retrieval: { ...c.retrieval, [k]: v } } : c))
  }
  function setRr<K extends keyof PipelineConfig["rerank"]>(k: K, v: PipelineConfig["rerank"][K]) {
    setCfg((c) => (c ? { ...c, rerank: { ...c.rerank, [k]: v } } : c))
  }
  function setG<K extends keyof PipelineConfig["generation"]>(k: K, v: PipelineConfig["generation"][K]) {
    setCfg((c) => (c ? { ...c, generation: { ...c.generation, [k]: v } } : c))
  }

  function applyPreset(key: string) {
    const p = PRESETS[key]
    if (!p) return
    setCfg((c) =>
      c
        ? {
            retrieval: { ...c.retrieval, ...p.patch.retrieval },
            rerank: { ...c.rerank, ...p.patch.rerank },
            generation: { ...c.generation, ...p.patch.generation }, // model 은 patch 에 없어 유지됨
          }
        : c,
    )
  }

  async function handleSave() {
    if (!pipeline || !cfg) return
    try {
      await updateConfig(pipeline.id, cfg, note.trim() || undefined)
      toast.success("새 버전을 저장했습니다.")
      setNote("")
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "저장 실패")
    }
  }

  async function handleStageChange(stage: string) {
    if (!pipeline || stage === pipeline.stage) return
    try {
      const p = await updateMeta(pipeline.id, { stage })
      setPipeline(p) // 버전 생성 없는 메타 변경 — 화면만 갱신
      toast.success(`스테이지를 ${stage} 로 변경했습니다.`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "스테이지 변경 실패")
    }
  }

  async function handleActivate(version: number) {
    if (!pipeline) return
    try {
      await activateVersion(pipeline.id, version)
      toast.success(`v${version} 로 롤백했습니다.`)
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "활성화 실패")
    }
  }

  async function handleDiff() {
    if (!pipeline) return
    try {
      setDiff(await getDiff(pipeline.id, Number(diffA), Number(diffB)))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "diff 실패")
    }
  }

  async function handleCompare() {
    if (!pipeline || !cmpCol || !cmpQuery.trim()) return
    try {
      setCmp(
        await compare(pipeline.id, {
          query: cmpQuery,
          collection_id: Number(cmpCol),
          version_a: Number(cmpA),
          version_b: Number(cmpB),
        })
      )
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "비교 실패")
    }
  }

  if (!pipeline || !cfg) return null

  return (
    <>
      <DashboardHeader title={pipeline.name} />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <div className="flex items-center justify-between">
          <Button variant="ghost" size="sm" onClick={() => router.push("/dashboard/pipelines")}>
            <ArrowLeft className="size-4" />
            목록으로
          </Button>
          <div className="flex items-center gap-2">
            {canManage ? (
              <Select value={pipeline.stage} onValueChange={handleStageChange}>
                <SelectTrigger className="h-8 w-[120px]" aria-label="스테이지">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="dev">dev</SelectItem>
                  <SelectItem value="staging">staging</SelectItem>
                  <SelectItem value="prod">prod</SelectItem>
                </SelectContent>
              </Select>
            ) : (
              <Badge variant="outline">{pipeline.stage}</Badge>
            )}
            <Badge variant="secondary">활성 v{pipeline.active_version}</Badge>
            {canManage && (
              <Button
                variant="destructive"
                size="sm"
                onClick={() => {
                  if (confirm("이 파이프라인을 삭제할까요?"))
                    deletePipeline(pipeline.id).then(() => router.replace("/dashboard/pipelines"))
                }}
              >
                <Trash2 className="size-4" />
                삭제
              </Button>
            )}
          </div>
        </div>

        {/* 설정 편집 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">설정 (저장 시 새 버전 생성)</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {/* 프리셋 — 한 번에 값 채우기 */}
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-medium text-muted-foreground">프리셋</span>
              <Select value={detectPreset(cfg)} onValueChange={applyPreset} disabled={!canManage}>
                <SelectTrigger className="h-8 w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="recommended">권장 (균형)</SelectItem>
                  <SelectItem value="precise">정밀 (품질↑)</SelectItem>
                  <SelectItem value="cheap">저비용 (속도·비용↓)</SelectItem>
                  <SelectItem value="custom" disabled>
                    사용자 지정
                  </SelectItem>
                </SelectContent>
              </Select>
              <span className="text-xs text-muted-foreground">
                {detectPreset(cfg) === "custom"
                  ? "프리셋과 다르게 직접 조정됨 — 고급 설정에서 값을 볼 수 있습니다."
                  : PRESETS[detectPreset(cfg)]?.desc}
              </span>
            </div>

            {/* 고급 설정 토글(기본 접힘) */}
            <button
              type="button"
              onClick={() => setAdvancedOpen((o) => !o)}
              className="flex w-fit items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
            >
              {advancedOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
              고급 설정 (검색 · 리랭크 · 생성 세부)
            </button>

            {advancedOpen && (
              <div className="flex flex-col gap-5 border-l-2 pl-3">
                <SettingTable title="검색">
                  <SettingRow name="방식 (mode)" path="retrieval.mode">
                    <Select value={cfg.retrieval.mode} onValueChange={(v) => setR("mode", v as PipelineConfig["retrieval"]["mode"])} disabled={!canManage}>
                      <SelectTrigger className="h-8 w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="hybrid">하이브리드</SelectItem>
                        <SelectItem value="vector">벡터</SelectItem>
                        <SelectItem value="lexical">렉시컬</SelectItem>
                      </SelectContent>
                    </Select>
                  </SettingRow>
                  <SettingRow name="거리 메트릭 (distance_metric)" path="retrieval.distance_metric">
                    <Select
                      value={cfg.retrieval.distance_metric || "__inherit__"}
                      onValueChange={(v) => setR("distance_metric", v === "__inherit__" ? "" : v)}
                      disabled={!canManage}
                    >
                      <SelectTrigger className="h-8 w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__inherit__">컬렉션 상속</SelectItem>
                        <SelectItem value="cosine">cosine</SelectItem>
                        <SelectItem value="l2">l2</SelectItem>
                        <SelectItem value="inner_product">inner_product</SelectItem>
                      </SelectContent>
                    </Select>
                  </SettingRow>
                  <SettingRow name="top_k" path="retrieval.top_k">
                    <NumCell value={cfg.retrieval.top_k} onChange={(v) => setR("top_k", v)} disabled={!canManage} />
                  </SettingRow>
                  <SettingRow name="vector_k" path="retrieval.vector_k">
                    <NumCell value={cfg.retrieval.vector_k} onChange={(v) => setR("vector_k", v)} disabled={!canManage} />
                  </SettingRow>
                  <SettingRow name="lexical_k" path="retrieval.lexical_k">
                    <NumCell value={cfg.retrieval.lexical_k} onChange={(v) => setR("lexical_k", v)} disabled={!canManage} />
                  </SettingRow>
                  <SettingRow name="rrf_k" path="retrieval.rrf_k">
                    <NumCell value={cfg.retrieval.rrf_k} onChange={(v) => setR("rrf_k", v)} disabled={!canManage} />
                  </SettingRow>
                </SettingTable>

                <SettingTable title="리랭크">
                  <SettingRow name="사용 (enabled)" path="rerank.enabled">
                    <div className="flex h-8 items-center">
                      <Checkbox checked={cfg.rerank.enabled} onCheckedChange={(v) => setRr("enabled", !!v)} disabled={!canManage} />
                    </div>
                  </SettingRow>
                  <SettingRow name="provider" path="rerank.provider">
                    <Select value={cfg.rerank.provider} onValueChange={(v) => setRr("provider", v)} disabled={!canManage}>
                      <SelectTrigger className="h-8 w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="none">none</SelectItem>
                        <SelectItem value="llm">llm</SelectItem>
                        <SelectItem value="local">local (인프로세스)</SelectItem>
                        <SelectItem value="cross_encoder">cross_encoder</SelectItem>
                      </SelectContent>
                    </Select>
                  </SettingRow>
                  <SettingRow name="top_n" path="rerank.top_n">
                    <NumCell value={cfg.rerank.top_n} onChange={(v) => setRr("top_n", v)} disabled={!canManage} />
                  </SettingRow>
                </SettingTable>

                <SettingTable title="생성">
                  <SettingRow name="모델 (model)" path="generation.model">
                    <Input className="h-8" value={cfg.generation.model} onChange={(e) => setG("model", e.target.value)} disabled={!canManage} placeholder="빈 값=전역" />
                  </SettingRow>
                  <SettingRow name="max_tokens" path="generation.max_tokens">
                    <NumCell value={cfg.generation.max_tokens} onChange={(v) => setG("max_tokens", v)} disabled={!canManage} />
                  </SettingRow>
                  <SettingRow name="temperature" path="generation.temperature">
                    <NumCell value={cfg.generation.temperature} step="0.1" onChange={(v) => setG("temperature", v)} disabled={!canManage} />
                  </SettingRow>
                </SettingTable>
              </div>
            )}
            {canManage && (
              <div className="flex flex-col gap-2 border-t pt-4 sm:flex-row sm:items-end">
                <div className="flex flex-1 flex-col gap-1.5">
                  <Label className="text-xs text-muted-foreground">비고 (변경 사유 — 버전 목록에 표시)</Label>
                  <Input
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="예: 정밀 프리셋 적용, top_k 8로 상향"
                  />
                </div>
                <Button onClick={handleSave}>
                  <Save className="size-4" />
                  새 버전으로 저장
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        {/* 버전 + diff */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-medium">버전</CardTitle>
            <div className="flex items-center gap-2 text-xs">
              <VersionSelect versions={versions} value={diffA} onChange={setDiffA} />
              <span className="text-muted-foreground">→</span>
              <VersionSelect versions={versions} value={diffB} onChange={setDiffB} />
              <Button variant="outline" size="sm" onClick={handleDiff} disabled={versions.length < 2}>
                <GitCompare className="size-3.5" />
                비교
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-20">버전</TableHead>
                  <TableHead>비고</TableHead>
                  <TableHead className="text-right">작업</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {versions.map((v) => (
                  <TableRow key={v.version}>
                    <TableCell>
                      v{v.version}
                      {v.version === pipeline.active_version && (
                        <Badge variant="secondary" className="ml-2 h-4">활성</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{v.note ?? "-"}</TableCell>
                    <TableCell className="text-right">
                      {canManage && v.version !== pipeline.active_version && (
                        <Button variant="outline" size="xs" onClick={() => handleActivate(v.version)}>
                          이 버전 활성화
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {diff && (
              <div className="mt-3 flex flex-col gap-2">
                <p className="text-xs font-medium text-muted-foreground">
                  v{diff.from_version} → v{diff.to_version} 변경 ({diff.changes.length})
                </p>
                {diff.changes.length === 0 ? (
                  <p className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">차이 없음</p>
                ) : (
                  <div className="overflow-hidden rounded-lg border">
                    <table className="w-full text-left text-sm">
                      <thead className="bg-muted/50 text-muted-foreground">
                        <tr>
                          <th className="w-44 p-2">설정</th>
                          <th className="w-28 p-2">v{diff.from_version} (이전)</th>
                          <th className="w-28 p-2">v{diff.to_version} (대상)</th>
                          <th className="p-2">설명</th>
                        </tr>
                      </thead>
                      <tbody>
                        {diff.changes.map((c) => (
                          <tr key={c.path} className="border-t align-top">
                            <td className="p-2">
                              <div className="font-medium text-foreground">{fieldLabel(c.path)}</div>
                              <div className="text-xs text-muted-foreground">{c.path}</div>
                            </td>
                            <td className="p-2 text-destructive">{fmtValue(c.from_value)}</td>
                            <td className="p-2 text-primary">{fmtValue(c.to_value)}</td>
                            <td className="p-2 text-muted-foreground">{fieldDesc(c.path)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* 버전 비교(실험) */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">버전 비교 (동일 질의를 두 버전으로 검색)</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="flex flex-wrap items-end gap-2">
              <Field label="지식베이스">
                <Select value={cmpCol} onValueChange={setCmpCol}>
                  <SelectTrigger className="w-48">
                    <SelectValue placeholder="컬렉션" />
                  </SelectTrigger>
                  <SelectContent>
                    {collections.map((c) => (
                      <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="버전 A"><VersionSelect versions={versions} value={cmpA} onChange={setCmpA} /></Field>
              <Field label="버전 B"><VersionSelect versions={versions} value={cmpB} onChange={setCmpB} /></Field>
              <Input
                className="min-w-48 flex-1"
                value={cmpQuery}
                onChange={(e) => setCmpQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && cmpCol && cmpQuery.trim()) {
                    e.preventDefault()
                    handleCompare()
                  }
                }}
                placeholder="질문 (Enter 로 비교)"
              />
              <Button onClick={handleCompare} disabled={!cmpCol || !cmpQuery.trim()}>검색 결과 비교</Button>
            </div>
            <p className="text-xs text-muted-foreground">
              각 버전의 검색 설정(top_k·리랭크 top_n)만큼 결과가 반환됩니다. 더 많이 보려면 해당 버전의 top_k 를 늘려 저장하십시오.
            </p>
            {cmp && (
              <div className="grid gap-3 lg:grid-cols-2">
                {[cmp.a, cmp.b].map((side, i) => (
                  <div key={i} className="flex flex-col gap-2 rounded-lg border p-2">
                    <p className="px-1 text-xs font-medium text-muted-foreground">
                      v{side.version} — 청크 {side.hits.length}개
                    </p>
                    {side.hits.length === 0 ? (
                      <p className="px-1 py-4 text-center text-xs text-muted-foreground">검색 결과가 없습니다.</p>
                    ) : (
                      side.hits.map((h, j) => (
                        <CompareHit
                          key={h.chunk_id}
                          h={h}
                          rank={j + 1}
                          query={cmp.query}
                          onInspect={() => setInspectDoc({ uuid: h.document_uuid, name: h.document_name, text: h.text })}
                        />
                      ))
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <DocumentInspectDialog
          documentId={inspectDoc?.uuid ?? null}
          documentName={inspectDoc?.name ?? ""}
          highlightText={inspectDoc?.text}
          open={inspectDoc !== null}
          onOpenChange={(o) => !o && setInspectDoc(null)}
        />
      </div>
    </>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  )
}

// 질의어가 청크에 직접 등장하는지(키워드 매칭). 표시 전용 — 랭킹엔 영향 없음(Playground 와 동일 규칙).
function chunkHasKeyword(text: string, query: string): boolean {
  const terms = query.toLowerCase().split(/\s+/).map((t) => t.trim()).filter((t) => t.length >= 2)
  if (terms.length === 0) return false
  const lower = text.toLowerCase()
  return terms.some((t) => lower.includes(t))
}

// 버전 비교 — 한 청크 렌더. 지식베이스 검색(Playground)과 같은 정보량으로 보여준다.
function CompareHit({ h, rank, query, onInspect }: { h: ChunkHit; rank: number; query: string; onInspect: () => void }) {
  return (
    <div className="rounded-md border p-3">
      <div className="mb-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="outline" className="h-5">#{rank}</Badge>
        {chunkHasKeyword(h.text, query) ? (
          <Badge variant="secondary" className="h-5 shrink-0 border-emerald-200 bg-emerald-50 font-normal text-emerald-700"
            title="질의어가 이 청크에 직접 등장합니다(키워드 매칭).">키워드</Badge>
        ) : (
          <Badge variant="outline" className="h-5 shrink-0 font-normal text-muted-foreground"
            title="질의어가 직접 없지만 의미가 유사해 검색된 결과입니다(의미 매칭).">의미</Badge>
        )}
        <FileText className="size-3.5 shrink-0" />
        <span className="font-medium text-foreground">{h.document_name}</span>
        <ImageTypeBadges types={h.document_image_types} />
        <span>seq {h.seq}</span>
        <OriginalViewButton h={h} onInspect={onInspect} />
        <span className="ml-auto">score {h.score.toFixed(4)}</span>
      </div>
      <p className="whitespace-pre-wrap text-sm text-muted-foreground">{h.text}</p>
      <ChunkImageRefs refs={h.image_refs} />
    </div>
  )
}

const HWP_RE = /\.hwpx?$/i

// 원본 보기 — HWP/HWPX 이고 렌더 가능한 경우 '원본 페이지'(이미지)를, 그 외/렌더 불가 시
// '문서 전체 보기'(onInspect)로 자동 폴백한다. 어떤 동작인지 tooltip 으로 안내한다.
function OriginalViewButton({ h, onInspect }: { h: ChunkHit; onInspect: () => void }) {
  const isHwp = HWP_RE.test(h.document_name)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [img, setImg] = useState<string | null>(null)
  const [info, setInfo] = useState<{ page: number; total: number } | null>(null)

  function close(o: boolean) {
    setOpen(o)
    if (!o && img) {
      URL.revokeObjectURL(img)
      setImg(null)
      setInfo(null)
    }
  }

  async function onClick() {
    if (!isHwp) {
      onInspect() // 원본 페이지 미지원 형식 → 문서 전체 보기
      return
    }
    setLoading(true)
    try {
      const ev = await getChunkEvidence(h.chunk_id)
      if (!ev.available || !ev.page) {
        onInspect() // 렌더 서비스 미설정/페이지 추정 불가 → 폴백
        return
      }
      const blob = await getDocumentPageImage(ev.document_uuid, ev.page)
      setInfo({ page: ev.page, total: ev.total_pages ?? 0 })
      setImg(URL.createObjectURL(blob))
      setOpen(true)
    } catch {
      onInspect() // 렌더 실패 시에도 에러 대신 문서 전체 보기로 폴백
    } finally {
      setLoading(false)
    }
  }

  const label = isHwp ? "원본 페이지" : "문서 전체 보기"
  const tip = isHwp
    ? "원본 문서의 해당 페이지를 봅니다. 표시할 수 없으면 문서 전체 보기로 열립니다."
    : "원본(파싱) 전문을 봅니다. 이 형식은 원본 페이지 보기를 지원하지 않습니다."

  return (
    <>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={onClick}
            disabled={loading}
            className="inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
          >
            {loading ? <Loader2 className="size-3 animate-spin" /> : <FileImage className="size-3" />}
            {label}
          </button>
        </TooltipTrigger>
        <TooltipContent>{tip}</TooltipContent>
      </Tooltip>
      <Dialog open={open} onOpenChange={close}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle className="truncate text-sm">
              {h.document_name}
              {info ? ` · p.${info.page}/${info.total}` : ""}
            </DialogTitle>
          </DialogHeader>
          <div className="max-h-[75vh] overflow-auto">
            {img ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={img} alt="원본 페이지" className="w-full rounded border" />
            ) : null}
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}

// 고급 설정 — 설정/값/설명 3열 테이블. 그룹별로 하나씩 둔다.
function SettingTable({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-2 text-xs font-medium text-muted-foreground">{title}</p>
      <div className="overflow-hidden rounded-lg border">
        <table className="w-full text-left text-sm">
          <thead className="bg-muted/50 text-muted-foreground">
            <tr>
              <th className="w-44 p-2">설정</th>
              <th className="w-40 p-2">값</th>
              <th className="p-2">설명</th>
            </tr>
          </thead>
          <tbody>{children}</tbody>
        </table>
      </div>
    </div>
  )
}

function SettingRow({ name, path, children }: { name: string; path: string; children: React.ReactNode }) {
  return (
    <tr className="border-t align-top">
      <td className="p-2 align-middle text-foreground">{name}</td>
      <td className="p-2 align-middle">{children}</td>
      <td className="p-2 text-muted-foreground">{fieldDesc(path)}</td>
    </tr>
  )
}

// 설정 경로(예: retrieval.top_k) → 사람이 읽는 이름. 고급 설정과 같은 명칭을 쓴다.
const FIELD_LABELS: Record<string, string> = {
  "retrieval.mode": "검색 방식",
  "retrieval.distance_metric": "거리 메트릭",
  "retrieval.top_k": "top_k",
  "retrieval.vector_k": "vector_k",
  "retrieval.lexical_k": "lexical_k",
  "retrieval.rrf_k": "rrf_k",
  "rerank.enabled": "리랭크 사용",
  "rerank.provider": "리랭크 provider",
  "rerank.top_n": "리랭크 top_n",
  "generation.model": "생성 모델",
  "generation.max_tokens": "max_tokens",
  "generation.temperature": "temperature",
}

function fieldLabel(path: string): string {
  return FIELD_LABELS[path] ?? path
}

// 설정 경로 → 설명. 고급 설정·비교 표가 같은 설명을 공유한다(중복 방지).
const FIELD_DESCRIPTIONS: Record<string, string> = {
  "retrieval.mode": "질의를 어떻게 매칭할지 정합니다. 하이브리드=의미(벡터)+키워드(렉시컬)를 RRF로 결합, 벡터=의미 유사도만, 렉시컬=키워드 일치만. 대부분 하이브리드를 권장합니다.",
  "retrieval.distance_metric": "벡터 유사도를 계산하는 방식입니다. '컬렉션 상속'이면 지식베이스 생성 시 지정한 값을 따릅니다. cosine=방향 유사도(일반적), l2=유클리드 거리, inner_product=내적. 렉시컬 검색에는 적용되지 않습니다.",
  "retrieval.top_k": "최종적으로 반환하거나 LLM에 넘길 청크 수입니다. 너무 크면 관련 없는 내용이 섞여 노이즈·비용이 늘고, 너무 작으면 근거가 누락될 수 있습니다.",
  "retrieval.vector_k": "벡터(의미) 검색이 1차로 가져올 후보 수입니다. 하이브리드에서 병합 전 후보 풀(pool)이 되며, 클수록 재현율↑·비용↑.",
  "retrieval.lexical_k": "렉시컬(키워드) 검색이 1차로 가져올 후보 수입니다. 하이브리드에서 병합 전 후보 풀이 되며, 고유명사·코드·숫자 등 정확 일치를 보완합니다.",
  "retrieval.rrf_k": "하이브리드 RRF(Reciprocal Rank Fusion) 병합 상수입니다. 클수록 순위 차이를 완만하게 반영해 상위 가중을 약화합니다. 보통 60을 씁니다.",
  "rerank.enabled": "1차 검색 결과를 한 번 더 정밀하게 재정렬할지 여부입니다. 켜면 상위 정확도가 오르지만 지연·비용이 늘어납니다.",
  "rerank.provider": "리랭커 종류입니다. none=미사용, llm=LLM이 관련도 채점, local=인프로세스 cross-encoder, cross_encoder=외부 리랭커 서버. 사용이 꺼져 있으면 적용되지 않습니다.",
  "rerank.top_n": "리랭크 후 남길 상위 청크 수입니다. 보통 top_k 와 같거나 작게 설정해 최종 근거를 추립니다.",
  "generation.model": "답변을 생성할 LLM입니다. 비워 두면 전역/사용자 설정 모델을 사용합니다. 파이프라인별로 다른 모델을 쓰려면 지정하십시오.",
  "generation.max_tokens": "답변의 최대 길이(토큰)입니다. 길수록 자세하지만 비용·지연이 늘어납니다.",
  "generation.temperature": "생성의 무작위성입니다. 0에 가까울수록 일관·결정적이고, 높을수록 다양·창의적입니다. 근거에 충실해야 하는 RAG에서는 0.1~0.3을 권장합니다.",
}

function fieldDesc(path: string): string {
  return FIELD_DESCRIPTIONS[path] ?? ""
}

// 빈 문자열/누락은 의미가 안 통하므로 표시용으로 치환한다(distance_metric 빈 값=컬렉션 상속 등).
function fmtValue(v: string | null): string {
  if (v === null || v === "") return "(빈 값)"
  return v
}

function NumCell({
  value, onChange, step, disabled,
}: { value: number; onChange: (v: number) => void; step?: string; disabled?: boolean }) {
  return (
    <Input
      type="number"
      step={step}
      value={value}
      onChange={(e) => onChange(step ? parseFloat(e.target.value) : parseInt(e.target.value, 10))}
      disabled={disabled}
      className="h-8 w-full"
    />
  )
}

function VersionSelect({
  versions, value, onChange,
}: { versions: PipelineVersion[]; value: string; onChange: (v: string) => void }) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="w-24">
        <SelectValue placeholder="버전" />
      </SelectTrigger>
      <SelectContent>
        {versions.map((v) => (
          <SelectItem key={v.version} value={String(v.version)}>v{v.version}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
