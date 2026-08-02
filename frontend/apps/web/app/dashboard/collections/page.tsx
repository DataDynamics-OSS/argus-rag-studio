// 지식베이스(컬렉션) 목록 + 생성 다이얼로그. 슈퍼유저/관리자만 생성 가능.
"use client"

import { useCallback, useEffect, useState, type FormEvent } from "react"
import Link from "next/link"
import { Boxes, HelpCircle, Plus } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Textarea } from "@workspace/ui/components/textarea"
import { TooltipProvider } from "@workspace/ui/components/tooltip"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { getCoreRowModel, useReactTable } from "@tanstack/react-table"
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard-header"
import { ServiceEndpointPicker } from "@/features/deploy/components/service-endpoint-picker"
import { DataTablePagination } from "@/components/data-table"
import { useAuth } from "@/features/auth"
import {
  checkEmbeddingServer,
  createCollection,
  listCollections,
  listLocalEmbeddingModels,
  listLocalRerankModels,
  listParseStrategies,
  listRerankModels,
  listServerEmbeddingModels,
  probeEmbeddingDimension,
} from "@/features/collections/api"
import {
  ConfigRow,
  ConfigTable,
  COLLECTION_HINTS as HINTS,
  digitsOnly,
} from "@/features/collections/components/config-table"
import { CollectionConfigHelp } from "@/features/collections/components/collection-config-help"
import type {
  ChunkStrategy,
  ChunkUnit,
  Collection,
  DistanceMetric,
  EmbeddingProviderKind,
  LocalEmbeddingModel,
  ParseStrategy,
  ParseStrategyInfo,
  RerankProviderKind,
} from "@/features/collections/data/schema"

const RERANK_PROVIDER_LABELS: Record<RerankProviderKind, string> = {
  none: "none — 리랭크 안 함",
  llm: "llm — 생성 LLM 으로 재정렬",
  local: "local — 자체 cross-encoder(서버 불필요)",
  cross_encoder: "cross_encoder — 외부 리랭크 서버",
}

const CHUNK_STRATEGY_LABELS: Record<ChunkStrategy, string> = {
  auto: "auto — 내용 자동(표·헤딩 있으면 markdown)",
  recursive: "recursive — 구조 보존(범용 기본)",
  sentence: "sentence — 문장 보존(FAQ·QA)",
  paragraph: "paragraph — 문단(빈 줄) 보존(산문·보고서)",
  section: "section — 섹션 헤더(헤딩·번호·장/절) 보존",
  fixed: "fixed — 고정 길이 윈도우",
  markdown: "markdown — 표·헤딩 보존(파싱 layout/docai/vlm 짝)",
  semantic: "semantic — 의미 경계 분할(문장 임베딩, 비용↑)",
}

const CHUNK_UNIT_LABELS: Record<ChunkUnit, string> = {
  char: "char — 문자 수(기본)",
  token: "token — 토큰 수(임베딩 윈도우에 맞춤)",
}

const DISTANCE_METRIC_LABELS: Record<DistanceMetric, string> = {
  cosine: "cosine — 코사인 거리(정규화 임베딩 기본)",
  l2: "l2 — 유클리드 거리",
  inner_product: "inner_product — 내적",
}


