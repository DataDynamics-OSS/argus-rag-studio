// 지식베이스 상세 — 메타데이터 + 문서 업로드(인제스천)/목록/재처리/삭제.
// 업로드 시 비동기 잡이 생성되고, 진행률(parse→chunk→embed→index)을 폴링해 표시한다.
"use client"

import {
  Fragment,
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react"
import { useParams, useRouter } from "next/navigation"
import { ArrowLeft, FileSearch, FileText, Layers, RefreshCw, Settings2, SplitSquareHorizontal, Trash2, Upload } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Badge } from "@workspace/ui/components/badge"
import { Input } from "@workspace/ui/components/input"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@workspace/ui/components/tooltip"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@workspace/ui/components/tabs"
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
import { getCoreRowModel, useReactTable } from "@tanstack/react-table"
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard-header"
import { ServiceEndpointPicker } from "@/features/deploy/components/service-endpoint-picker"
import { DataTablePagination } from "@/components/data-table"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { useAuth } from "@/features/auth"
import { fetchUsers } from "@/features/users/api"
import {
  checkEmbeddingServer,
  getCollection,
  listLocalEmbeddingModels,
  listLocalRerankModels,
  listParseStrategies,
  listRerankModels,
  listServerEmbeddingModels,
  probeEmbeddingDimension,
  reindexCollection,
  updateCollection,
} from "@/features/collections/api"
import {
  ConfigRow,
  ConfigTable,
  COLLECTION_HINTS as HINTS,
  digitsOnly,
} from "@/features/collections/components/config-table"
import { CollectionDeleteDialog } from "@/features/collections/components/collection-delete-dialog"
import { IngestionPipelineBuilder } from "@/features/collections/components/ingestion-pipeline-builder"
import { CollectionSearchPanel } from "@/features/search/components/collection-search-panel"
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
import { deleteDocument, listDocuments } from "@/features/documents/api"
import type { RagDocument } from "@/features/documents/data/schema"
import {
  DocumentMetadata,
  metadataPages,
  metadataTitle,
} from "@/features/documents/components/document-metadata"
import { DocumentChunksDialog } from "@/features/documents/components/document-chunks-dialog"
import { DocumentInspectDialog } from "@/features/documents/components/document-inspect-dialog"
import { ChunkCompareDialog } from "@/features/documents/components/chunk-compare-dialog"
import { fileTypeLabel, formatBytes, formatDateTime } from "@/lib/format"
import { pollJob, reindexDocument, uploadDocument } from "@/features/ingestion/api"
import { UrlTabs } from "@/components/url-tabs"

