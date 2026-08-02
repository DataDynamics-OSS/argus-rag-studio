// 라벨링 작업대 — 검색으로 후보 청크를 띄우고, 전문가가 정답/오답을 지정해 학습 데이터셋에 추가.
"use client"

import { useCallback, useEffect, useState } from "react"
import { CheckCircle2, MinusCircle, Search } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { TabsContent, TabsList, TabsTrigger } from "@workspace/ui/components/tabs"
import { Tooltip, TooltipContent, TooltipTrigger } from "@workspace/ui/components/tooltip"
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard-header"
import { useAuth } from "@/features/auth"
import { addExample, listDatasets } from "@/features/finetune/api"
import type { FtDataset, FtSplit } from "@/features/finetune/data/schema"
import { listCollections } from "@/features/collections/api"
import type { Collection } from "@/features/collections/data/schema"
import { search } from "@/features/search/api"
import type { ChunkHit } from "@/features/search/data/schema"
import { UrlTabs } from "@/components/url-tabs"

export default function FtLabelingPage() {
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser

  const [collections, setCollections] = useState<Collection[]>([])
  const [datasets, setDatasets] = useState<FtDataset[]>([])
  const [collectionId, setCollectionId] = useState("")
  const [datasetId, setDatasetId] = useState("")
  const [split, setSplit] = useState<FtSplit>("train")

  const [query, setQuery] = useState("")
  const [hits, setHits] = useState<ChunkHit[]>([])
  const [searching, setSearching] = useState(false)
  const [positiveId, setPositiveId] = useState<string | null>(null)
  const [negativeIds, setNegativeIds] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    try {
      const [cols, dss] = await Promise.all([listCollections({ page_size: 100 }), listDatasets()])
      setCollections(cols.items)
      setDatasets(dss)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "조회 실패")
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function onSearch() {
    if (!collectionId) {
      toast.error("지식베이스를 선택하세요.")
      return
    }
    if (!query.trim()) {
      toast.error("질의를 입력하세요.")
      return
    }
    setSearching(true)
    setPositiveId(null)
    setNegativeIds(new Set())
    try {
      const res = await search(Number(collectionId), { query: query.trim(), mode: "vector", top_k: 10 })
      setHits(res.hits)
      if (res.hits.length === 0) toast.info("검색 결과가 없습니다.")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "검색 실패")
    } finally {
      setSearching(false)
    }
  }

  function markPositive(id: string) {
    setPositiveId((cur) => (cur === id ? null : id))
    setNegativeIds((prev) => {
      const next = new Set(prev)
      next.delete(id)
      return next
    })
  }

  function toggleNegative(id: string) {
    if (positiveId === id) return
    setNegativeIds((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  async function onSave() {
    if (!datasetId) {
      toast.error("대상 학습 데이터셋을 선택하세요.")
      return
    }
    const positive = hits.find((h) => h.chunk_id === positiveId)
    if (!positive) {
      toast.error("정답(positive) 청크를 하나 선택하세요.")
      return
    }
    const negatives = hits.filter((h) => negativeIds.has(h.chunk_id)).map((h) => h.text)
    setSaving(true)
    try {
      await addExample(Number(datasetId), {
        query: query.trim(),
        positive: positive.text,
        negatives,
        split,
        source: "manual",
      })
      toast.success("학습 예시를 추가했습니다.")
      // 다음 라벨링을 위해 선택만 초기화(질의·검색결과는 유지)
      setPositiveId(null)
      setNegativeIds(new Set())
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "추가 실패")
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <DashboardHeader title="라벨링" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <UrlTabs defaultValue="label" className="flex flex-1 flex-col gap-4">
          <TabsList>
            <TabsTrigger value="label">라벨링</TabsTrigger>
            <TabsTrigger value="guide">라벨링 방법</TabsTrigger>
          </TabsList>

          <TabsContent value="guide" className="mt-0">
        <div className="flex max-w-4xl flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            질의를 검색해 후보 청크를 띄우고, <span className="font-medium text-foreground">정답 1개</span>와{" "}
            <span className="font-medium text-foreground">오답 여럿</span>을 지정해 학습 데이터셋에 추가합니다.
            전문가가 검수하며 라벨을 모을 때 씁니다.
          </p>

          {/* 정답/오답 정의 — 검색 임베딩 학습은 "관련/비관련 청크"를 가르치는 대조학습 */}
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/5 p-3">
              <div className="mb-1 flex items-center gap-1.5 text-sm font-medium text-emerald-700 dark:text-emerald-400">
                <CheckCircle2 className="size-4" /> 정답 (positive) — 관련 청크
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">
                질의에 <span className="font-medium text-foreground">실제로 답하는</span>, 검색돼야 하는 청크입니다.
                질의당 <span className="font-medium text-foreground">정확히 1개</span>. 답(예산·평가기준·과업 범위 등)이
                그 청크 본문에 들어 있어야 합니다.
              </p>
            </div>
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
              <div className="mb-1 flex items-center gap-1.5 text-sm font-medium text-amber-700 dark:text-amber-400">
                <MinusCircle className="size-4" /> 오답 (hard negative) — 혼동 청크
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">
                답이 아닌데 <span className="font-medium text-foreground">비슷해 보여 같이 검색되는</span> 청크(=함정)입니다.
                여러 개 지정. <span className="font-medium text-foreground">점수가 높은데 사실은 무관한</span> 청크일수록
                학습에 가장 유용합니다.
              </p>
            </div>
          </div>

          {/* 마킹 방법 */}
          <div className="rounded-lg border bg-muted/30 p-3">
            <p className="mb-1.5 text-sm font-medium">마킹 방법</p>
            <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
              <li><span className="font-medium text-foreground">라벨링</span> 탭에서 <span className="font-medium text-foreground">지식베이스 · 대상 학습 데이터셋 · Split</span>을 선택합니다.</li>
              <li>질의를 입력하고 검색해 후보 청크를 띄웁니다.</li>
              <li>질의에 정확히 답하는 청크 1개에{" "}
                <span className="font-medium text-emerald-700 dark:text-emerald-400">정답</span> 버튼을 누릅니다(다시 누르면 해제).</li>
              <li>비슷하지만 답이 아닌 청크들에{" "}
                <span className="font-medium text-amber-700 dark:text-amber-400">오답</span> 버튼을 누릅니다 —
                <span className="font-medium text-foreground"> 점수가 높은 근접 오답</span>을 우선 고르면 효과가 큽니다.</li>
              <li>목차·표 테두리 같은 <span className="font-medium text-foreground">구조성 청크</span>는 건너뜁니다(학습 가치 낮음).</li>
              <li><span className="font-medium text-foreground">데이터셋에 추가</span>를 누르면 한 건이 저장되고, 같은 검색결과에서 다음 질의로 이어갈 수 있습니다.</li>
            </ol>
            <p className="mt-2 text-sm text-muted-foreground">
              ※ 정답·오답은 <span className="font-medium text-foreground">&ldquo;맞는 답 / 틀린 답&rdquo;이 아니라 &ldquo;관련 / 비관련 청크&rdquo;</span>를 뜻합니다.
              모델이 <span className="font-medium text-foreground">질의↔정답은 가깝게, 질의↔오답은 멀게</span> 임베딩하도록 배우는 대조학습용 신호입니다.
            </p>
          </div>

          {/* split 설명 — 이 예시를 학습/검증/평가 어디에 쓸지 */}
          <div className="rounded-lg border bg-muted/30 p-3">
            <p className="mb-1.5 text-sm font-medium">Split — 이 예시를 어디에 쓸지</p>
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              <li>
                <span className="font-medium text-foreground">train</span> — 모델이 직접 학습하는 데이터입니다.
              </li>
              <li>
                <span className="font-medium text-foreground">valid</span> — 학습 중 성능을 점검(과적합 모니터링)하는 데이터로, 학습 자체에는 쓰지 않습니다.
              </li>
              <li>
                <span className="font-medium text-foreground">test</span> — 홀드아웃입니다. 학습·내보내기에서 제외하고{" "}
                <span className="font-medium text-foreground">최종 객관 평가에만</span> 써서 데이터 누수를 막습니다.
              </li>
            </ul>
            <p className="mt-2 text-sm text-muted-foreground">
              보통 train:valid 를 8:2 정도로 두고,{" "}
              <span className="font-medium text-foreground">같은 문서의 질의가 train·valid 양쪽에 섞이지 않도록</span> 문서 단위로 나눕니다.
            </p>
          </div>
        </div>
          </TabsContent>

          <TabsContent value="label" className="mt-0 flex flex-col gap-4">
        {/* 컨트롤 — 지식베이스 상세 메타데이터와 동일한 key/value 표(1행 3쌍) */}
        <table className="w-full table-fixed border-collapse text-sm text-black">
          <colgroup>
            <col className="w-[120px]" />
            <col />
            <col className="w-[150px]" />
            <col />
            <col className="w-[80px]" />
            <col />
          </colgroup>
          <tbody>
            <tr>
              <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">
                지식베이스
              </th>
              <td className="border px-2 py-1 align-middle">
                <Select value={collectionId} onValueChange={setCollectionId}>
                  <SelectTrigger className="h-8 w-full border-0 bg-transparent shadow-none focus:ring-0 focus-visible:ring-0">
                    <SelectValue placeholder="컬렉션 선택" />
                  </SelectTrigger>
                  <SelectContent>
                    {collections.map((c) => (
                      <SelectItem key={c.id} value={String(c.id)}>
                        {c.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </td>
              <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">
                대상 학습 데이터셋
              </th>
              <td className="border px-2 py-1 align-middle">
                <Select value={datasetId} onValueChange={setDatasetId}>
                  <SelectTrigger className="h-8 w-full border-0 bg-transparent shadow-none focus:ring-0 focus-visible:ring-0">
                    <SelectValue placeholder="데이터셋 선택" />
                  </SelectTrigger>
                  <SelectContent>
                    {datasets.map((d) => (
                      <SelectItem key={d.id} value={String(d.id)}>
                        {d.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </td>
              <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">
                Split
              </th>
              <td className="border px-2 py-1 align-middle">
                <Select value={split} onValueChange={(v) => setSplit(v as FtSplit)}>
                  <SelectTrigger className="h-8 w-full border-0 bg-transparent shadow-none focus:ring-0 focus-visible:ring-0">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="train">train</SelectItem>
                    <SelectItem value="valid">valid</SelectItem>
                    <SelectItem value="test">test</SelectItem>
                  </SelectContent>
                </Select>
              </td>
            </tr>
          </tbody>
        </table>

        {/* 질의 + 검색 */}
        <div className="flex gap-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onSearch()}
            placeholder="질의를 입력하고 검색하세요…"
          />
          <Button onClick={onSearch} disabled={searching}>
            <Search className="size-4" /> {searching ? "검색 중…" : "검색"}
          </Button>
          {canManage && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex" tabIndex={0}>
                  <Button variant="default" onClick={onSave} disabled={saving || !positiveId}>
                    {saving ? "추가 중…" : "데이터셋에 추가"}
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent>
                후보 청크에서 정답·오답을 선택한 뒤 이 버튼을 누르면 학습 데이터셋에 추가됩니다.
              </TooltipContent>
            </Tooltip>
          )}
        </div>

        {/* 후보 청크 */}
        <div className="flex flex-col gap-2">
          {hits.map((h) => {
            const isPos = positiveId === h.chunk_id
            const isNeg = negativeIds.has(h.chunk_id)
            return (
              <div
                key={h.chunk_id}
                className={`rounded-lg border p-3 text-sm transition-colors ${
                  isPos
                    ? "border-emerald-500/50 bg-emerald-500/5"
                    : isNeg
                      ? "border-amber-500/50 bg-amber-500/5"
                      : ""
                }`}
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="text-sm text-black">
                    {h.document_name} · score {h.score.toFixed(3)}
                  </span>
                  {canManage && (
                    <span className="flex items-center gap-1">
                      <Button
                        variant="outline"
                        size="sm"
                        className={`h-7 ${
                          isPos
                            ? "border-emerald-600 bg-emerald-600 text-white hover:bg-emerald-600/90 hover:text-white"
                            : "border-emerald-500/40 text-emerald-700 hover:bg-emerald-500/10 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-400"
                        }`}
                        onClick={() => markPositive(h.chunk_id)}
                      >
                        <CheckCircle2 className="size-3.5" /> 정답
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className={`h-7 ${
                          isNeg
                            ? "border-amber-500 bg-amber-500 text-white hover:bg-amber-500/90 hover:text-white"
                            : "border-amber-500/40 text-amber-700 hover:bg-amber-500/10 hover:text-amber-700 dark:text-amber-400 dark:hover:text-amber-400"
                        }`}
                        onClick={() => toggleNegative(h.chunk_id)}
                        disabled={isPos}
                      >
                        <MinusCircle className="size-3.5" /> 오답
                      </Button>
                    </span>
                  )}
                </div>
                <p className="text-sm text-black">{h.text}</p>
              </div>
            )
          })}
        </div>
          </TabsContent>
        </UrlTabs>
      </div>
    </>
  )
}