export default function CollectionsPage() {
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser

  const [items, setItems] = useState<Collection[]>([])
  const [loading, setLoading] = useState(true)
  // 서버 페이징(catalog datasets 와 동일 방식 — manualPagination + DataTablePagination)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(30)
  const [total, setTotal] = useState(0)
  const [open, setOpen] = useState(false)
  const [showHelp, setShowHelp] = useState(true)
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [submitting, setSubmitting] = useState(false)

  // 색인 설정(생성 후 불변) — 비우면 서버 기본값
  const [provider, setProvider] = useState<EmbeddingProviderKind>("openai_compatible")
  const [model, setModel] = useState("bge-m3")
  const [dim, setDim] = useState("1024")
  const [serverUrl, setServerUrl] = useState("")
  const [metric, setMetric] = useState<DistanceMetric>("cosine")
  const [reranker, setReranker] = useState<RerankProviderKind>("none")
  const [rerankModel, setRerankModel] = useState("")
  const [rerankModels, setRerankModels] = useState<string[]>([])

  // 리랭커 모델 목록 로드 — local 은 FastEmbed 인프로세스 목록, cross_encoder 는 리랭커 서버 목록
  async function onRerankerChange(v: RerankProviderKind) {
    setReranker(v)
    setRerankModel("")
    setRerankModels([])
    if (v === "local") {
      try {
        const { models } = await listLocalRerankModels()
        setRerankModels(models.map((m) => m.model))
      } catch {
        setRerankModels([])
      }
    } else if (v === "cross_encoder") {
      try {
        const { models } = await listRerankModels()
        setRerankModels(models)
      } catch {
        toast.info("리랭커 서버 모델을 불러오지 못했습니다(서버 기본 모델 사용).")
      }
    }
  }
  const [strategy, setStrategy] = useState<ChunkStrategy>("auto")
  const [chunkUnit, setChunkUnit] = useState<ChunkUnit>("char")
  const [parseStrategy, setParseStrategy] = useState<ParseStrategy>("auto")
  const [parseStrategies, setParseStrategies] = useState<ParseStrategyInfo[]>([])
  const [localModels, setLocalModels] = useState<LocalEmbeddingModel[]>([])
  const [openaiModels, setOpenaiModels] = useState<string[]>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [probing, setProbing] = useState(false)
  const [serverTested, setServerTested] = useState(false)
  const [testing, setTesting] = useState(false)

  // 서버 URL 변경 시 — 테스트/불러오기/감지 상태 초기화(다시 테스트해야 함)
  function onServerUrlChange(v: string) {
    setServerUrl(v)
    setServerTested(false)
    setOpenaiModels([])
    setModel("")
    setDim("")
  }

  // 접속 테스트 → 성공 시 모델 불러오기 + 첫 모델 선택 + 차원 감지까지 자동 처리
  async function testServer() {
    if (!serverUrl.trim()) {
      toast.error("서버 URL을 입력하세요.")
      return
    }
    setTesting(true)
    try {
      await checkEmbeddingServer(serverUrl.trim())
      setServerTested(true)
      toast.success("서버 연결 성공 — 모델·차원을 자동 설정합니다.")
      const models = await loadServerModels()
      if (models.length > 0) {
        const first = models[0]!
        setModel(first)
        const res = await probeEmbeddingDimension(first, serverUrl.trim())
        setDim(String(res.dim))
        if (!res.matches) {
          toast.warning(
            `감지된 차원 ${res.dim} 이 저장 차원(${res.column_dim})과 달라 업로드 시 오류가 납니다. 다른 모델을 선택하세요.`
          )
        }
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "서버 연결 실패")
    } finally {
      setTesting(false)
    }
  }

  async function loadServerModels(): Promise<string[]> {
    setLoadingModels(true)
    try {
      const { models } = await listServerEmbeddingModels(serverUrl.trim() || null)
      setOpenaiModels(models)
      if (models.length === 0) toast.info("서버가 모델 목록을 제공하지 않습니다.")
      else toast.success(`${models.length}개 모델을 불러왔습니다.`)
      return models
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "모델 목록 조회 실패")
      return []
    } finally {
      setLoadingModels(false)
    }
  }

  async function detectDim() {
    if (!serverUrl.trim()) {
      toast.error("서버 URL을 먼저 입력하세요.")
      return
    }
    if (!model.trim()) {
      toast.error("먼저 모델명을 입력하세요.")
      return
    }
    setProbing(true)
    try {
      const res = await probeEmbeddingDimension(model.trim(), serverUrl.trim() || null)
      setDim(String(res.dim))
      if (res.matches) {
        toast.success(`차원 감지됨: ${res.dim}`)
      } else {
        toast.warning(`감지된 차원 ${res.dim} 은 저장 차원(${res.column_dim})과 달라 업로드 시 오류가 납니다.`)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "차원 감지 실패")
    } finally {
      setProbing(false)
    }
  }

  // 로컬 프로바이더 선택 시 지원 모델 목록 로딩(차원에 맞는 것만)
  useEffect(() => {
    if (provider !== "local") return
    listLocalEmbeddingModels(Number(dim) || 1024)
      .then((res) => {
        setLocalModels(res.models)
        // 현재 모델이 목록에 없으면 첫 모델로 맞추고 차원도 동기화
        if (res.models.length && !res.models.some((m) => m.model === model)) {
          setModel(res.models[0]!.model)
          setDim(String(res.models[0]!.dim))
        }
      })
      .catch(() => setLocalModels([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider])
  const [chunkSize, setChunkSize] = useState("1000")
  const [chunkOverlap, setChunkOverlap] = useState("150")

  function resetForm() {
    setName("")
    setDescription("")
    setProvider("openai_compatible")
    setModel("bge-m3")
    setDim("1024")
    setServerUrl("")
    setMetric("cosine")
    setReranker("none")
    setRerankModel("")
    setRerankModels([])
    setStrategy("auto")
    setChunkUnit("char")
    setParseStrategy("auto")
    setChunkSize("1000")
    setChunkOverlap("150")
    setServerTested(false)
    setOpenaiModels([])
  }

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listCollections({ page, page_size: pageSize })
      setItems(res.items)
      setTotal(res.total)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "목록 조회 실패")
    } finally {
      setLoading(false)
    }
  }, [page, pageSize])

  // 페이징 테이블 인스턴스(행 렌더링은 아래 표에서 직접, 페이지 이동만 TanStack)
  const table = useReactTable({
    data: items,
    columns: [],
    pageCount: Math.max(1, Math.ceil(total / pageSize)),
    state: { pagination: { pageIndex: page - 1, pageSize } },
    manualPagination: true,
    getCoreRowModel: getCoreRowModel(),
    onPaginationChange: (updater) => {
      const next =
        typeof updater === "function"
          ? updater({ pageIndex: page - 1, pageSize })
          : updater
      if (next.pageSize !== pageSize) {
        setPageSize(next.pageSize)
        setPage(1)
      } else {
        setPage(next.pageIndex + 1)
      }
    },
  })

  useEffect(() => {
    refresh()
  }, [refresh])

  // 생성 다이얼로그 열릴 때 파싱 전략 목록 + 가용성 로드
  useEffect(() => {
    if (!open) return
    listParseStrategies()
      .then((res) => setParseStrategies(res.strategies))
      .catch(() => setParseStrategies([]))
  }, [open])

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    if (!name.trim()) {
      toast.error("이름을 입력하세요.")
      return
    }
    if (provider === "openai_compatible") {
      if (!serverUrl.trim()) {
        toast.error("OpenAI 호환은 서버 URL을 입력해야 합니다.")
        return
      }
      if (!model.trim()) {
        toast.error("'모델 불러오기'로 모델을 선택하세요.")
        return
      }
      if (!dim || Number(dim) <= 0) {
        toast.error("'차원 감지'로 차원을 설정하세요.")
        return
      }
    }
    if (provider === "local" && !model.trim()) {
      toast.error("모델을 선택하세요.")
      return
    }
    if (Number(chunkOverlap) >= Number(chunkSize)) {
      toast.error("청크 오버랩은 청크 크기보다 작아야 합니다.")
      return
    }
    setSubmitting(true)
    try {
      await createCollection({
        name,
        description: description || null,
        embedding_provider: provider,
        // hash 는 모델을 쓰지 않으므로 표시·저장 모두 'hash' 로 고정(오해 방지)
        embedding_model: provider === "hash" ? "hash" : model.trim() || null,
        embedding_dim: dim ? Number(dim) : null,
        // 서버 URL 은 OpenAI 호환에서만 의미 있음(다른 프로바이더는 필드 숨김)
        embedding_server_url: provider === "openai_compatible" ? serverUrl.trim() || null : null,
        distance_metric: metric,
        rerank_provider: reranker,
        rerank_model:
          reranker === "local" || reranker === "cross_encoder" ? rerankModel.trim() || null : null,
        parse_strategy: parseStrategy,
        chunk_strategy: strategy,
        chunk_unit: chunkUnit,
        chunk_size: chunkSize ? Number(chunkSize) : null,
        chunk_overlap: chunkOverlap ? Number(chunkOverlap) : null,
      })
      toast.success("지식베이스를 생성했습니다.")
      setOpen(false)
      resetForm()
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "생성 실패")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <DashboardHeader title="지식베이스" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            RAG 검색 단위인 지식베이스(컬렉션)를 관리합니다.
          </p>
          {canManage && (
            <Button onClick={() => setOpen(true)} size="sm">
              <Plus className="size-4" />
              지식베이스 생성
            </Button>
          )}
        </div>

        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>이름</TableHead>
                <TableHead>임베딩 모델</TableHead>
                <TableHead className="text-center">차원</TableHead>
                <TableHead>청킹</TableHead>
                <TableHead className="text-center">리랭커</TableHead>
                <TableHead className="text-center">문서</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-8 text-center text-muted-foreground">
                    불러오는 중...
                  </TableCell>
                </TableRow>
              ) : items.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-8 text-center text-muted-foreground">
                    <Boxes className="mx-auto mb-2 size-6 opacity-50" />
                    아직 지식베이스가 없습니다.
                  </TableCell>
                </TableRow>
              ) : (
                items.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>
                      <Link
                        href={`/dashboard/collections/${c.collection_id}`}
                        className="font-medium text-black hover:underline"
                      >
                        {c.name}
                      </Link>
                      {c.description && (
                        <p className="max-w-[420px] truncate text-xs text-black">
                          {c.description}
                        </p>
                      )}
                    </TableCell>
                    <TableCell className="text-black">{c.embedding_model}</TableCell>
                    <TableCell className="text-center text-black">
                      {c.embedding_dim}
                    </TableCell>
                    <TableCell className="text-black">
                      {c.chunk_strategy} {c.chunk_size}/{c.chunk_overlap}
                    </TableCell>
                    <TableCell className="text-center text-black">
                      {c.rerank_provider}
                    </TableCell>
                    <TableCell className="text-center text-black">
                      {c.document_count}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>

        {total > 0 && <DataTablePagination table={table} />}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          className={`flex max-h-[92vh] flex-col overflow-y-auto ${showHelp ? "sm:max-w-[1050px]" : "sm:max-w-[560px]"}`}
        >
          <DialogHeader className="shrink-0">
            <div className="flex items-center gap-3">
              <DialogTitle className="text-sm">지식베이스 생성</DialogTitle>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7"
                onClick={() => setShowHelp((v) => !v)}
              >
                <HelpCircle className="size-3.5" />
                {showHelp ? "도움말 숨기기" : "도움말 보기"}
              </Button>
            </div>
          </DialogHeader>
          <TooltipProvider delayDuration={150}>
          <form onSubmit={handleCreate} className="flex flex-col gap-2.5 text-sm [&_input]:text-sm [&_textarea]:text-sm">
              <div className="flex items-stretch gap-4">
                <div className="flex min-w-0 flex-1 flex-col gap-2.5">
            <ConfigTable title="기본 정보">
              <ConfigRow label="이름" hint={HINTS.name}>
                <Input
                  id="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="예: 제품 매뉴얼"
                  required
                  autoFocus
                />
              </ConfigRow>
              <ConfigRow label="설명" hint={HINTS.description} top>
                <Textarea
                  id="description"
                  rows={2}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="이 지식베이스의 용도를 설명하세요"
                  className="min-h-0 resize-none"
                />
              </ConfigRow>
            </ConfigTable>

            <ConfigTable title="임베딩 (벡터 공간 — 생성 후 변경 불가)">
              <ConfigRow label="프로바이더" hint={HINTS.provider}>
                <Select value={provider} onValueChange={(v) => setProvider(v as EmbeddingProviderKind)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="openai_compatible">OpenAI 호환 (외부 서버)</SelectItem>
                    <SelectItem value="local">로컬 (자체 임베딩, 서버 불필요)</SelectItem>
                    <SelectItem value="hash">hash (테스트용)</SelectItem>
                  </SelectContent>
                </Select>
              </ConfigRow>
              {/* 모델 — hash 는 모델을 쓰지 않으므로 숨김 */}
              {provider !== "hash" && (
                <ConfigRow label="모델" hint={HINTS.model}>
                  {provider === "local" ? (
                    <Select
                      value={model}
                      onValueChange={(v) => {
                        setModel(v)
                        const m = localModels.find((x) => x.model === v)
                        if (m) setDim(String(m.dim))
                      }}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder={localModels.length ? "모델 선택" : "사용 가능한 모델 없음"} />
                      </SelectTrigger>
                      <SelectContent>
                        {localModels.map((m) => (
                          <SelectItem key={m.model} value={m.model}>
                            {m.model} ({m.dim}d{m.size_gb ? `, ${m.size_gb}GB` : ""})
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <div className="flex items-center gap-2">
                      <Select
                        value={model}
                        onValueChange={(v) => {
                          setModel(v)
                          setDim("") // 모델이 바뀌면 차원을 다시 감지하도록 비움
                        }}
                        disabled={openaiModels.length === 0}
                      >
                        <SelectTrigger className="flex-1">
                          <SelectValue placeholder={openaiModels.length ? "모델 선택" : "먼저 '모델 불러오기'"} />
                        </SelectTrigger>
                        <SelectContent>
                          {openaiModels.map((m) => (
                            <SelectItem key={m} value={m}>
                              {m}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-8 shrink-0"
                        disabled={loadingModels || !serverTested}
                        title={!serverTested ? "먼저 서버 URL을 '테스트'하세요" : undefined}
                        onClick={loadServerModels}
                      >
                        {loadingModels ? "불러오는 중..." : "모델 불러오기"}
                      </Button>
                    </div>
                  )}
                </ConfigRow>
              )}
              {/* 차원 — 로컬은 모델에 따라 자동 결정되므로 숨김 */}
              {provider !== "local" && (
                <ConfigRow label="차원" hint={HINTS.dim}>
                  <div className="flex items-center gap-2">
                    <Input
                      value={dim}
                      onChange={(e) => setDim(digitsOnly(e.target.value))}
                      inputMode="numeric"
                      placeholder={provider === "openai_compatible" ? "차원 감지" : "1024"}
                      readOnly={provider === "openai_compatible"}
                      className="w-[100px]"
                    />
                    {provider === "openai_compatible" && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-8"
                        disabled={probing || !model.trim() || !serverTested}
                        title={!serverTested ? "먼저 서버 URL을 '테스트'하세요" : undefined}
                        onClick={detectDim}
                      >
                        {probing ? "감지 중..." : "차원 감지"}
                      </Button>
                    )}
                  </div>
                </ConfigRow>
              )}
              {/* 서버 URL — OpenAI 호환에서만 필요. 테스트 성공 후 모델·차원 자동 처리 */}
              {provider === "openai_compatible" && (
                <ConfigRow label="서버 URL" hint={HINTS.serverUrl}>
                  <div className="flex flex-col gap-1.5">
                  <ServiceEndpointPicker
                    kind="embedding"
                    value={serverUrl}
                    className="h-9 w-full text-sm"
                    allowCustom={false}
                    onPick={(svc) => { if (svc) onServerUrlChange(svc.url) }}
                  />
                  <div className="flex items-center gap-2">
                    <Input
                      value={serverUrl}
                      readOnly
                      placeholder="위에서 배포된 임베딩 서비스를 선택하세요"
                      className="flex-1 bg-muted/40"
                    />
                    <Button
                      type="button"
                      variant={serverTested ? "secondary" : "outline"}
                      size="sm"
                      className="h-8 shrink-0"
                      disabled={testing || serverTested || !serverUrl.trim()}
                      onClick={testServer}
                    >
                      {testing ? "테스트 중..." : serverTested ? "연결됨 ✓" : "테스트"}
                    </Button>
                  </div>
                  </div>
                </ConfigRow>
              )}
              <ConfigRow label="거리 메트릭" hint={HINTS.metric}>
                <Select value={metric} onValueChange={(v) => setMetric(v as DistanceMetric)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(Object.keys(DISTANCE_METRIC_LABELS) as DistanceMetric[]).map((m) => (
                      <SelectItem key={m} value={m}>
                        {DISTANCE_METRIC_LABELS[m]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </ConfigRow>
              <ConfigRow label="리랭커" hint={HINTS.reranker}>
                <Select value={reranker} onValueChange={(v) => onRerankerChange(v as RerankProviderKind)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(Object.keys(RERANK_PROVIDER_LABELS) as RerankProviderKind[]).map((p) => (
                      <SelectItem key={p} value={p}>
                        {RERANK_PROVIDER_LABELS[p]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </ConfigRow>
              {/* 리랭커 모델 — local/cross_encoder 일 때, 모델 목록에서 선택(비우면 기본) */}
              {(reranker === "local" || reranker === "cross_encoder") && (
                <ConfigRow label="리랭커 모델" hint={HINTS.rerankModel}>
                  <Select value={rerankModel || "__default__"} onValueChange={(v) => setRerankModel(v === "__default__" ? "" : v)}>
                    <SelectTrigger>
                      <SelectValue placeholder={rerankModels.length ? "모델 선택" : "서버 기본값"} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__default__">서버 기본값</SelectItem>
                      {rerankModels.map((m) => (
                        <SelectItem key={m} value={m}>
                          {m}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </ConfigRow>
              )}
            </ConfigTable>

            <ConfigTable title="파싱 (변경 시 재인덱싱 필요)">
              <ConfigRow label="파싱 전략" hint={HINTS.parse}>
                <Select value={parseStrategy} onValueChange={(v) => setParseStrategy(v as ParseStrategy)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {parseStrategies.map((p) => (
                      <SelectItem key={p.strategy} value={p.strategy}>
                        {p.label}
                        {!p.available ? " (미설치)" : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </ConfigRow>
            </ConfigTable>

            <ConfigTable title="청킹 (변경 시 재인덱싱 필요)">
              <ConfigRow label="전략" hint={HINTS.strategy}>
                <Select value={strategy} onValueChange={(v) => setStrategy(v as ChunkStrategy)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(Object.keys(CHUNK_STRATEGY_LABELS) as ChunkStrategy[]).map((s) => (
                      <SelectItem key={s} value={s}>
                        {CHUNK_STRATEGY_LABELS[s]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </ConfigRow>
              <ConfigRow label="단위" hint={HINTS.chunkUnit}>
                <Select value={chunkUnit} onValueChange={(v) => setChunkUnit(v as ChunkUnit)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(Object.keys(CHUNK_UNIT_LABELS) as ChunkUnit[]).map((u) => (
                      <SelectItem key={u} value={u}>
                        {CHUNK_UNIT_LABELS[u]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </ConfigRow>
              <ConfigRow label={`청크 크기 (${chunkUnit})`} hint={HINTS.chunkSize}>
                <Input value={chunkSize} onChange={(e) => setChunkSize(digitsOnly(e.target.value))} inputMode="numeric" placeholder={chunkUnit === "token" ? "512" : "1000"} className="w-[100px]" />
              </ConfigRow>
              <ConfigRow label={`오버랩 (${chunkUnit})`} hint={HINTS.chunkOverlap}>
                <Input value={chunkOverlap} onChange={(e) => setChunkOverlap(digitsOnly(e.target.value))} inputMode="numeric" placeholder={chunkUnit === "token" ? "64" : "150"} className="w-[100px]" />
              </ConfigRow>
            </ConfigTable>
                </div>
                {showHelp && (
                  <div className="relative hidden w-[470px] shrink-0 md:block">
                    <div className="absolute inset-0 overflow-y-auto rounded-md border bg-muted/20 p-4">
                      <p className="mb-3 text-sm font-semibold">도움말</p>
                      <CollectionConfigHelp />
                    </div>
                  </div>
                )}
              </div>

            <DialogFooter className="shrink-0">
              <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
                취소
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? "생성 중..." : "생성"}
              </Button>
            </DialogFooter>
          </form>
          </TooltipProvider>
        </DialogContent>
      </Dialog>
    </>
  )
}