const STATUS_VARIANT: Record<string, "secondary" | "outline" | "default" | "destructive"> = {
  indexed: "secondary",
  registered: "outline",
  processing: "default",
  failed: "destructive",
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

// 메타데이터 표의 값 한글 표시용 간결 라벨(없는 키는 원본 값 그대로).
const PROVIDER_KR: Record<string, string> = {
  openai_compatible: "OpenAI 호환",
  local: "로컬",
  hash: "hash(테스트용)",
}
const DISTANCE_KR: Record<string, string> = {
  cosine: "코사인",
  l2: "유클리드(L2)",
  inner_product: "내적",
}
const RERANK_KR: Record<string, string> = {
  none: "없음",
  llm: "LLM",
  local: "로컬",
  cross_encoder: "Cross-Encoder",
}
const PARSE_KR: Record<string, string> = {
  auto: "자동(파일 유형별)",
  text: "텍스트",
  layout: "레이아웃",
  docai: "문서 AI",
  vlm: "비전 LLM",
  rhwp: "한글(rhwp)",
}
const CHUNK_KR: Record<string, string> = {
  auto: "자동",
  recursive: "재귀 분할",
  sentence: "문장 보존",
  paragraph: "문단 보존",
  section: "섹션 보존",
  fixed: "고정 길이",
  markdown: "마크다운 구조",
  semantic: "의미 기반",
}
const UNIT_KR: Record<string, string> = { char: "문자", token: "토큰" }
const STATUS_KR: Record<string, string> = { active: "활성", archived: "보관됨" }

/** 라벨 맵에서 한글 값을 찾아 반환(없으면 원본 값 그대로). */
function kr(map: Record<string, string>, value: string): string {
  return map[value] ?? value
}

// 메타데이터 표 key 의 설명 — hover 툴팁(catalog 데이터셋 상세 메타데이터와 동일 방식).
const META_KEY_DESC: Record<string, string> = {
  "임베딩 프로바이더": "임베딩 벡터를 생성하는 방식 — OpenAI 호환 외부 서버 / 로컬 ONNX / hash(테스트용)",
  "임베딩 모델": "임베딩에 사용하는 모델 이름",
  "차원": "임베딩 벡터 차원 수(벡터 컬럼 고정값, 변경 불가)",
  "거리 메트릭": "검색 시 유사도를 재는 방법 — 코사인 / 유클리드(L2) / 내적",
  "리랭커": "검색 결과를 다시 정렬하는 방식 — 없음 / LLM / 로컬 / Cross-Encoder",
  "리랭커 모델": "리랭킹에 사용하는 모델(로컬·Cross-Encoder 일 때)",
  "파싱 전략": "문서에서 텍스트를 추출하는 방식(파일 유형·품질에 따라 선택)",
  "청킹 전략": "추출한 본문을 검색 단위(청크)로 나누는 방식",
  "청크 크기": "청크 하나의 최대 크기(단위: 문자 또는 토큰)",
  "오버랩": "인접 청크 간 겹치는 분량(경계 문맥 보존)",
  "임베딩 서버": "임베딩 생성에 사용하는 외부 서버 주소(없으면 기본값)",
  "상태": "지식베이스 상태 — 활성 / 보관됨",
  "문서 수": "이 지식베이스에 등록된 문서 수",
  "생성자": "이 지식베이스를 생성한 사용자",
  "UUID": "지식베이스 고유 식별자(Universally Unique Identifier)",
}

// key 라벨 — 설명이 있으면 점선 밑줄 + hover 툴팁(catalog KeyLabel 과 동일).
function KeyLabel({ label }: { label: string }) {
  const desc = META_KEY_DESC[label]
  if (!desc) return <>{label}</>
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="cursor-help underline decoration-dotted decoration-muted-foreground/50 underline-offset-2">
          {label}
        </span>
      </TooltipTrigger>
      <TooltipContent side="right" className="max-w-sm whitespace-pre-wrap">
        {desc}
      </TooltipContent>
    </Tooltip>
  )
}

export default function CollectionDetailPage() {
  const params = useParams()
  const router = useRouter()
  // 외부 노출 식별자는 컬렉션 UUID. 내부 작업은 조회된 collection.id(정수 PK)를 쓴다.
  const uuid = String(params.id)
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser

  const [collection, setCollection] = useState<Collection | null>(null)
  const [docs, setDocs] = useState<RagDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [progress, setProgress] = useState<string | null>(null)
  // 문서 목록 서버 페이징(지식베이스 목록과 동일 방식)
  const [docPage, setDocPage] = useState(1)
  const [docPageSize, setDocPageSize] = useState(10)
  const [docTotal, setDocTotal] = useState(0)
  const fileRef = useRef<HTMLInputElement>(null)

  // 설정 변경 & 재인덱싱 다이얼로그
  const [creatorName, setCreatorName] = useState<string | null>(null)
  const [docConfirm, setDocConfirm] = useState<{ id: string; kind: "delete" | "reindex" } | null>(
    null,
  )
  const [chunksDoc, setChunksDoc] = useState<RagDocument | null>(null)
  const [previewDoc, setPreviewDoc] = useState<RagDocument | null>(null)
  const [chunkDoc, setChunkDoc] = useState<RagDocument | null>(null)
  const [cfgOpen, setCfgOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [reindexing, setReindexing] = useState(false)
  const [provider, setProvider] = useState<EmbeddingProviderKind>("openai_compatible")
  const [model, setModel] = useState("")
  const [serverUrl, setServerUrl] = useState("")
  const [metric, setMetric] = useState<DistanceMetric>("cosine")
  const [strategy, setStrategy] = useState<ChunkStrategy>("auto")
  const [chunkUnit, setChunkUnit] = useState<ChunkUnit>("char")
  const [parseStrategy, setParseStrategy] = useState<ParseStrategy>("auto")
  const [parseStrategies, setParseStrategies] = useState<ParseStrategyInfo[]>([])
  const [chunkSize, setChunkSize] = useState("1000")
  const [chunkOverlap, setChunkOverlap] = useState("150")
  const [localModels, setLocalModels] = useState<LocalEmbeddingModel[]>([])
  const [openaiModels, setOpenaiModels] = useState<string[]>([])
  const [rerankModels, setRerankModels] = useState<string[]>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [serverTested, setServerTested] = useState(false)
  const [testing, setTesting] = useState(false)

  // 서버 URL 변경 시 — 테스트 상태 초기화(현재 모델은 유지해 드롭다운이 비지 않게)
  function onServerUrlChange(v: string) {
    setServerUrl(v)
    setServerTested(false)
    setOpenaiModels(model ? [model] : [])
  }

  // 접속 테스트 → 성공 시 모델 불러오기 자동 처리(차원은 모델 선택 시 확인)
  async function testServer() {
    if (!serverUrl.trim()) {
      toast.error("서버 URL을 입력하세요.")
      return
    }
    setTesting(true)
    try {
      await checkEmbeddingServer(serverUrl.trim())
      setServerTested(true)
      toast.success("서버 연결 성공 — 모델 목록을 불러옵니다.")
      await loadServerModels()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "서버 연결 실패")
    } finally {
      setTesting(false)
    }
  }

  async function loadServerModels() {
    setLoadingModels(true)
    try {
      const { models } = await listServerEmbeddingModels(serverUrl.trim())
      // 현재 선택된 모델이 목록에 없으면 유지(드롭다운이 비지 않도록)
      const merged = model && !models.includes(model) ? [model, ...models] : models
      setOpenaiModels(merged)
      if (models.length === 0) toast.info("서버가 모델 목록을 제공하지 않습니다.")
      else toast.success(`${models.length}개 모델을 불러왔습니다.`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "모델 목록 조회 실패")
    } finally {
      setLoadingModels(false)
    }
  }

  // 재인덱싱은 차원이 고정이므로, OpenAI 모델 선택 시 차원이 맞는지 미리 확인
  async function pickOpenaiModel(v: string) {
    setModel(v)
    if (!collection) return
    try {
      const res = await probeEmbeddingDimension(v, serverUrl.trim() || null)
      if (res.dim !== collection.embedding_dim) {
        toast.warning(
          `이 모델의 차원(${res.dim})이 컬렉션 차원(${collection.embedding_dim})과 달라 재인덱싱이 실패합니다.`
        )
      }
    } catch {
      // 차원 확인 실패는 무시(재인덱싱 시 검증됨)
    }
  }

  // 로컬 프로바이더 선택 시 — 컬렉션 차원(변경 불가)에 맞는 모델만 로딩
  useEffect(() => {
    if (provider !== "local" || !collection) return
    listLocalEmbeddingModels(collection.embedding_dim)
      .then((res) => {
        setLocalModels(res.models)
        if (res.models.length && !res.models.some((m) => m.model === model)) {
          setModel(res.models[0]!.model)
        }
      })
      .catch(() => setLocalModels([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider])

  function openConfig() {
    if (!collection) return
    setProvider((collection.embedding_provider as EmbeddingProviderKind) ?? "openai_compatible")
    setModel(collection.embedding_model)
    // 현재 OpenAI 모델을 드롭다운에 미리 노출(불러오기 전에도 보이도록)
    setOpenaiModels(
      collection.embedding_provider === "openai_compatible" && collection.embedding_model
        ? [collection.embedding_model]
        : []
    )
    setServerUrl(collection.embedding_server_url ?? "")
    // 기존 OpenAI 컬렉션은 생성 시 검증된 설정이므로 테스트 완료 상태로 연다(모델 불러오기 즉시 가능)
    setServerTested(collection.embedding_provider === "openai_compatible")
    setMetric((collection.distance_metric as DistanceMetric) ?? "cosine")
    setStrategy((collection.chunk_strategy as ChunkStrategy) ?? "auto")
    setChunkUnit((collection.chunk_unit as ChunkUnit) ?? "char")
    setParseStrategy((collection.parse_strategy as ParseStrategy) ?? "auto")
    listParseStrategies()
      .then((res) => setParseStrategies(res.strategies))
      .catch(() => setParseStrategies([]))
    setChunkSize(String(collection.chunk_size))
    setChunkOverlap(String(collection.chunk_overlap))
    setCfgOpen(true)
  }

  async function handleReindexCollection(e: FormEvent) {
    e.preventDefault()
    if (!collection) return
    if (provider === "openai_compatible") {
      if (!serverUrl.trim()) {
        toast.error("OpenAI 호환은 서버 URL을 입력해야 합니다.")
        return
      }
      if (!model.trim()) {
        toast.error("'모델 불러오기'로 모델을 선택하세요.")
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
    setReindexing(true)
    try {
      const isOpenAI = provider === "openai_compatible"
      const result = await reindexCollection(collection.id, {
        embedding_provider: provider,
        embedding_model: provider === "hash" ? "hash" : model.trim() || null,
        // 서버 URL 은 OpenAI 호환에서만 의미 있음 — local/hash 는 비운다
        embedding_server_url: isOpenAI ? serverUrl.trim() || null : null,
        clear_server_url: !isOpenAI || !serverUrl.trim(),
        distance_metric: metric,
        parse_strategy: parseStrategy,
        chunk_strategy: strategy,
        chunk_unit: chunkUnit,
        chunk_size: Number(chunkSize),
        chunk_overlap: Number(chunkOverlap),
      })
      setCfgOpen(false)
      await refresh()
      const total = result.job_ids.length
      if (total === 0) {
        toast.success("설정을 저장했습니다. 재처리할 문서가 없습니다.")
        return
      }
      // 모든 잡 완료까지 폴링하며 진행 표시
      let done = 0
      setProgress(`재인덱싱 0/${total}`)
      await Promise.all(
        result.job_ids.map((jid) =>
          pollJob(jid, () => {}).then((job) => {
            done += 1
            setProgress(`재인덱싱 ${done}/${total}`)
            return job
          })
        )
      )
      toast.success(`재인덱싱 완료 — 문서 ${total}개`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "재인덱싱 실패")
    } finally {
      setProgress(null)
      setReindexing(false)
      await refresh()
    }
  }

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const c = await getCollection(uuid) // UUID 로 컬렉션 해석(내부 PK 포함)
      const d = await listDocuments(c.id, { page: docPage, page_size: docPageSize })
      setCollection(c)
      setDocs(d.items)
      setDocTotal(d.total)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [uuid, docPage, docPageSize])

  // 문서 목록 페이징 테이블 인스턴스(행 렌더링은 표에서 직접, 페이지 이동만 TanStack)
  const docTable = useReactTable({
    data: docs,
    columns: [],
    pageCount: Math.max(1, Math.ceil(docTotal / docPageSize)),
    state: { pagination: { pageIndex: docPage - 1, pageSize: docPageSize } },
    manualPagination: true,
    getCoreRowModel: getCoreRowModel(),
    onPaginationChange: (updater) => {
      const next =
        typeof updater === "function"
          ? updater({ pageIndex: docPage - 1, pageSize: docPageSize })
          : updater
      if (next.pageSize !== docPageSize) {
        setDocPageSize(next.pageSize)
        setDocPage(1)
      } else {
        setDocPage(next.pageIndex + 1)
      }
    },
  })

  useEffect(() => {
    if (uuid && uuid !== "undefined") refresh()
  }, [uuid, refresh])

  // 생성자(username) → 실제 이름(성+이름) 해석. 권한·미존재 시 username 그대로.
  useEffect(() => {
    const username = collection?.created_by
    setCreatorName(null)
    if (!username) return
    let cancelled = false
    fetchUsers({ search: username, pageSize: 0 })
      .then((res) => {
        if (cancelled) return
        const u = res.items.find((x) => x.username === username)
        const name = u ? `${u.lastName ?? ""}${u.firstName ?? ""}`.trim() : ""
        setCreatorName(name || null)
      })
      .catch(() => {
        /* 권한 없음 등 — username 그대로 표시(폴백) */
      })
    return () => {
      cancelled = true
    }
  }, [collection?.created_by])

  // local/cross_encoder 컬렉션이면 리랭커 모델 목록을 미리 로드(드롭다운용)
  useEffect(() => {
    const p = collection?.rerank_provider
    if ((p === "local" || p === "cross_encoder") && rerankModels.length === 0) {
      loadRerankModels(p as RerankProviderKind)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collection?.rerank_provider])

  async function loadRerankModels(provider: RerankProviderKind) {
    try {
      if (provider === "local") {
        const { models } = await listLocalRerankModels()
        setRerankModels(models.map((m) => m.model))
      } else if (provider === "cross_encoder") {
        const { models } = await listRerankModels()
        setRerankModels(models)
      } else {
        setRerankModels([])
      }
    } catch {
      setRerankModels([])
    }
  }

  const rerankUsesModel = (p: string) => p === "local" || p === "cross_encoder"

  async function changeReranker(provider: RerankProviderKind) {
    if (!collection) return
    try {
      // 모델을 쓰는 프로바이더가 아니면 모델을 비운다
      const patch: { rerank_provider: RerankProviderKind; rerank_model?: string | null } = {
        rerank_provider: provider,
      }
      if (!rerankUsesModel(provider)) patch.rerank_model = null
      const updated = await updateCollection(collection.id, patch)
      setCollection(updated)
      if (rerankUsesModel(provider)) loadRerankModels(provider)
      else setRerankModels([])
      toast.success("리랭커 설정을 변경했습니다(재인덱싱 불필요).")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "리랭커 변경 실패")
    }
  }

  async function changeRerankModel(model: string) {
    if (!collection) return
    try {
      const updated = await updateCollection(collection.id, { rerank_model: model || null })
      setCollection(updated)
      toast.success("리랭커 모델을 변경했습니다.")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "리랭커 모델 변경 실패")
    }
  }

  async function handleFile(file: File) {
    if (!collection) return
    setProgress("업로드 중...")
    try {
      const { job_id } = await uploadDocument(collection.id, file)
      await refresh() // 등록 직후 목록에 registered 로 노출
      const final = await pollJob(job_id, (job) => {
        setProgress(
          job.status === "running"
            ? `처리 중 (${job.stage ?? ""} ${job.progress}%)`
            : job.status === "queued"
              ? "대기 중..."
              : null
        )
      })
      if (final.status === "succeeded") {
        toast.success(`인덱싱 완료 — 청크 ${final.chunk_count}개`)
      } else {
        toast.error(`인제스천 실패: ${final.error ?? "알 수 없는 오류"}`)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "업로드 실패")
    } finally {
      setProgress(null)
      await refresh()
    }
  }

  async function handleReindex(docId: string) {
    try {
      const { job_id } = await reindexDocument(docId)
      setProgress("재처리 중...")
      await refresh()
      const final = await pollJob(job_id, (job) =>
        setProgress(job.status === "running" ? `재처리 (${job.stage ?? ""} ${job.progress}%)` : "대기 중...")
      )
      toast[final.status === "succeeded" ? "success" : "error"](
        final.status === "succeeded" ? `재처리 완료 — 청크 ${final.chunk_count}개` : `재처리 실패: ${final.error}`
      )
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "재처리 실패")
    } finally {
      setProgress(null)
      await refresh()
    }
  }

  async function handleDeleteDoc(docId: string) {
    try {
      await deleteDocument(docId)
      toast.success("문서를 삭제했습니다.")
      refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "삭제 실패")
    }
  }

  // 문서 삭제/재처리 확인 다이얼로그에서 "확인" 시 실제 동작 실행
  async function runDocConfirm() {
    if (!docConfirm) return
    const { id: docId, kind } = docConfirm
    setDocConfirm(null)
    if (kind === "delete") await handleDeleteDoc(docId)
    else await handleReindex(docId)
  }

  function handleCollectionDeleted() {
    setDeleteOpen(false)
    toast.success("지식베이스를 삭제했습니다.")
    router.replace("/dashboard/collections")
  }

  return (
    <TooltipProvider delayDuration={150}>
      <DashboardHeader title={collection?.name ?? "지식베이스"} />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <div className="flex items-center justify-between">
          <Button variant="ghost" size="sm" onClick={() => router.push("/dashboard/collections")}>
            <ArrowLeft className="size-4" />
            목록으로
          </Button>
          {canManage && collection && (
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" disabled={!!progress} onClick={openConfig}>
                <Settings2 className="size-4" />
                설정 변경 & 재인덱싱
              </Button>
              <Button variant="destructive" size="sm" onClick={() => setDeleteOpen(true)}>
                <Trash2 className="size-4" />
                지식베이스 삭제
              </Button>
            </div>
          )}
        </div>

        {collection && (
          <div className="space-y-2">
            <h3 className="text-sm font-medium">메타데이터</h3>
            <MetaTable
                items={[
                  {
                    label: "임베딩 프로바이더",
                    node: metaText(kr(PROVIDER_KR, collection.embedding_provider)),
                  },
                  { label: "임베딩 모델", node: metaText(collection.embedding_model) },
                  { label: "차원", node: metaText(String(collection.embedding_dim)) },
                  { label: "거리 메트릭", node: metaText(kr(DISTANCE_KR, collection.distance_metric)) },
                  {
                    label: "리랭커",
                    node: canManage ? (
                      <Select
                        value={collection.rerank_provider}
                        onValueChange={(v) => changeReranker(v as RerankProviderKind)}
                      >
                        <SelectTrigger className="h-8 w-full border-0 bg-transparent px-0 shadow-none focus:ring-0 focus-visible:ring-0">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="none">{RERANK_KR.none}</SelectItem>
                          <SelectItem value="llm">{RERANK_KR.llm}</SelectItem>
                          <SelectItem value="local">{RERANK_KR.local}</SelectItem>
                          <SelectItem value="cross_encoder">{RERANK_KR.cross_encoder}</SelectItem>
                        </SelectContent>
                      </Select>
                    ) : (
                      metaText(kr(RERANK_KR, collection.rerank_provider))
                    ),
                  },
                  // 리랭커 모델 — local/cross_encoder 일 때만(쿼리 시점, 재인덱싱 불필요)
                  ...(collection.rerank_provider === "local" ||
                  collection.rerank_provider === "cross_encoder"
                    ? [
                        {
                          label: "리랭커 모델",
                          node: canManage ? (
                            <Select
                              value={collection.rerank_model || "__default__"}
                              onValueChange={(v) =>
                                changeRerankModel(v === "__default__" ? "" : v)
                              }
                            >
                              <SelectTrigger className="h-8 w-full border-0 bg-transparent px-0 shadow-none focus:ring-0 focus-visible:ring-0">
                                <SelectValue
                                  placeholder={rerankModels.length ? "모델 선택" : "서버 기본값"}
                                />
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
                          ) : (
                            metaText(collection.rerank_model ?? "서버 기본값")
                          ),
                        },
                      ]
                    : []),
                  { label: "파싱 전략", node: metaText(kr(PARSE_KR, collection.parse_strategy)) },
                  { label: "청킹 전략", node: metaText(kr(CHUNK_KR, collection.chunk_strategy)) },
                  {
                    label: "청크 크기",
                    node: metaText(
                      `${collection.chunk_size} ${kr(UNIT_KR, collection.chunk_unit ?? "char")}`,
                    ),
                  },
                  { label: "오버랩", node: metaText(String(collection.chunk_overlap)) },
                  { label: "임베딩 서버", node: metaText(collection.embedding_server_url ?? "기본값") },
                  { label: "상태", node: metaText(kr(STATUS_KR, collection.status)) },
                  { label: "문서 수", node: metaText(String(collection.document_count)) },
                  {
                    label: "생성자",
                    node: metaText(creatorName ?? collection.created_by ?? "-"),
                  },
                  { label: "UUID", node: metaText(collection.collection_id) },
                ]}
            />
          </div>
        )}

        <UrlTabs defaultValue="documents" className="gap-4">
          <TabsList>
            <TabsTrigger value="documents">문서 목록</TabsTrigger>
            <TabsTrigger value="search">검색</TabsTrigger>
            {canManage && <TabsTrigger value="pipeline">파이프라인</TabsTrigger>}
          </TabsList>

          <TabsContent value="documents" className="flex flex-col gap-4">
            {canManage && (
              <div className="flex items-center justify-end gap-3">
                {progress && (
                  <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <RefreshCw className="size-3.5 animate-spin" />
                    {progress}
                  </span>
                )}
                <input
                  ref={fileRef}
                  type="file"
                  className="hidden"
                  accept=".txt,.md,.markdown,.csv,.tsv,.json,.html,.htm,.xml,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.hwp,.hwpx,.log,.rst,.yaml,.yml,.toml,.ini,.cfg,.conf,.tex,.py,.js,.ts,.tsx,.jsx,.java,.go,.rs,.c,.cc,.cpp,.h,.hpp,.cs,.rb,.php,.sh,.bash,.sql,.kt,.swift,.scala"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) handleFile(f)
                    e.target.value = ""
                  }}
                />
                <Button size="sm" disabled={!!progress} onClick={() => fileRef.current?.click()}>
                  <Upload className="size-4" />
                  파일 업로드
                </Button>
              </div>
            )}

            <div className="rounded-lg border">
              <Table>
            <TableHeader>
              <TableRow>
                <TableHead>이름</TableHead>
                <TableHead>출처</TableHead>
                <TableHead>유형</TableHead>
                <TableHead className="text-right">크기</TableHead>
                <TableHead className="text-center">페이지</TableHead>
                <TableHead className="text-center">청크</TableHead>
                <TableHead className="whitespace-nowrap">인덱스 생성일</TableHead>
                <TableHead className="text-center">상태</TableHead>
                <TableHead className="w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={9} className="py-8 text-center text-muted-foreground">
                    불러오는 중...
                  </TableCell>
                </TableRow>
              ) : docs.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} className="py-8 text-center text-muted-foreground">
                    <FileText className="mx-auto mb-2 size-6 opacity-50" />
                    문서를 업로드하면 자동으로 파싱·청킹·임베딩됩니다.
                  </TableCell>
                </TableRow>
              ) : (
                docs.map((d) => (
                  <TableRow key={d.id}>
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate">{d.name}</span>
                        <DocumentMetadata json={d.metadata_json} />
                      </div>
                      {metadataTitle(d.metadata_json) && (
                        <p className="max-w-[360px] truncate text-xs font-normal text-muted-foreground">
                          {metadataTitle(d.metadata_json)}
                        </p>
                      )}
                    </TableCell>
                    <TableCell className="text-black">{d.source_type}</TableCell>
                    <TableCell className="whitespace-nowrap text-black">
                      {fileTypeLabel(d.name)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right tabular-nums text-black">
                      {formatBytes(d.size_bytes)}
                    </TableCell>
                    <TableCell className="text-center tabular-nums text-black">
                      {metadataPages(d.metadata_json) ?? "—"}
                    </TableCell>
                    <TableCell className="text-center text-black">
                      {d.chunk_count}
                    </TableCell>
                    <TableCell className="whitespace-nowrap tabular-nums text-black">
                      {d.indexed_at ? formatDateTime(d.indexed_at) : "—"}
                    </TableCell>
                    <TableCell className="text-center">
                      <Badge variant={STATUS_VARIANT[d.status] ?? "outline"}>{d.status}</Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              onClick={() => setPreviewDoc(d)}
                            >
                              <FileSearch className="size-3.5" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>원본 · 파싱 비교</TooltipContent>
                        </Tooltip>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              onClick={() => setChunkDoc(d)}
                            >
                              <SplitSquareHorizontal className="size-3.5" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>청킹 전 · 후 비교</TooltipContent>
                        </Tooltip>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              onClick={() => setChunksDoc(d)}
                            >
                              <Layers className="size-3.5" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>청크 · 인제스천 현황</TooltipContent>
                        </Tooltip>
                        {canManage && (
                          <>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="icon-xs"
                                  disabled={!!progress}
                                  onClick={() => setDocConfirm({ id: d.document_id, kind: "reindex" })}
                                >
                                  <RefreshCw className="size-3.5" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>재처리</TooltipContent>
                            </Tooltip>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="icon-xs"
                                  onClick={() => setDocConfirm({ id: d.document_id, kind: "delete" })}
                                >
                                  <Trash2 className="size-3.5" />
                                </Button>
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

            {docTotal > 0 && <DataTablePagination table={docTable} />}
          </TabsContent>

          <TabsContent value="search">
            {collection && (
              <CollectionSearchPanel
                collectionId={collection.id}
                distanceMetric={collection.distance_metric}
                rerankProvider={collection.rerank_provider}
              />
            )}
          </TabsContent>

          {canManage && (
            <TabsContent value="pipeline">
              {collection && (
                <IngestionPipelineBuilder
                  collection={collection}
                  documents={docs}
                  onReindexed={refresh}
                />
              )}
            </TabsContent>
          )}
        </UrlTabs>
      </div>

      <Dialog open={cfgOpen} onOpenChange={(o) => !reindexing && setCfgOpen(o)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[35.2rem]">
          <DialogHeader>
            <DialogTitle>색인 설정 변경 & 재인덱싱</DialogTitle>
            <DialogDescription>
              임베딩·청킹 설정을 바꾸면 이 지식베이스의 모든 문서를 새 설정으로 다시 처리합니다.
              차원({collection?.embedding_dim})은 벡터 컬럼 고정이라 변경할 수 없습니다.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleReindexCollection} className="flex flex-col gap-4">
            <ConfigTable title="임베딩">
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
                    <Select value={model} onValueChange={setModel}>
                      <SelectTrigger>
                        <SelectValue placeholder={localModels.length ? "모델 선택" : `${collection?.embedding_dim}d 모델 없음`} />
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
                      <Select value={model} onValueChange={pickOpenaiModel} disabled={openaiModels.length === 0}>
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
              {/* 서버 URL — OpenAI 호환에서만 필요. 테스트 후 모델 불러오기 */}
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
            </ConfigTable>

            <ConfigTable title="파싱">
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

            <ConfigTable title="청킹">
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
                <Input value={chunkSize} onChange={(e) => setChunkSize(digitsOnly(e.target.value))} inputMode="numeric" />
              </ConfigRow>
              <ConfigRow label={`오버랩 (${chunkUnit})`} hint={HINTS.chunkOverlap}>
                <Input value={chunkOverlap} onChange={(e) => setChunkOverlap(digitsOnly(e.target.value))} inputMode="numeric" />
              </ConfigRow>
            </ConfigTable>

            <p className="text-xs text-muted-foreground">
              문서 {docTotal}개가 재처리됩니다. 처리 중에는 기존 검색 결과가 일시적으로 달라질 수 있습니다.
            </p>

            <DialogFooter>
              <Button type="button" variant="ghost" disabled={reindexing} onClick={() => setCfgOpen(false)}>
                취소
              </Button>
              <Button type="submit" disabled={reindexing}>
                {reindexing ? "재인덱싱 중..." : "저장 & 재인덱싱"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {collection && (
        <CollectionDeleteDialog
          open={deleteOpen}
          onOpenChange={setDeleteOpen}
          collectionId={collection.id}
          collectionName={collection.name}
          onDeleted={handleCollectionDeleted}
        />
      )}

      <ConfirmDialog
        open={docConfirm !== null}
        onOpenChange={(o) => !o && setDocConfirm(null)}
        handleConfirm={runDocConfirm}
        title={docConfirm?.kind === "delete" ? "문서 삭제" : "문서 재처리"}
        desc={
          docConfirm?.kind === "delete"
            ? "이 문서를 삭제할까요? 생성된 청크도 함께 삭제됩니다. 이 작업은 되돌릴 수 없습니다."
            : "이 문서를 다시 처리(파싱·청킹·임베딩·색인)할까요? 기존 청크는 삭제 후 재생성됩니다."
        }
        confirmText={docConfirm?.kind === "delete" ? "삭제" : "재처리"}
        destructive={docConfirm?.kind === "delete"}
      />

      <DocumentChunksDialog
        documentId={chunksDoc?.document_id ?? null}
        documentName={chunksDoc?.name ?? ""}
        indexedAt={chunksDoc?.indexed_at ?? null}
        open={chunksDoc !== null}
        onOpenChange={(o) => !o && setChunksDoc(null)}
      />

      <DocumentInspectDialog
        documentId={previewDoc?.document_id ?? null}
        documentName={previewDoc?.name ?? ""}
        open={previewDoc !== null}
        onOpenChange={(o) => !o && setPreviewDoc(null)}
      />

      <ChunkCompareDialog
        documentId={chunkDoc?.document_id ?? null}
        documentName={chunkDoc?.name ?? ""}
        open={chunkDoc !== null}
        onOpenChange={(o) => !o && setChunkDoc(null)}
      />
    </TooltipProvider>
  )
}

/** 메타데이터 값 텍스트 — 셀 안에서 한 줄로 잘라 표시(전체는 title 툴팁). */
function metaText(value: string): ReactNode {
  return (
    <span className="block truncate font-medium" title={value}>
      {value}
    </span>
  )
}

/**
 * 메타데이터 표 — catalog 데이터셋 상세의 메타데이터 표시와 동일한 구조.
 * 한 행에 key/value 3쌍(6컬럼), key 셀은 배경색(bg-muted/60) 테두리 셀.
 */
function MetaTable({ items }: { items: { label: string; node: ReactNode }[] }) {
  const rows: { label: string; node: ReactNode }[][] = []
  for (let i = 0; i < items.length; i += 3) rows.push(items.slice(i, i + 3))
  return (
    <table className="w-full table-fixed border-collapse text-sm text-black">
      <colgroup>
        <col className="w-[138px]" />
        <col />
        <col className="w-[138px]" />
        <col />
        <col className="w-[138px]" />
        <col />
      </colgroup>
      <tbody>
        {rows.map((group, ri) => (
          <tr key={ri}>
            {group.map((it) => (
              <Fragment key={it.label}>
                <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">
                  <KeyLabel label={it.label} />
                </th>
                <td className="border px-3 py-2 align-middle text-black">{it.node}</td>
              </Fragment>
            ))}
            {Array.from({ length: 3 - group.length }).map((_, k) => (
              <Fragment key={`pad-${k}`}>
                <th className="border bg-muted/60" />
                <td className="border" />
              </Fragment>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
