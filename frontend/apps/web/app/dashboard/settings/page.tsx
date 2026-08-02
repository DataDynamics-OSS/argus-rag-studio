// 설정 — RAG Studio 운영 설정. 유형별 탭(임베딩/생성LLM/검색·리랭킹/벡터DB/인제스천/CORS/시스템).
// 각 탭은 1설정=1행 테이블 + 옵션별 설명. 탭 상단에 용도 설명 + 우측 정렬 저장 버튼.
// admin 전용. 편집값은 PUT /settings 로 저장되며 런타임에 즉시 적용된다(시스템 탭은 읽기 전용).
"use client"

import { UrlTabs } from "@/components/url-tabs"
import { useCallback, useEffect, useState } from "react"
import { getHwpViewerMode, setHwpViewerMode, type HwpViewerMode } from "@/lib/hwp-pref"
import { Database, Eye, EyeOff, FolderPlus, Plug, RefreshCw, Save } from "lucide-react"
import { toast } from "sonner"

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
import { DashboardHeader } from "@/components/dashboard-header"
import { ServiceEndpointPicker } from "@/features/deploy/components/service-endpoint-picker"
import {
  checkEmbeddingServer,
  checkRerankServer,
  probeEmbeddingDimension,
} from "@/features/collections/api"
import {
  getSettings,
  initializeObjectStorage,
  reindexVectorStore,
  testAuth,
  testDatabricks,
  testImageClassification,
  testObjectStorage,
  updateSettings,
  type EffectiveSettings,
} from "@/features/settings/api"

const VECTOR_STORES = [
  { value: "pgvector", label: "pgvector (기본 · PostgreSQL 내장)" },
  { value: "qdrant", label: "Qdrant" },
  { value: "weaviate", label: "Weaviate" },
  { value: "milvus", label: "Milvus / Zilliz" },
  { value: "databricks", label: "Databricks (Mosaic AI Vector Search)" },
] as const

// Databricks 기반 환경 권장 기본값 — 백엔드 DatabricksProfile 과 일치(model/dim/metric, 벡터스토어/스토리지).
const DBX = {
  embeddingModel: "Qwen/Qwen3-Embedding-0.6B",
  embeddingDim: "1024",
  embeddingMetric: "cosine",
  vectorStore: "databricks",
  storageBackend: "uc_volumes",
} as const

// 워크스페이스 Host → OpenAI 호환 serving-endpoints 베이스 URL. host 가 비면 빈 문자열(유도 보류).
const dbxServingUrl = (host: string) =>
  host.trim() ? `${host.trim().replace(/\/+$/, "")}/serving-endpoints` : ""

export default function SettingsPage() {
  const [data, setData] = useState<EffectiveSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  // 기반 환경(Platform Profile)
  const [platformBase, setPlatformBase] = useState("standard")
  const [databricksHost, setDatabricksHost] = useState("")
  const [databricksToken, setDatabricksToken] = useState("")
  const [dbxTesting, setDbxTesting] = useState(false)
  // databricks 전환 시 자동 변경한 필드의 '변경 전 값'(되돌리기·이전값 표시용). key = "embedding.model" 등.
  const [prevValues, setPrevValues] = useState<Record<string, string>>({})
  // 임베딩
  const [provider, setProvider] = useState("openai_compatible")
  const [serverUrl, setServerUrl] = useState("")
  const [model, setModel] = useState("")
  const [embQueryInstruction, setEmbQueryInstruction] = useState("")
  const [batchSize, setBatchSize] = useState("32")
  const [embeddingApiKey, setEmbeddingApiKey] = useState("")
  // 생성 LLM
  const [llmProvider, setLlmProvider] = useState("openai_compatible")
  const [llmServerUrl, setLlmServerUrl] = useState("")
  const [llmModel, setLlmModel] = useState("")
  const [llmMaxTokens, setLlmMaxTokens] = useState("2048")
  const [llmTemperature, setLlmTemperature] = useState("0")
  const [llmApiKey, setLlmApiKey] = useState("")
  // 검색·리랭킹
  const [rerankProvider, setRerankProvider] = useState("none")
  const [rerankServerUrl, setRerankServerUrl] = useState("")
  const [topK, setTopK] = useState("5")
  const [vectorK, setVectorK] = useState("20")
  const [lexicalK, setLexicalK] = useState("20")
  const [rrfK, setRrfK] = useState("60")
  // 벡터 DB
  const [vectorStore, setVectorStore] = useState("pgvector")
  const [vectorStoreUrl, setVectorStoreUrl] = useState("")
  const [vectorStoreApiKey, setVectorStoreApiKey] = useState("")
  const [vectorStorePrefix, setVectorStorePrefix] = useState("argus")
  // Databricks Mosaic AI Vector Search (vectorStore === "databricks" 일 때)
  const [dbxVsEndpoint, setDbxVsEndpoint] = useState("")
  const [dbxVsCatalog, setDbxVsCatalog] = useState("main")
  const [dbxVsSchema, setDbxVsSchema] = useState("argus")
  const [reindexing, setReindexing] = useState(false)
  // 인제스천
  const [chunkSize, setChunkSize] = useState("1000")
  const [chunkOverlap, setChunkOverlap] = useState("150")
  // CORS
  const [corsOrigins, setCorsOrigins] = useState("")
  // 오브젝트 스토리지
  const [storageBackend, setStorageBackend] = useState("s3")
  const [dbxVolCatalog, setDbxVolCatalog] = useState("main")
  const [dbxVolSchema, setDbxVolSchema] = useState("argus")
  const [dbxVolVolume, setDbxVolVolume] = useState("documents")
  const [osEndpoint, setOsEndpoint] = useState("")
  const [osAccessKey, setOsAccessKey] = useState("")
  const [osSecretKey, setOsSecretKey] = useState("")
  const [osRegion, setOsRegion] = useState("us-east-1")
  const [osUseSsl, setOsUseSsl] = useState("false")
  const [osBucket, setOsBucket] = useState("")
  const [osTesting, setOsTesting] = useState(false)
  const [osIniting, setOsIniting] = useState(false)
  const [embTesting, setEmbTesting] = useState(false)
  const [rerankTesting, setRerankTesting] = useState(false)
  // 인증
  const [authType, setAuthType] = useState("local")
  const [kcServerUrl, setKcServerUrl] = useState("")
  const [kcRealm, setKcRealm] = useState("")
  const [kcClientId, setKcClientId] = useState("")
  const [kcClientSecret, setKcClientSecret] = useState("")
  const [kcAdminRole, setKcAdminRole] = useState("")
  const [kcSuperuserRole, setKcSuperuserRole] = useState("")
  const [kcUserRole, setKcUserRole] = useState("")
  const [authTesting, setAuthTesting] = useState(false)
  // 이미지 변환 (HWP/HWPX 엔진)
  const [hwpEngine, setHwpEngine] = useState("rhwp")
  // 임베딩(고급)
  const [embTimeout, setEmbTimeout] = useState("60")
  const [embAuthHeader, setEmbAuthHeader] = useState("Authorization")
  const [embAuthScheme, setEmbAuthScheme] = useState("Bearer")
  const [embDefaultModel, setEmbDefaultModel] = useState("bge-m3")
  const [embDefaultDim, setEmbDefaultDim] = useState("1024")
  const [embDefaultMetric, setEmbDefaultMetric] = useState("cosine")
  // LLM(고급)
  const [llmTimeout, setLlmTimeout] = useState("120")
  const [llmAuthHeader, setLlmAuthHeader] = useState("Authorization")
  const [llmAuthScheme, setLlmAuthScheme] = useState("Bearer")
  // 리랭킹(추가)
  const [rerankApiKey, setRerankApiKey] = useState("")
  const [rerankTopN, setRerankTopN] = useState("5")
  const [rerankAuthHeader, setRerankAuthHeader] = useState("Authorization")
  const [rerankAuthScheme, setRerankAuthScheme] = useState("Bearer")
  // 인제스천(추가)
  const [workerInterval, setWorkerInterval] = useState("2.0")
  const [serviceToken, setServiceToken] = useState("")
  const [maxKssChars, setMaxKssChars] = useState("5000")
  const [minChunkRatio, setMinChunkRatio] = useState("0.1")
  const [semanticPct, setSemanticPct] = useState("90")
  // 검출(자동 bbox)
  const [detEnabled, setDetEnabled] = useState("false")
  const [detServerUrl, setDetServerUrl] = useState("")
  const [detApiKey, setDetApiKey] = useState("")
  const [detLang, setDetLang] = useState("korean")
  const [detMinScore, setDetMinScore] = useState("0.5")
  const [detTimeout, setDetTimeout] = useState("60")
  const [detAuthHeader, setDetAuthHeader] = useState("Authorization")
  const [detAuthScheme, setDetAuthScheme] = useState("Bearer")
  // 이미지 추출 및 분류(VLM)
  const [icEnabled, setIcEnabled] = useState("false")
  const [icServerUrl, setIcServerUrl] = useState("")
  const [icModel, setIcModel] = useState("")
  const [icApiKey, setIcApiKey] = useState("")
  const [icCategories, setIcCategories] = useState("")
  const [icMinPixels, setIcMinPixels] = useState("64")
  const [icMaxImages, setIcMaxImages] = useState("50")
  const [icTimeout, setIcTimeout] = useState("60")
  const [icSmallImageMinKb, setIcSmallImageMinKb] = useState("10")
  const [icAuthHeader, setIcAuthHeader] = useState("Authorization")
  const [icAuthScheme, setIcAuthScheme] = useState("Bearer")
  const [icTesting, setIcTesting] = useState(false)
  // 이미지 변환(추가)
  const [convDpi, setConvDpi] = useState("150")
  const [convThumbMax, setConvThumbMax] = useState("320")
  const [convHwpScale, setConvHwpScale] = useState("2.0")
  const [convOfficeConc, setConvOfficeConc] = useState("2")
  const [convOfficeTimeout, setConvOfficeTimeout] = useState("90")
  // 스토리지(추가)
  const [annotationBucket, setAnnotationBucket] = useState("annotation-images")
  const [classificationBucket, setClassificationBucket] = useState("classification-images")
  const [modelsBucket, setModelsBucket] = useState("argus-models")
  const [presignExpiry, setPresignExpiry] = useState("3600")
  // 인증(추가)
  const [jwtExpireMinutes, setJwtExpireMinutes] = useState("480")
  // 미리보기 / 관측성
  const [previewMaxRows, setPreviewMaxRows] = useState("1000")
  const [answerLimit, setAnswerLimit] = useState("2000")

  // 클라이언트 표시 취향(localStorage) — HWP 뷰어 방식. 백엔드 저장과 무관(즉시 적용).
  const [hwpMode, setHwpMode] = useState<HwpViewerMode>("image")
  useEffect(() => {
    setHwpMode(getHwpViewerMode())
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const d = await getSettings()
      setData(d)
      setPlatformBase(d.platform.base)
      setDatabricksHost(d.platform.databricks_host)
      setDatabricksToken(d.platform.databricks_token)
      setProvider(d.embedding.provider)
      setServerUrl(d.embedding.server_url)
      setModel(d.embedding.model)
      setEmbQueryInstruction(d.embedding.query_instruction)
      setBatchSize(String(d.embedding.batch_size))
      setEmbeddingApiKey(d.embedding.api_key)
      setLlmProvider(d.llm.provider)
      setLlmServerUrl(d.llm.server_url)
      setLlmModel(d.llm.model)
      setLlmMaxTokens(String(d.llm.max_tokens))
      setLlmTemperature(String(d.llm.temperature))
      setLlmApiKey(d.llm.api_key)
      setRerankProvider(d.rerank.provider)
      setRerankServerUrl(d.rerank.server_url)
      setTopK(String(d.retrieval.top_k))
      setVectorK(String(d.retrieval.vector_k))
      setLexicalK(String(d.retrieval.lexical_k))
      setRrfK(String(d.retrieval.rrf_k))
      setVectorStore(d.retrieval.vector_store)
      setVectorStoreUrl(d.retrieval.vector_store_url)
      setVectorStoreApiKey(d.retrieval.vector_store_api_key)
      setVectorStorePrefix(d.retrieval.vector_store_collection_prefix)
      setDbxVsEndpoint(d.retrieval.vector_store_databricks_endpoint)
      setDbxVsCatalog(d.retrieval.vector_store_databricks_catalog)
      setDbxVsSchema(d.retrieval.vector_store_databricks_schema)
      setChunkSize(String(d.ingestion.chunk_size))
      setChunkOverlap(String(d.ingestion.chunk_overlap))
      setCorsOrigins(d.cors.origins.join(", "))
      setStorageBackend(d.storage.backend)
      setDbxVolCatalog(d.storage.databricks_catalog)
      setDbxVolSchema(d.storage.databricks_schema)
      setDbxVolVolume(d.storage.databricks_volume)
      setOsEndpoint(d.storage.endpoint)
      setOsAccessKey(d.storage.access_key)
      setOsSecretKey(d.storage.secret_key)
      setOsRegion(d.storage.region)
      setOsUseSsl(String(d.storage.use_ssl))
      setOsBucket(d.storage.bucket)
      setAuthType(d.auth.type)
      setKcServerUrl(d.auth.keycloak_server_url)
      setKcRealm(d.auth.keycloak_realm)
      setKcClientId(d.auth.keycloak_client_id)
      setKcClientSecret(d.auth.keycloak_client_secret)
      setKcAdminRole(d.auth.keycloak_admin_role)
      setKcSuperuserRole(d.auth.keycloak_superuser_role)
      setKcUserRole(d.auth.keycloak_user_role)
      setHwpEngine(d.image_conversion.hwp_engine)
      setEmbTimeout(String(d.embedding.timeout))
      setEmbAuthHeader(d.embedding.auth_header)
      setEmbAuthScheme(d.embedding.auth_scheme)
      setEmbDefaultModel(d.embedding.default_model)
      setEmbDefaultDim(String(d.embedding.default_dim))
      setEmbDefaultMetric(d.embedding.default_metric)
      setLlmTimeout(String(d.llm.timeout))
      setLlmAuthHeader(d.llm.auth_header)
      setLlmAuthScheme(d.llm.auth_scheme)
      setRerankApiKey(d.rerank.api_key)
      setRerankTopN(String(d.rerank.top_n))
      setRerankAuthHeader(d.rerank.auth_header)
      setRerankAuthScheme(d.rerank.auth_scheme)
      setWorkerInterval(String(d.ingestion.worker_interval))
      setServiceToken(d.ingestion.service_token)
      setMaxKssChars(String(d.ingestion.max_kss_chars))
      setMinChunkRatio(String(d.ingestion.min_chunk_ratio))
      setSemanticPct(String(d.ingestion.semantic_percentile))
      setDetEnabled(String(d.detection.enabled))
      setDetServerUrl(d.detection.server_url)
      setDetApiKey(d.detection.api_key)
      setDetLang(d.detection.lang)
      setDetMinScore(String(d.detection.min_score))
      setDetTimeout(String(d.detection.timeout))
      setDetAuthHeader(d.detection.auth_header)
      setDetAuthScheme(d.detection.auth_scheme)
      setIcEnabled(String(d.image_classification.enabled))
      setIcServerUrl(d.image_classification.server_url)
      setIcModel(d.image_classification.model)
      setIcApiKey(d.image_classification.api_key)
      setIcCategories(d.image_classification.categories)
      setIcMinPixels(String(d.image_classification.min_pixels))
      setIcMaxImages(String(d.image_classification.max_images))
      setIcTimeout(String(d.image_classification.timeout))
      setIcSmallImageMinKb(String(d.image_classification.small_image_min_kb))
      setIcAuthHeader(d.image_classification.auth_header)
      setIcAuthScheme(d.image_classification.auth_scheme)
      setConvDpi(String(d.image_conversion.dpi))
      setConvThumbMax(String(d.image_conversion.thumbnail_max))
      setConvHwpScale(String(d.image_conversion.hwp_scale))
      setConvOfficeConc(String(d.image_conversion.office_concurrency))
      setConvOfficeTimeout(String(d.image_conversion.office_timeout))
      setAnnotationBucket(d.storage.annotation_bucket)
      setClassificationBucket(d.storage.classification_bucket)
      setModelsBucket(d.storage.models_bucket ?? "argus-models")
      setPresignExpiry(String(d.storage.presign_expiry))
      setJwtExpireMinutes(String(d.auth.local_jwt_expire_minutes))
      setPreviewMaxRows(String(d.preview.max_rows))
      setAnswerLimit(String(d.observability.answer_limit))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "설정 조회 실패")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function handleSave() {
    setSaving(true)
    try {
      const payload: Record<string, unknown> = {
        "platform.base": platformBase,
        "databricks.host": databricksHost,
        "databricks.token": databricksToken,
        "embedding.provider": provider,
        "embedding.server_url": serverUrl,
        "embedding.model": model,
        "embedding.query_instruction": embQueryInstruction,
        "embedding.batch_size": Number(batchSize),
        "embedding.api_key": embeddingApiKey,
        "llm.provider": llmProvider,
        "llm.server_url": llmServerUrl,
        "llm.model": llmModel,
        "llm.max_tokens": Number(llmMaxTokens),
        "llm.temperature": Number(llmTemperature),
        "llm.api_key": llmApiKey,
        "rerank.provider": rerankProvider,
        "rerank.server_url": rerankServerUrl,
        "retrieval.top_k": Number(topK),
        "retrieval.vector_k": Number(vectorK),
        "retrieval.lexical_k": Number(lexicalK),
        "retrieval.rrf_k": Number(rrfK),
        "retrieval.vector_store": vectorStore,
        "retrieval.vector_store_url": vectorStoreUrl,
        "retrieval.vector_store_api_key": vectorStoreApiKey,
        "retrieval.vector_store_collection_prefix": vectorStorePrefix,
        "retrieval.vector_store_databricks_endpoint": dbxVsEndpoint,
        "retrieval.vector_store_databricks_catalog": dbxVsCatalog,
        "retrieval.vector_store_databricks_schema": dbxVsSchema,
        "ingestion.chunk_size": Number(chunkSize),
        "ingestion.chunk_overlap": Number(chunkOverlap),
        "cors.origins": corsOrigins.split(",").map((s) => s.trim()).filter(Boolean),
        "object_storage.backend": storageBackend,
        "object_storage.databricks_catalog": dbxVolCatalog,
        "object_storage.databricks_schema": dbxVolSchema,
        "object_storage.databricks_volume": dbxVolVolume,
        "object_storage.endpoint": osEndpoint,
        "object_storage.access_key": osAccessKey,
        "object_storage.secret_key": osSecretKey,
        "object_storage.region": osRegion,
        "object_storage.use_ssl": osUseSsl === "true",
        "object_storage.bucket": osBucket,
        "auth.type": authType,
        "auth.keycloak_server_url": kcServerUrl,
        "auth.keycloak_realm": kcRealm,
        "auth.keycloak_client_id": kcClientId,
        "auth.keycloak_client_secret": kcClientSecret,
        "auth.keycloak_admin_role": kcAdminRole,
        "auth.keycloak_superuser_role": kcSuperuserRole,
        "auth.keycloak_user_role": kcUserRole,
        "auth.local_jwt_expire_minutes": Number(jwtExpireMinutes),
        "image_conversion.hwp_engine": hwpEngine,
        "image_conversion.dpi": Number(convDpi),
        "image_conversion.thumbnail_max": Number(convThumbMax),
        "image_conversion.hwp_scale": Number(convHwpScale),
        "image_conversion.office_concurrency": Number(convOfficeConc),
        "image_conversion.office_timeout": Number(convOfficeTimeout),
        "embedding.timeout": Number(embTimeout),
        "embedding.auth_header": embAuthHeader,
        "embedding.auth_scheme": embAuthScheme,
        "embedding.default_model": embDefaultModel,
        "embedding.default_dim": Number(embDefaultDim),
        "embedding.default_metric": embDefaultMetric,
        "llm.timeout": Number(llmTimeout),
        "llm.auth_header": llmAuthHeader,
        "llm.auth_scheme": llmAuthScheme,
        "rerank.api_key": rerankApiKey,
        "rerank.top_n": Number(rerankTopN),
        "rerank.auth_header": rerankAuthHeader,
        "rerank.auth_scheme": rerankAuthScheme,
        "ingestion.worker_interval": Number(workerInterval),
        "ingestion.service_token": serviceToken,
        "ingestion.max_kss_chars": Number(maxKssChars),
        "ingestion.min_chunk_ratio": Number(minChunkRatio),
        "ingestion.semantic_percentile": Number(semanticPct),
        "detection.enabled": detEnabled === "true",
        "detection.server_url": detServerUrl,
        "detection.api_key": detApiKey,
        "detection.lang": detLang,
        "detection.min_score": Number(detMinScore),
        "detection.timeout": Number(detTimeout),
        "detection.auth_header": detAuthHeader,
        "detection.auth_scheme": detAuthScheme,
        "image_classification.enabled": icEnabled === "true",
        "image_classification.server_url": icServerUrl,
        "image_classification.model": icModel,
        "image_classification.api_key": icApiKey,
        "image_classification.categories": icCategories,
        "image_classification.min_pixels": Number(icMinPixels),
        "image_classification.max_images": Number(icMaxImages),
        "image_classification.timeout": Number(icTimeout),
        "image_classification.small_image_min_kb": Number(icSmallImageMinKb),
        "image_classification.auth_header": icAuthHeader,
        "image_classification.auth_scheme": icAuthScheme,
        "object_storage.annotation_bucket": annotationBucket,
        "object_storage.classification_bucket": classificationBucket,
        "object_storage.models_bucket": modelsBucket,
        "object_storage.presign_expiry": Number(presignExpiry),
        "preview.max_rows": Number(previewMaxRows),
        "observability.answer_limit": Number(answerLimit),
      }
      await updateSettings(payload)
      toast.success("설정을 저장했습니다.")
      setPrevValues({}) // 저장 완료 → '이전값'(되돌리기) 기록은 의미 없으므로 비움
      load()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "저장 실패")
    } finally {
      setSaving(false)
    }
  }

  async function handleReindex() {
    setReindexing(true)
    try {
      const r = await reindexVectorStore()
      toast.success(`벡터 재색인 완료 — ${r.provider}: 컬렉션 ${r.collections}개 · 벡터 ${r.vectors.toLocaleString()}개`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "벡터 재색인 실패")
    } finally {
      setReindexing(false)
    }
  }

  // 현재 폼 값으로 스토리지 요청 바디 구성(저장 전 검증).
  function osBody(): Record<string, unknown> {
    return {
      endpoint: osEndpoint, access_key: osAccessKey, secret_key: osSecretKey,
      region: osRegion, use_ssl: osUseSsl === "true", bucket: osBucket,
    }
  }

  async function handleTestDatabricks() {
    setDbxTesting(true)
    try {
      const r = await testDatabricks({ host: databricksHost, token: databricksToken })
      r.ok ? toast.success(r.message) : toast.error(r.message)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "연결 테스트 실패")
    } finally {
      setDbxTesting(false)
    }
  }

  async function handleTestStorage() {
    setOsTesting(true)
    try {
      const r = await testObjectStorage(osBody())
      r.ok ? toast.success(r.message) : toast.error(r.message)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "연결 테스트 실패")
    } finally {
      setOsTesting(false)
    }
  }

  // 임베딩 서버 연결 테스트(현재 입력 URL) — health + 모델 지정 시 차원 감지까지.
  async function handleTestEmbedding() {
    if (!serverUrl.trim()) {
      toast.error("서버 URL을 입력하세요.")
      return
    }
    setEmbTesting(true)
    try {
      await checkEmbeddingServer(serverUrl)
      let msg = "임베딩 서버 연결 OK"
      if (model.trim()) {
        try {
          const p = await probeEmbeddingDimension(model, serverUrl)
          msg += ` · 차원 ${p.dim}${p.matches ? " (기본 차원과 일치)" : ` (기본 ${p.column_dim}과 불일치)`}`
        } catch {
          /* health 는 성공, 차원 감지만 실패 — 연결 OK 로 처리 */
        }
      }
      toast.success(msg)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "연결 테스트 실패")
    } finally {
      setEmbTesting(false)
    }
  }

  // 리랭커 서버 연결 테스트(현재 입력 URL) — /v1/models 응답 확인.
  async function handleTestRerank() {
    if (!rerankServerUrl.trim()) {
      toast.error("리랭커 서버 URL을 입력하세요.")
      return
    }
    setRerankTesting(true)
    try {
      const r = await checkRerankServer(rerankServerUrl)
      toast.success(`리랭커 서버 연결 OK${r.models?.length ? ` · 모델 ${r.models.length}개` : ""}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "연결 테스트 실패")
    } finally {
      setRerankTesting(false)
    }
  }

  async function handleInitStorage() {
    setOsIniting(true)
    try {
      // 설정의 3개 버킷(문서·이미지 라벨링·이미지 추출 및 분류)을 순서대로 없으면 생성.
      const r = await initializeObjectStorage({
        ...osBody(),
        buckets: [osBucket, annotationBucket, classificationBucket, modelsBucket],
      })
      r.ok ? toast.success(r.message) : toast.error(r.message)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "버킷 초기화 실패")
    } finally {
      setOsIniting(false)
    }
  }

  async function handleTestAuth() {
    setAuthTesting(true)
    try {
      const r = await testAuth({ type: authType, keycloak_server_url: kcServerUrl, keycloak_realm: kcRealm })
      r.ok ? toast.success(r.message) : toast.error(r.message)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "연결 테스트 실패")
    } finally {
      setAuthTesting(false)
    }
  }

  // 이미지 추출 및 분류 엔드포인트 연결 테스트(현재 입력값으로 작은 합성 이미지 1장 분류).
  async function handleTestImageClassification() {
    setIcTesting(true)
    try {
      const r = await testImageClassification({
        server_url: icServerUrl,
        model: icModel,
        api_key: icApiKey,
        auth_header: icAuthHeader,
        auth_scheme: icAuthScheme,
      })
      r.ok ? toast.success(r.message) : toast.error(r.message)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "연결 테스트 실패")
    } finally {
      setIcTesting(false)
    }
  }

  // 탭 상단: 용도 설명(좌) + 저장 버튼(우, 항상 right align)
  function SaveBar({ desc, readOnly }: { desc: string; readOnly?: boolean }) {
    return (
      <div className="mb-3 flex items-start justify-between gap-4">
        <p className="text-sm text-muted-foreground">{desc}</p>
        {!readOnly && (
          <Button onClick={handleSave} disabled={saving} className="ml-auto shrink-0">
            <Save className="size-4" />
            {saving ? "저장 중..." : "설정 저장"}
          </Button>
        )}
      </div>
    )
  }

  // databricks 자동 설정으로 바뀌는 각 필드의 setter — 되돌리기/원복에서 공용으로 사용.
  const fieldSetters: Record<string, (v: string) => void> = {
    "embedding.server_url": setServerUrl,
    "embedding.model": setModel,
    "embedding.api_key": setEmbeddingApiKey,
    "embedding.default_model": setEmbDefaultModel,
    "embedding.default_dim": setEmbDefaultDim,
    "embedding.default_metric": setEmbDefaultMetric,
    "llm.server_url": setLlmServerUrl,
    "llm.api_key": setLlmApiKey,
    "retrieval.vector_store": setVectorStore,
    "object_storage.backend": setStorageBackend,
  }

  // 현재 폼 값으로 Databricks 권장값을 적용한다(변경 전 값을 1회 기록). host/token 미입력 필드는 보류.
  function applyDatabricksDefaults(host: string, token: string) {
    const snap = { ...prevValues }
    const url = dbxServingUrl(host)
    const apply = (key: string, cur: string, target: string, setter: (v: string) => void) => {
      if (!target || cur === target) return // 유도 불가(빈 target)거나 이미 같으면 건너뜀
      if (!(key in snap)) snap[key] = cur // 변경 전 값 1회 기록
      setter(target)
    }
    apply("embedding.model", model, DBX.embeddingModel, setModel)
    apply("embedding.default_model", embDefaultModel, DBX.embeddingModel, setEmbDefaultModel)
    apply("embedding.default_dim", embDefaultDim, DBX.embeddingDim, setEmbDefaultDim)
    apply("embedding.default_metric", embDefaultMetric, DBX.embeddingMetric, setEmbDefaultMetric)
    apply("retrieval.vector_store", vectorStore, DBX.vectorStore, setVectorStore)
    apply("object_storage.backend", storageBackend, DBX.storageBackend, setStorageBackend)
    apply("embedding.server_url", serverUrl, url, setServerUrl)
    apply("llm.server_url", llmServerUrl, url, setLlmServerUrl)
    apply("embedding.api_key", embeddingApiKey, token, setEmbeddingApiKey)
    apply("llm.api_key", llmApiKey, token, setLlmApiKey)
    setPrevValues(snap)
  }

  // 단일 필드를 변경 전 값으로 되돌린다.
  function revertField(key: string) {
    const prev = prevValues[key]
    if (prev === undefined) return
    fieldSetters[key]?.(prev)
    setPrevValues((p) => {
      const np = { ...p }
      delete np[key]
      return np
    })
  }

  // standard 로 되돌릴 때, databricks 자동 변경분을 모두 원복하고 기록을 비운다.
  function revertAllDatabricks() {
    for (const [key, prev] of Object.entries(prevValues)) fieldSetters[key]?.(prev)
    setPrevValues({})
  }

  // 기반 환경 토글: databricks 선택 시 권장값 자동 적용, standard 복귀 시 자동 변경분 원복.
  function handleChangeBase(v: string) {
    setPlatformBase(v)
    if (v === "databricks") applyDatabricksDefaults(databricksHost, databricksToken)
    else revertAllDatabricks()
  }

  // Host 입력 변경 → databricks 모드면 serving-endpoints URL 을 재유도(변경 전 값 1회 기록).
  function handleChangeHost(v: string) {
    setDatabricksHost(v)
    if (platformBase !== "databricks") return
    const url = dbxServingUrl(v)
    if (!url) return
    const snap = { ...prevValues }
    if (serverUrl !== url) {
      if (!("embedding.server_url" in snap)) snap["embedding.server_url"] = serverUrl
      setServerUrl(url)
    }
    if (llmServerUrl !== url) {
      if (!("llm.server_url" in snap)) snap["llm.server_url"] = llmServerUrl
      setLlmServerUrl(url)
    }
    setPrevValues(snap)
  }

  // PAT 토큰 변경 → databricks 모드면 임베딩/LLM API 키를 토큰으로 동기화(변경 전 값 1회 기록).
  function handleChangeToken(v: string) {
    setDatabricksToken(v)
    if (platformBase !== "databricks" || !v) return
    const snap = { ...prevValues }
    if (embeddingApiKey !== v) {
      if (!("embedding.api_key" in snap)) snap["embedding.api_key"] = embeddingApiKey
      setEmbeddingApiKey(v)
    }
    if (llmApiKey !== v) {
      if (!("llm.api_key" in snap)) snap["llm.api_key"] = llmApiKey
      setLlmApiKey(v)
    }
    setPrevValues(snap)
  }

  // Row 에 넘길 이전값/되돌리기 props — prevValues 에 기록이 있을 때만.
  const prevProps = (key: string, secret = false) =>
    key in prevValues
      ? { prev: prevValues[key], prevSecret: secret, onRevert: () => revertField(key) }
      : {}

  // 기반 환경=databricks 일 때, 다른 탭에서 Databricks 값으로 바꿔야 하는 항목 라벨을 빨간색으로 강조.
  const dbx = platformBase === "databricks"

  return (
    <>
      <DashboardHeader title="설정" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        {loading || !data ? (
          <p className="text-sm text-muted-foreground">불러오는 중...</p>
        ) : (
          <UrlTabs defaultValue="platform">
            <TabsList>
              <TabsTrigger value="platform">기반 환경</TabsTrigger>
              <TabsTrigger value="embedding">임베딩</TabsTrigger>
              <TabsTrigger value="llm">생성 LLM</TabsTrigger>
              <TabsTrigger value="search">검색 · 리랭킹</TabsTrigger>
              <TabsTrigger value="vectorstore">벡터 DB</TabsTrigger>
              <TabsTrigger value="ingestion">인제스천</TabsTrigger>
              <TabsTrigger value="storage">오브젝트 스토리지</TabsTrigger>
              <TabsTrigger value="image-conversion">이미지 변환</TabsTrigger>
              <TabsTrigger value="image-classification">이미지 추출 및 분류</TabsTrigger>
              <TabsTrigger value="detection">검출</TabsTrigger>
              <TabsTrigger value="auth">인증</TabsTrigger>
              <TabsTrigger value="cors">CORS</TabsTrigger>
              <TabsTrigger value="etc">기타</TabsTrigger>
              <TabsTrigger value="system">시스템</TabsTrigger>
            </TabsList>

            {/* 기반 환경(Platform Profile) */}
            <TabsContent value="platform" className="mt-4">
              <SaveBar desc="시스템이 동작하는 기반 환경입니다. Databricks 선택 시 임베딩·LLM(이후 단계: 벡터DB·스토리지)의 기본값과 동작이 Databricks 규약에 맞춰집니다." />
              <SettingsTable>
                <Row name="기반 환경" desc={
                  <Opts items={[
                    ["standard", "기본(self-host / OpenAI 호환). 현행 동작 그대로 — bge-m3 등."],
                    ["databricks", "Databricks Foundation Model API / Mosaic AI 규약. 쿼리 instruction 비대칭(Qwen3-Embedding) 적용, 인증은 PAT 토큰."],
                  ]} />
                }>
                  <Select value={platformBase} onValueChange={handleChangeBase}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="standard">standard (기본 · self-host)</SelectItem>
                      <SelectItem value="databricks">Databricks</SelectItem>
                    </SelectContent>
                  </Select>
                </Row>
                {platformBase === "databricks" && (
                  <>
                    <Row name="Databricks Host" desc="워크스페이스 URL. 예) https://<workspace>.cloud.databricks.com — 입력하면 임베딩/LLM 의 '서버 URL' 이 자동으로 {host}/serving-endpoints 로 채워집니다.">
                      <Input value={databricksHost} onChange={(e) => handleChangeHost(e.target.value)} placeholder="https://<workspace>.cloud.databricks.com" />
                    </Row>
                    <Row name="PAT 토큰" desc="Databricks Personal Access Token. 가려서(••••) 표시되며 eye 아이콘으로 확인할 수 있습니다. 입력하면 임베딩/LLM 의 'API 키' 가 이 토큰으로 자동 채워집니다. (환경변수 ARGUS_DATABRICKS_TOKEN 으로도 설정 가능)">
                      <SecretInput value={databricksToken} onChange={handleChangeToken} placeholder="dapi…" />
                    </Row>
                  </>
                )}
              </SettingsTable>
              {platformBase === "databricks" && (
                <>
                  <div className="mt-3 flex gap-2">
                    <Button variant="outline" size="sm" onClick={handleTestDatabricks} disabled={dbxTesting}>
                      <Plug className="size-4" />
                      {dbxTesting ? "테스트 중..." : "연결 테스트"}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => applyDatabricksDefaults(databricksHost, databricksToken)}
                    >
                      <RefreshCw className="size-4" />
                      Databricks 권장값 적용
                    </Button>
                  </div>
                  <p className="mt-2 text-xs text-amber-600">
                    ⚠️ 기반 환경 전환은 <b>신규 컬렉션의 기본값·검색 동작</b>에만 적용됩니다. 기존 컬렉션은 생성 시점 임베딩 모델이 고정되어 그대로 유지됩니다(재임베딩하려면 새 컬렉션 생성 필요).
                  </p>
                </>
              )}
              <p className="mt-2 text-xs text-muted-foreground">
                Databricks 가 쿼리에 적용하는 instruction 과 정확히 맞춰야 벡터 공간이 일치합니다 — 임베딩 탭의 <b>쿼리 instruction</b> 에서 지정하세요(비우면 Qwen3-Embedding 기본 지시문 사용).
              </p>
              {platformBase === "databricks" && (
                <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm dark:border-red-900/40 dark:bg-red-950/20">
                  <p className="font-medium text-red-700 dark:text-red-300">
                    Databricks 기반 환경 — 다른 탭에서 추가 설정이 필요합니다
                  </p>
                  <p className="mt-1 text-xs text-red-700/90 dark:text-red-300/80">
                    전환 시 아래 항목이 Databricks 권장값으로 <b>자동 설정</b>됩니다(모델·차원·벡터스토어·스토리지). 서버 URL·API 키는 위 <b>Host/PAT 토큰</b>을 입력하면 자동으로 채워집니다(serving-endpoints·PAT).
                    각 탭에서 <span className="font-semibold text-red-600 dark:text-red-400">빨간색 *</span> 로 표시되며, 자동 변경된 항목은 입력 아래에 <b>이전값</b>과 <b>되돌리기</b>가 함께 표시됩니다. 값이 다르면 직접 수정하세요.
                  </p>
                  <ul className="mt-2 space-y-1 text-xs text-red-800 dark:text-red-200">
                    <li>
                      <b>임베딩</b> 탭 — 서버 URL(serving-endpoints), 모델, API 키(PAT 토큰), 쿼리 instruction
                    </li>
                    <li>
                      <b>생성 LLM</b> 탭 — 서버 URL(serving-endpoints), 모델, API 키(PAT 토큰)
                    </li>
                    <li>
                      <b>벡터 DB</b> 탭 — 벡터 스토어 = Databricks + Vector Search 엔드포인트·카탈로그·스키마, 저장 후 <b>벡터 재색인</b>
                    </li>
                    <li>
                      <b>오브젝트 스토리지</b> 탭 — 백엔드 = Unity Catalog Volumes + 카탈로그·스키마·볼륨
                    </li>
                  </ul>
                </div>
              )}
            </TabsContent>

            {/* 임베딩 */}
            <TabsContent value="embedding" className="mt-4">
              <SaveBar desc="문서를 벡터로 변환하는 임베딩 모델/서버 설정입니다. 인제스천(색인)과 검색 질의 임베딩에 공통으로 사용됩니다." />
              <SettingsTable>
                <Row name="프로바이더" desc={
                  <Opts items={[
                    ["openai_compatible", "TEI·Ollama·vLLM 등 OpenAI 호환 /embeddings 엔드포인트 호출(권장)"],
                    ["local", "프로세스 내 FastEmbed 로컬 임베딩 — 외부 서버 불필요"],
                    ["hash", "외부 서버 없이 텍스트 해시로 결정적 더미 벡터 — 오프라인·에어갭 검증용(품질 낮음)"],
                  ]} />
                }>
                  <Select value={provider} onValueChange={setProvider}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="openai_compatible">OpenAI 호환 (TEI/Ollama/vLLM)</SelectItem>
                      <SelectItem value="local">로컬 (FastEmbed)</SelectItem>
                      <SelectItem value="hash">hash (오프라인 더미)</SelectItem>
                    </SelectContent>
                  </Select>
                </Row>
                <Row name="서버 URL" highlight={dbx} {...prevProps("embedding.server_url")} desc="openai_compatible 일 때 임베딩 서버 베이스 URL. 예) http://192.0.2.50:8080/v1 · Databricks 는 serving-endpoints 베이스(https://<workspace>/serving-endpoints).">
                  <div className="flex flex-col gap-1.5">
                    <ServiceEndpointPicker kind="embedding" value={serverUrl} className="h-9 w-full text-sm" onPick={(svc) => { if (svc) { setServerUrl(svc.url); if (svc.model) setModel(svc.model) } }} />
                    <Input value={serverUrl} onChange={(e) => setServerUrl(e.target.value)} />
                  </div>
                </Row>
                <Row name="모델" highlight={dbx} {...prevProps("embedding.model")} desc="서버가 서빙하는 임베딩 모델명. 예) bge-m3 — 모델이 출력 차원을 결정합니다. Databricks 는 서빙 임베딩 엔드포인트명을 입력합니다.">
                  <Input value={model} onChange={(e) => setModel(e.target.value)} />
                </Row>
                <Row name="쿼리 instruction" highlight={dbx} desc="instruction-aware 모델(Qwen3-Embedding 등)에서 검색 쿼리에만 붙는 지시문. 문서는 원문 그대로 임베딩됩니다. 비우면 기반 환경 프로파일 기본값을 따릅니다(standard=없음, databricks=Qwen 기본 지시문). Databricks 서빙 규약과 글자 단위로 일치시키려면 직접 입력하세요.">
                  <Input value={embQueryInstruction} onChange={(e) => setEmbQueryInstruction(e.target.value)} placeholder="(비움 = 프로파일 기본값)" />
                </Row>
                <Row name="배치 크기" desc="한 번에 임베딩 요청할 청크 수. 클수록 처리량↑·메모리↑. 기본 32.">
                  <Input type="number" value={batchSize} onChange={(e) => setBatchSize(e.target.value)} />
                </Row>
                <Row name="API 키" highlight={dbx} {...prevProps("embedding.api_key", true)} desc="임베딩 서버 인증 키. 기본은 가려서(••••) 표시되며 eye 아이콘으로 확인할 수 있습니다. Databricks 는 PAT 토큰을 입력합니다. (환경변수 ARGUS_EMBEDDING_API_KEY 로도 설정 가능)">
                  <SecretInput
                    value={embeddingApiKey}
                    onChange={setEmbeddingApiKey}
                    placeholder="미설정"
                  />
                </Row>
                <Row name="타임아웃(초)" desc="임베딩 서버 호출 타임아웃. 기본 60.">
                  <Input type="number" value={embTimeout} onChange={(e) => setEmbTimeout(e.target.value)} />
                </Row>
                <Row name="인증 헤더" desc="인증 헤더 이름. 기본 Authorization. X-API-Key 게이트웨이면 변경.">
                  <Input value={embAuthHeader} onChange={(e) => setEmbAuthHeader(e.target.value)} />
                </Row>
                <Row name="인증 스킴" desc="헤더 값 접두. 기본 Bearer. X-API-Key 처럼 접두가 없으면 비웁니다.">
                  <Input value={embAuthScheme} onChange={(e) => setEmbAuthScheme(e.target.value)} placeholder="(비움 가능)" />
                </Row>
                <Row name="기본 모델(컬렉션)" highlight={dbx} {...prevProps("embedding.default_model")} desc="컬렉션 생성 시 기본으로 채울 임베딩 모델명.">
                  <Input value={embDefaultModel} onChange={(e) => setEmbDefaultModel(e.target.value)} />
                </Row>
                <Row name="기본 차원(컬렉션)" highlight={dbx} {...prevProps("embedding.default_dim")} desc="컬렉션 생성 기본 벡터 차원. 모델 출력 차원과 일치해야 합니다.">
                  <Input type="number" value={embDefaultDim} onChange={(e) => setEmbDefaultDim(e.target.value)} />
                </Row>
                <Row name="기본 거리 메트릭" highlight={dbx} {...prevProps("embedding.default_metric")} desc="컬렉션 기본 거리 함수. cosine / l2 / ip 등.">
                  <Input value={embDefaultMetric} onChange={(e) => setEmbDefaultMetric(e.target.value)} />
                </Row>
              </SettingsTable>
              {provider === "openai_compatible" && (
                <>
                  <div className="mt-3">
                    <Button variant="outline" size="sm" onClick={handleTestEmbedding} disabled={embTesting}>
                      <Plug className="size-4" />
                      {embTesting ? "테스트 중..." : "연결 테스트"}
                    </Button>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">
                    <b>현재 입력 URL</b>로 임베딩 서버 접속을 확인합니다(저장 전 검증). 모델을 입력하면 차원 감지까지 시도합니다.
                  </p>
                </>
              )}
            </TabsContent>

            {/* 생성 LLM */}
            <TabsContent value="llm" className="mt-4">
              <SaveBar desc="RAG 답변 생성에 사용하는 LLM 설정입니다. 검색된 컨텍스트로 최종 답변을 만들 때 호출됩니다." />
              <SettingsTable>
                <Row name="프로바이더" desc={
                  <Opts items={[
                    ["openai_compatible", "사내·vLLM·Ollama 등 OpenAI 호환 /chat/completions 호출"],
                    ["anthropic", "Anthropic Claude — 공식 SDK 사용"],
                  ]} />
                }>
                  <Select value={llmProvider} onValueChange={setLlmProvider}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="openai_compatible">OpenAI 호환 (사내/vLLM/Ollama)</SelectItem>
                      <SelectItem value="anthropic">Claude (Anthropic)</SelectItem>
                    </SelectContent>
                  </Select>
                </Row>
                <Row name="서버 URL" highlight={dbx} {...prevProps("llm.server_url")} desc="openai_compatible 일 때 LLM 서버 베이스 URL. 예) http://192.0.2.50:8080/v1 · Databricks 는 serving-endpoints 베이스(https://<workspace>/serving-endpoints).">
                  <div className="flex flex-col gap-1.5">
                    <ServiceEndpointPicker kind="vlm" value={llmServerUrl} className="h-9 w-full text-sm" onPick={(svc) => { if (svc) { setLlmServerUrl(svc.url); if (svc.model) setLlmModel(svc.model) } }} />
                    <Input value={llmServerUrl} onChange={(e) => setLlmServerUrl(e.target.value)} placeholder="http://192.0.2.50:8080/v1" />
                  </div>
                </Row>
                <Row name="모델" highlight={dbx} desc="서빙 모델명. anthropic 은 비워두면 claude-opus-4-8 을 사용합니다. Databricks 는 서빙 LLM 엔드포인트명을 입력합니다.">
                  <Input value={llmModel} onChange={(e) => setLlmModel(e.target.value)} placeholder="모델명" />
                </Row>
                <Row name="최대 토큰" desc="응답으로 생성할 최대 토큰 수. 길수록 답변이 길어질 수 있고 지연·비용↑.">
                  <Input type="number" value={llmMaxTokens} onChange={(e) => setLlmMaxTokens(e.target.value)} />
                </Row>
                <Row name="Temperature" desc="0~2. 낮을수록 결정적·일관적, 높을수록 다양·창의적. RAG 는 0~0.3 권장.">
                  <Input type="number" step="0.1" value={llmTemperature} onChange={(e) => setLlmTemperature(e.target.value)} />
                </Row>
                <Row name="API 키" highlight={dbx} {...prevProps("llm.api_key", true)} desc="LLM 서버 인증 키. 기본은 가려서(••••) 표시되며 eye 아이콘으로 확인할 수 있습니다. Databricks 는 PAT 토큰을 입력합니다. (환경변수 ARGUS_LLM_API_KEY 로도 설정 가능)">
                  <SecretInput value={llmApiKey} onChange={setLlmApiKey} placeholder="미설정" />
                </Row>
                <Row name="타임아웃(초)" desc="LLM 서버 호출 타임아웃. 기본 120.">
                  <Input type="number" value={llmTimeout} onChange={(e) => setLlmTimeout(e.target.value)} />
                </Row>
                <Row name="인증 헤더" desc="인증 헤더 이름. 기본 Authorization.">
                  <Input value={llmAuthHeader} onChange={(e) => setLlmAuthHeader(e.target.value)} />
                </Row>
                <Row name="인증 스킴" desc="헤더 값 접두. 기본 Bearer. 접두가 없으면 비웁니다.">
                  <Input value={llmAuthScheme} onChange={(e) => setLlmAuthScheme(e.target.value)} placeholder="(비움 가능)" />
                </Row>
              </SettingsTable>
            </TabsContent>

            {/* 검색 · 리랭킹 */}
            <TabsContent value="search" className="mt-4">
              <SaveBar desc="하이브리드 검색(벡터+렉시컬)의 후보 수와 융합·리랭킹 파라미터입니다. 검색 품질과 지연의 균형을 조정합니다." />
              <SettingsTable>
                <Row name="리랭커" desc={
                  <Opts items={[
                    ["none", "리랭킹 없이 RRF 융합 순위만 사용 — 가장 빠름"],
                    ["llm", "LLM 으로 관련도 재점수 — 품질↑, 비용·지연↑"],
                    ["local", "프로세스 내 FastEmbed cross-encoder 리랭크"],
                    ["cross_encoder", "외부 cross-encoder 리랭커 서버 호출"],
                  ]} />
                }>
                  <Select value={rerankProvider} onValueChange={setRerankProvider}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">사용 안 함 (RRF만)</SelectItem>
                      <SelectItem value="llm">LLM 리랭크</SelectItem>
                      <SelectItem value="local">로컬 cross-encoder (FastEmbed)</SelectItem>
                      <SelectItem value="cross_encoder">Cross-encoder 서버</SelectItem>
                    </SelectContent>
                  </Select>
                </Row>
                <Row name="리랭커 서버 URL" desc="cross_encoder 일 때 리랭커 엔드포인트. 예) http://…/rerank">
                  <div className="flex flex-col gap-1.5">
                    <ServiceEndpointPicker kind="reranker" value={rerankServerUrl} className="h-9 w-full text-sm" onPick={(svc) => { if (svc) setRerankServerUrl(svc.url) }} />
                    <Input value={rerankServerUrl} onChange={(e) => setRerankServerUrl(e.target.value)} placeholder="http://…/rerank" />
                  </div>
                </Row>
                <Row name="리랭커 API 키" desc="cross_encoder 서버 인증 키. 기본은 가려서(••••) 표시. (환경변수 ARGUS_RERANK_API_KEY 로도 설정 가능)">
                  <SecretInput value={rerankApiKey} onChange={setRerankApiKey} placeholder="미설정" />
                </Row>
                <Row name="리랭커 top_n" desc="리랭킹 후 반환할 상위 문서 수. 기본 5.">
                  <Input type="number" value={rerankTopN} onChange={(e) => setRerankTopN(e.target.value)} />
                </Row>
                <Row name="리랭커 인증 헤더" desc="인증 헤더 이름. 기본 Authorization.">
                  <Input value={rerankAuthHeader} onChange={(e) => setRerankAuthHeader(e.target.value)} />
                </Row>
                <Row name="리랭커 인증 스킴" desc="헤더 값 접두. 기본 Bearer. 접두가 없으면 비웁니다.">
                  <Input value={rerankAuthScheme} onChange={(e) => setRerankAuthScheme(e.target.value)} placeholder="(비움 가능)" />
                </Row>
                <Row name="top_k" desc="최종 반환(컨텍스트로 전달)할 문서 수. 기본 5.">
                  <Input type="number" value={topK} onChange={(e) => setTopK(e.target.value)} />
                </Row>
                <Row name="vector_k" desc="융합 전 벡터 검색에서 가져올 후보 수. 클수록 재현율↑·연산↑.">
                  <Input type="number" value={vectorK} onChange={(e) => setVectorK(e.target.value)} />
                </Row>
                <Row name="lexical_k" desc="융합 전 렉시컬(tsvector) 검색에서 가져올 후보 수.">
                  <Input type="number" value={lexicalK} onChange={(e) => setLexicalK(e.target.value)} />
                </Row>
                <Row name="rrf_k" desc="RRF(Reciprocal Rank Fusion) 상수. 클수록 상위 순위 가중이 완만해집니다. 기본 60.">
                  <Input type="number" value={rrfK} onChange={(e) => setRrfK(e.target.value)} />
                </Row>
              </SettingsTable>
              {rerankProvider === "cross_encoder" && (
                <>
                  <div className="mt-3">
                    <Button variant="outline" size="sm" onClick={handleTestRerank} disabled={rerankTesting}>
                      <Plug className="size-4" />
                      {rerankTesting ? "테스트 중..." : "연결 테스트"}
                    </Button>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">
                    <b>현재 입력 URL</b>의 리랭커 서버에 <span className="font-mono">/v1/models</span>로 접속을 확인합니다(저장 전 검증).
                  </p>
                </>
              )}
            </TabsContent>

            {/* 벡터 DB */}
            <TabsContent value="vectorstore" className="mt-4">
              <SaveBar desc="임베딩 벡터를 저장·검색하는 백엔드입니다. 기본 pgvector 는 PostgreSQL 내장이며, 외부 DB 선택 시 연결 후 '벡터 재색인'이 필요합니다." />
              <SettingsTable>
                <Row name="벡터 스토어" highlight={dbx} {...prevProps("retrieval.vector_store")} desc={
                  <Opts items={[
                    ["pgvector", "PostgreSQL 내장 — 별도 서버 불필요(기본). 정본과 동일해 재색인 불필요"],
                    ["qdrant", "Qdrant 서버 — 샤딩·복제·페이로드 필터 강점"],
                    ["weaviate", "Weaviate 서버"],
                    ["milvus", "Milvus / Zilliz Cloud"],
                    ["databricks", "Databricks Mosaic AI Vector Search — 인증은 기반 환경의 Databricks Host/PAT 토큰 재사용"],
                  ]} />
                }>
                  <Select value={vectorStore} onValueChange={setVectorStore}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {VECTOR_STORES.map((v) => (
                        <SelectItem key={v.value} value={v.value}>{v.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Row>
                <Row name="컬렉션 접두사" desc="외부 DB 에 생성할 컬렉션 명 접두. 컬렉션마다 {접두사}_c{ID} 형태로 만들어집니다. 예) argus_c12">
                  <Input value={vectorStorePrefix} onChange={(e) => setVectorStorePrefix(e.target.value)} placeholder="argus" />
                </Row>
                {vectorStore !== "pgvector" && vectorStore !== "databricks" && (
                  <>
                    <Row name="연결 URL" desc="외부 벡터 DB 엔드포인트. provider 기본 포트 — Qdrant 6333 / Weaviate 8080 / Milvus 19530.">
                      <Input
                        value={vectorStoreUrl}
                        onChange={(e) => setVectorStoreUrl(e.target.value)}
                        placeholder={
                          vectorStore === "qdrant" ? "http://localhost:6333"
                            : vectorStore === "weaviate" ? "http://localhost:8080"
                              : "http://localhost:19530"
                        }
                      />
                    </Row>
                    <Row name="API 키 / 토큰" desc="인증이 필요한 경우 입력합니다(예: Qdrant API key, Zilliz token). 기본은 가려서(••••) 표시되며 eye 아이콘으로 확인할 수 있습니다.">
                      <SecretInput
                        value={vectorStoreApiKey}
                        onChange={setVectorStoreApiKey}
                        placeholder="없으면 비워두세요"
                      />
                    </Row>
                  </>
                )}
                {vectorStore === "databricks" && (
                  <>
                    <Row name="Vector Search 엔드포인트" highlight={dbx} desc="Mosaic AI Vector Search 엔드포인트(컴퓨트) 이름. Databricks 콘솔에서 미리 생성해 둡니다. 인증은 '기반 환경' 탭의 Databricks Host/PAT 토큰을 그대로 씁니다.">
                      <Input value={dbxVsEndpoint} onChange={(e) => setDbxVsEndpoint(e.target.value)} placeholder="예) argus-vs-endpoint" />
                    </Row>
                    <Row name="Unity Catalog · Catalog" highlight={dbx} desc="인덱스가 생성될 Unity Catalog 카탈로그. 인덱스 전체 이름은 {catalog}.{schema}.{접두사}_c{ID} 입니다.">
                      <Input value={dbxVsCatalog} onChange={(e) => setDbxVsCatalog(e.target.value)} placeholder="main" />
                    </Row>
                    <Row name="Unity Catalog · Schema" highlight={dbx} desc="인덱스가 생성될 스키마(데이터베이스).">
                      <Input value={dbxVsSchema} onChange={(e) => setDbxVsSchema(e.target.value)} placeholder="argus" />
                    </Row>
                  </>
                )}
              </SettingsTable>
              {vectorStore === "databricks" && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Argus 가 임베딩을 직접 계산해 밀어넣는 <b>Direct Vector Access 인덱스</b>를 사용합니다(임베딩은 임베딩 탭 설정을 따름). 엔드포인트·카탈로그·스키마는 Databricks 콘솔에서 미리 준비되어 있어야 합니다.
                </p>
              )}

              <div className="mt-4 flex flex-col gap-3 rounded-md border border-amber-200 bg-amber-50 p-3 dark:border-amber-900/40 dark:bg-amber-950/20">
                <div className="flex items-start gap-2 text-sm text-amber-900 dark:text-amber-200">
                  <Database className="mt-0.5 size-4 shrink-0" />
                  <div className="space-y-1">
                    <p className="font-medium">전환해도 기존 벡터는 자동으로 옮겨지지 않습니다.</p>
                    <p className="text-amber-800/90 dark:text-amber-200/80">
                      벡터 스토어를 외부 DB로 바꿔 저장한 뒤, 아래 <b>벡터 재색인</b>을 한 번 실행해야
                      PostgreSQL 정본의 임베딩이 새 스토어로 적재되어 기존 문서가 검색됩니다.
                      (pgvector 는 정본과 동일해 재색인이 필요 없습니다.)
                    </p>
                  </div>
                </div>
                <div>
                  <Button variant="outline" size="sm" onClick={handleReindex} disabled={reindexing}>
                    <RefreshCw className={`size-4${reindexing ? " animate-spin" : ""}`} />
                    {reindexing ? "재색인 중..." : "벡터 재색인"}
                  </Button>
                </div>
              </div>
            </TabsContent>

            {/* 인제스천 */}
            <TabsContent value="ingestion" className="mt-4">
              <SaveBar desc="문서를 청크(검색 단위)로 분할하는 기본값입니다. 컬렉션이 별도 값을 지정하지 않으면 이 값이 사용됩니다." />
              <SettingsTable>
                <Row name="청크 크기" desc="청크 1개의 최대 문자 수. 작을수록 정밀하지만 문맥이 분절되고, 클수록 문맥은 풍부하나 노이즈↑.">
                  <Input type="number" value={chunkSize} onChange={(e) => setChunkSize(e.target.value)} />
                </Row>
                <Row name="청크 오버랩" desc="인접 청크 간 겹치는 문자 수. 경계에서 잘리는 문맥을 보존합니다. 보통 청크 크기의 10~20%.">
                  <Input type="number" value={chunkOverlap} onChange={(e) => setChunkOverlap(e.target.value)} />
                </Row>
                <Row name="워커 폴링 주기(초)" desc="비동기 인제스천 워커가 새 작업을 확인하는 주기. 기본 2.0.">
                  <Input type="number" step="0.5" value={workerInterval} onChange={(e) => setWorkerInterval(e.target.value)} />
                </Row>
                <Row name="KSS 폴백 임계(자)" desc="이 길이를 넘는 텍스트는 KSS(한국어 문장분리) 지연을 피해 규칙 기반으로 처리. 기본 5000.">
                  <Input type="number" value={maxKssChars} onChange={(e) => setMaxKssChars(e.target.value)} />
                </Row>
                <Row name="최소 청크 비율" desc="청크 크기 대비 최소 청크 비율(작은 청크 병합 기준). 0~1, 기본 0.1.">
                  <Input type="number" step="0.05" value={minChunkRatio} onChange={(e) => setMinChunkRatio(e.target.value)} />
                </Row>
                <Row name="시맨틱 경계 백분위" desc="시맨틱 청킹에서 의미 경계로 볼 인접 문장 거리 백분위. 기본 90.">
                  <Input type="number" value={semanticPct} onChange={(e) => setSemanticPct(e.target.value)} />
                </Row>
                <Row name="NiFi 서비스 토큰" desc="외부 파이프라인(NiFi)이 /ingestion/register 호출 시 검증할 토큰. 비우면 인증 비강제(개발용).">
                  <SecretInput value={serviceToken} onChange={setServiceToken} placeholder="미설정" />
                </Row>
              </SettingsTable>
            </TabsContent>

            {/* 오브젝트 스토리지 */}
            <TabsContent value="storage" className="mt-4">
              <SaveBar desc="원본 문서·아티팩트를 저장하는 스토리지 설정입니다. 기본 S3 호환(MinIO/S3) 또는 Databricks Unity Catalog Volumes 를 선택할 수 있습니다. 인제스천 시 업로드한 파일이 여기에 저장됩니다." />
              <SettingsTable>
                <Row name="스토리지 백엔드" highlight={dbx} {...prevProps("object_storage.backend")} desc={
                  <Opts items={[
                    ["s3", "S3 호환(MinIO/S3) — 기본. 아래 엔드포인트·키·버킷 사용."],
                    ["uc_volumes", "Databricks Unity Catalog Volumes — 인증은 '기반 환경'의 Databricks Host/PAT 토큰 재사용. RAG 문서 경로 지원(presigned·rename 등 일부 파일브라우저 기능 미지원)."],
                  ]} />
                }>
                  <Select value={storageBackend} onValueChange={setStorageBackend}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="s3">S3 호환 (MinIO/S3)</SelectItem>
                      <SelectItem value="uc_volumes">Databricks (Unity Catalog Volumes)</SelectItem>
                    </SelectContent>
                  </Select>
                </Row>
                {storageBackend === "uc_volumes" && (
                  <>
                    <Row name="UC · Catalog" highlight={dbx} desc="문서 Volume 이 위치한 Unity Catalog 카탈로그. 경로: /Volumes/{catalog}/{schema}/{volume}">
                      <Input value={dbxVolCatalog} onChange={(e) => setDbxVolCatalog(e.target.value)} placeholder="main" />
                    </Row>
                    <Row name="UC · Schema" highlight={dbx} desc="Volume 이 위치한 스키마(데이터베이스).">
                      <Input value={dbxVolSchema} onChange={(e) => setDbxVolSchema(e.target.value)} placeholder="argus" />
                    </Row>
                    <Row name="UC · Volume" highlight={dbx} desc="문서를 저장할 Volume 이름. Databricks 콘솔에서 미리 생성되어 있어야 합니다.">
                      <Input value={dbxVolVolume} onChange={(e) => setDbxVolVolume(e.target.value)} placeholder="documents" />
                    </Row>
                  </>
                )}
                {storageBackend !== "uc_volumes" && (
                  <>
                    <Row name="엔드포인트" desc="S3 호환 엔드포인트 URL. MinIO 예) http://minio:9000 · AWS 는 비우거나 리전 엔드포인트 사용.">
                      <Input value={osEndpoint} onChange={(e) => setOsEndpoint(e.target.value)} placeholder="http://localhost:9000" />
                    </Row>
                    <Row name="Access Key" desc="S3 액세스 키(사용자명에 해당).">
                      <Input value={osAccessKey} onChange={(e) => setOsAccessKey(e.target.value)} />
                    </Row>
                    <Row name="Secret Key" desc="S3 시크릿 키. 기본은 가려서(••••) 표시되며 eye 아이콘으로 확인할 수 있습니다.">
                      <SecretInput value={osSecretKey} onChange={setOsSecretKey} placeholder="미설정" />
                    </Row>
                    <Row name="리전" desc="S3 리전. MinIO 는 보통 us-east-1 사용.">
                      <Input value={osRegion} onChange={(e) => setOsRegion(e.target.value)} placeholder="us-east-1" />
                    </Row>
                    <Row name="SSL 사용" desc="HTTPS 로 접속할지 여부. 사내 HTTP MinIO 는 '사용 안 함'.">
                      <Select value={osUseSsl} onValueChange={setOsUseSsl}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="false">사용 안 함 (HTTP)</SelectItem>
                          <SelectItem value="true">사용 (HTTPS)</SelectItem>
                        </SelectContent>
                      </Select>
                    </Row>
                    <Row name="문서 버킷" desc="문서를 저장할 버킷 이름. 없으면 아래 '버킷 초기화'로 생성할 수 있습니다.">
                      <Input value={osBucket} onChange={(e) => setOsBucket(e.target.value)} placeholder="rag-documents" />
                    </Row>
                  </>
                )}
                <Row name="이미지 라벨링 버킷" desc="이미지 라벨링 탐색기 전용 버킷(S3). 원본 문서 버킷과 분리됩니다. ※ 현재 단계에서 이미지 라벨링·분류 버킷은 백엔드와 무관하게 S3 를 사용합니다.">
                  <Input value={annotationBucket} onChange={(e) => setAnnotationBucket(e.target.value)} placeholder="annotation-images" />
                </Row>
                <Row name="이미지 추출 및 분류 버킷" desc="이미지 추출 및 분류 결과(원본·썸네일·분석 JSON)를 저장하는 버킷(S3). 원본 문서·라벨링 버킷과 분리됩니다.">
                  <Input value={classificationBucket} onChange={(e) => setClassificationBucket(e.target.value)} placeholder="classification-images" />
                </Row>
                <Row name="모델 저장소 버킷 (Model Repository)" desc="에어갭 모델 팩(가중치 아카이브+manifest)을 보관하는 버킷(S3). 모델 관리 화면의 보유 확인과 배포 시 자동 설치·서버 팩 업로드가 이 버킷을 사용합니다. 없으면 서버 기동 시 자동 생성되며, 아래 '버킷 초기화'로도 만들 수 있습니다.">
                  <Input value={modelsBucket} onChange={(e) => setModelsBucket(e.target.value)} placeholder="argus-models" />
                </Row>
                <Row name="presigned URL 만료(초)" desc="미리보기/다운로드용 presigned URL 의 유효 시간(S3 백엔드). 기본 3600(1시간).">
                  <Input type="number" value={presignExpiry} onChange={(e) => setPresignExpiry(e.target.value)} />
                </Row>
              </SettingsTable>
              {storageBackend !== "uc_volumes" && (
                <div className="mt-3 flex gap-2">
                  <Button variant="outline" size="sm" onClick={handleTestStorage} disabled={osTesting}>
                    <Plug className="size-4" />
                    {osTesting ? "테스트 중..." : "연결 테스트"}
                  </Button>
                  <Button variant="outline" size="sm" onClick={handleInitStorage} disabled={osIniting}>
                    <FolderPlus className="size-4" />
                    {osIniting ? "초기화 중..." : "버킷 초기화"}
                  </Button>
                </div>
              )}
              {storageBackend === "uc_volumes" ? (
                <p className="mt-2 text-xs text-amber-600">
                  ⚠️ 백엔드 전환 시 기존 객체는 자동 이동하지 않습니다 — 전환 후 문서를 다시 인제스천해야 합니다. Volume 은 Databricks 콘솔에서 미리 생성되어 있어야 하며, 인증은 '기반 환경' 탭의 Databricks Host/PAT 토큰을 사용합니다.
                </p>
              ) : (
                <p className="mt-2 text-xs text-muted-foreground">
                  연결 테스트·초기화는 <b>현재 입력값</b>으로 동작합니다(저장 전 검증 가능). Secret Key 를 비워두면 저장된 값을 사용합니다.
                </p>
              )}
            </TabsContent>

            {/* 이미지 변환 */}
            <TabsContent value="image-conversion" className="mt-4">
              <SaveBar desc="이미지 라벨링의 '문서 변환'에서 문서를 페이지별 이미지로 만들 때의 설정입니다. PDF·오피스(doc/ppt/xls 등)는 항상 서버(LibreOffice/PyMuPDF)에서 변환하며, HWP/HWPX 만 아래 엔진을 선택할 수 있습니다." />
              <SettingsTable>
                <Row name="HWP/HWPX 변환 엔진" desc={
                  <Opts items={[
                    ["rhwp", "브라우저(클라이언트)에서 @rhwp/core(WASM)로 페이지를 렌더 — 서버 설치 불필요(기본). HWP 미리보기와 동일 엔진"],
                    ["libreoffice", "서버 LibreOffice(soffice)로 PDF 변환 후 래스터화 — 서버에 LibreOffice 설치 필요, 레이아웃 충실도↑"],
                  ]} />
                }>
                  <Select value={hwpEngine} onValueChange={setHwpEngine}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="rhwp">rhwp (클라이언트 · WASM)</SelectItem>
                      <SelectItem value="libreoffice">LibreOffice (서버)</SelectItem>
                    </SelectContent>
                  </Select>
                </Row>
                <Row name="변환 해상도(DPI)" desc="PDF·오피스 페이지를 이미지로 래스터화할 해상도. 36~600, 기본 150.">
                  <Input type="number" value={convDpi} onChange={(e) => setConvDpi(e.target.value)} />
                </Row>
                <Row name="썸네일 최대 변(px)" desc="변환 페이지 썸네일의 긴 변 최대 픽셀. 기본 320.">
                  <Input type="number" value={convThumbMax} onChange={(e) => setConvThumbMax(e.target.value)} />
                </Row>
                <Row name="HWP 렌더 배율" desc="rhwp(클라이언트) 렌더 배율. 클수록 선명·메모리↑. 기본 2.0.">
                  <Input type="number" step="0.5" value={convHwpScale} onChange={(e) => setConvHwpScale(e.target.value)} />
                </Row>
                <Row name="LibreOffice 동시 변환" desc="동시에 실행할 soffice 프로세스 수. 무거우므로 보통 2. (libreoffice 엔진/오피스 변환)">
                  <Input type="number" value={convOfficeConc} onChange={(e) => setConvOfficeConc(e.target.value)} />
                </Row>
                <Row name="LibreOffice 타임아웃(초)" desc="오피스→PDF 변환 타임아웃. 기본 90.">
                  <Input type="number" value={convOfficeTimeout} onChange={(e) => setConvOfficeTimeout(e.target.value)} />
                </Row>
              </SettingsTable>
            </TabsContent>

            {/* 이미지 추출 및 분류(VLM) */}
            <TabsContent value="image-classification" className="mt-4">
              <SaveBar desc="인제스천 시 문서 내 이미지를 비전 LLM(VLM)으로 도표/차트/사진 등으로 식별합니다. 사용이 켜져 있을 때만 동작하며, 분류 결과는 문서 메타데이터(image_classification)에 저장됩니다. 서버 URL·모델을 비우면 '생성 LLM' 설정을 그대로 재사용합니다(전용 vLLM Qwen2.5-VL 엔드포인트를 가리키려면 채우세요)." />
              <SettingsTable>
                <Row name="사용" desc="이미지 추출 및 분류 활성화 여부. 끄면(기본) 인제스천에서 분류를 건너뜁니다(기존 동작과 동일).">
                  <Select value={icEnabled} onValueChange={setIcEnabled}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="false">사용 안 함</SelectItem>
                      <SelectItem value="true">사용</SelectItem>
                    </SelectContent>
                  </Select>
                </Row>
                <Row name="서버 URL" desc="OpenAI 호환 비전 엔드포인트 베이스 URL. 비우면 생성 LLM 서버를 재사용. 예) http://192.0.2.50:8083/v1">
                  <div className="flex flex-col gap-1.5">
                    <ServiceEndpointPicker kind="vlm" value={icServerUrl} className="h-9 w-full text-sm" onPick={(svc) => { if (svc) { setIcServerUrl(svc.url); if (svc.model) setIcModel(svc.model) } }} />
                    <Input value={icServerUrl} onChange={(e) => setIcServerUrl(e.target.value)} placeholder="(비우면 생성 LLM 재사용)" />
                  </div>
                </Row>
                <Row name="모델" desc="서빙 중인 비전 모델명. 비우면 생성 LLM 모델을 사용. 예) qwen2.5-vl">
                  <Input value={icModel} onChange={(e) => setIcModel(e.target.value)} placeholder="(비우면 생성 LLM 모델)" />
                </Row>
                <Row name="API 키" desc="비전 서버 인증 키. 비우면 생성 LLM 키로 폴백. 기본은 가려서(••••) 표시. (환경변수 ARGUS_IMAGE_CLASSIFICATION_API_KEY 로도 설정 가능)">
                  <SecretInput value={icApiKey} onChange={setIcApiKey} placeholder="미설정(생성 LLM 키 사용)" />
                </Row>
                <Row name="분류 카테고리" desc="쉼표로 구분한 분류 후보. 모델 출력이 목록에 없으면 other 로 정규화됩니다.">
                  <Input value={icCategories} onChange={(e) => setIcCategories(e.target.value)} placeholder="chart,table,diagram,photo,screenshot,formula,logo,other" />
                </Row>
                <Row name="최소 이미지 크기(px)" desc="이 픽셀(긴 변) 미만 이미지는 아이콘/장식으로 보고 분류에서 제외. 기본 64.">
                  <Input type="number" value={icMinPixels} onChange={(e) => setIcMinPixels(e.target.value)} />
                </Row>
                <Row name="문서당 최대 이미지" desc="문서 1건당 분류할 최대 이미지 수(비용·지연 가드). 기본 50.">
                  <Input type="number" value={icMaxImages} onChange={(e) => setIcMaxImages(e.target.value)} />
                </Row>
                <Row name="작은 이미지 최소 크기(KB)" desc="URL에서 이미지 가져오기의 '작은 이미지 제거' 시, 이 크기(KB) 미만 이미지는 아이콘·트래킹 픽셀로 보고 제외. 기본 10.">
                  <Input type="number" value={icSmallImageMinKb} onChange={(e) => setIcSmallImageMinKb(e.target.value)} />
                </Row>
                <Row name="타임아웃(초)" desc="비전 서버 호출 타임아웃. 기본 60.">
                  <Input type="number" value={icTimeout} onChange={(e) => setIcTimeout(e.target.value)} />
                </Row>
                <Row name="인증 헤더" desc="인증 헤더 이름. 기본 Authorization.">
                  <Input value={icAuthHeader} onChange={(e) => setIcAuthHeader(e.target.value)} />
                </Row>
                <Row name="인증 스킴" desc="헤더 값 접두. 기본 Bearer. 접두가 없으면 비웁니다.">
                  <Input value={icAuthScheme} onChange={(e) => setIcAuthScheme(e.target.value)} placeholder="(비움 가능)" />
                </Row>
              </SettingsTable>
              <div className="mt-3">
                <Button variant="outline" size="sm" onClick={handleTestImageClassification} disabled={icTesting}>
                  <Plug className="size-4" />
                  {icTesting ? "테스트 중..." : "연결 테스트"}
                </Button>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                <b>현재 입력값</b>으로 작은 합성 이미지 1장을 분류해 비전 엔드포인트 응답을 확인합니다(저장 전 검증). 값을 비우면 저장된 설정/생성 LLM 으로 폴백합니다.
              </p>
            </TabsContent>

            {/* 검출(자동 bbox) */}
            <TabsContent value="detection" className="mt-4">
              <SaveBar desc="이미지 라벨링 편집기의 '자동 인식'이 호출하는 외부 검출 서버(PaddleOCR) 설정입니다. 비활성 시 자동 인식은 503 으로 안내됩니다." />
              <SettingsTable>
                <Row name="사용" desc="자동 bbox 인식 기능 활성화 여부.">
                  <Select value={detEnabled} onValueChange={setDetEnabled}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="false">사용 안 함</SelectItem>
                      <SelectItem value="true">사용</SelectItem>
                    </SelectContent>
                  </Select>
                </Row>
                <Row name="서버 URL" desc="검출 서버 베이스 URL. 예) http://192.0.2.50:8082">
                  <div className="flex flex-col gap-1.5">
                    <ServiceEndpointPicker kind="detection" value={detServerUrl} className="h-9 w-full text-sm" onPick={(svc) => { if (svc) setDetServerUrl(svc.url) }} />
                    <Input value={detServerUrl} onChange={(e) => setDetServerUrl(e.target.value)} placeholder="http://localhost:8082" />
                  </div>
                </Row>
                <Row name="API 키" desc="검출 서버 인증 키. 기본은 가려서(••••) 표시. (환경변수 ARGUS_DETECTION_API_KEY 로도 설정 가능)">
                  <SecretInput value={detApiKey} onChange={setDetApiKey} placeholder="미설정" />
                </Row>
                <Row name="언어" desc="PaddleOCR 기본 언어. 예) korean, en. 요청에서 override 가능.">
                  <Input value={detLang} onChange={(e) => setDetLang(e.target.value)} placeholder="korean" />
                </Row>
                <Row name="최소 신뢰도" desc="이 점수 미만 박스는 버립니다. 0~1, 기본 0.5.">
                  <Input type="number" step="0.05" value={detMinScore} onChange={(e) => setDetMinScore(e.target.value)} />
                </Row>
                <Row name="타임아웃(초)" desc="검출 서버 호출 타임아웃. 기본 60.">
                  <Input type="number" value={detTimeout} onChange={(e) => setDetTimeout(e.target.value)} />
                </Row>
                <Row name="인증 헤더" desc="인증 헤더 이름. 기본 Authorization.">
                  <Input value={detAuthHeader} onChange={(e) => setDetAuthHeader(e.target.value)} />
                </Row>
                <Row name="인증 스킴" desc="헤더 값 접두. 기본 Bearer. 접두가 없으면 비웁니다.">
                  <Input value={detAuthScheme} onChange={(e) => setDetAuthScheme(e.target.value)} placeholder="(비움 가능)" />
                </Row>
              </SettingsTable>
            </TabsContent>

            {/* 인증 */}
            <TabsContent value="auth" className="mt-4">
              <SaveBar desc="사용자 인증 방식입니다. 로컬(내장 JWT) 또는 Keycloak(OIDC) 중 선택합니다." />
              <div className="mb-3 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200">
                <Database className="mt-0.5 size-4 shrink-0" />
                <p>
                  인증 설정을 잘못 저장하면 <b>다시 로그인하지 못할 수 있습니다.</b> 저장 전에 반드시 <b>연결 테스트</b>로
                  Keycloak 연결을 확인하세요.
                </p>
              </div>
              <SettingsTable>
                <Row name="인증 방식" desc={
                  <Opts items={[
                    ["local", "서버 내장 JWT 인증 — 외부 의존성 없음"],
                    ["keycloak", "Keycloak OIDC 연동 — 아래 연결 정보 필요"],
                  ]} />
                }>
                  <Select value={authType} onValueChange={setAuthType}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="local">로컬 (내장 JWT)</SelectItem>
                      <SelectItem value="keycloak">Keycloak (OIDC)</SelectItem>
                    </SelectContent>
                  </Select>
                </Row>
                <Row name="로컬 JWT 만료(분)" desc="local 인증 시 발급 토큰 유효 시간. 기본 480(8시간). 변경은 이후 새 로그인부터 적용.">
                  <Input type="number" value={jwtExpireMinutes} onChange={(e) => setJwtExpireMinutes(e.target.value)} />
                </Row>
                {authType === "keycloak" && (
                  <>
                    <Row name="서버 URL" desc="Keycloak 서버 베이스 URL. 예) http://keycloak:8180">
                      <Input value={kcServerUrl} onChange={(e) => setKcServerUrl(e.target.value)} placeholder="http://localhost:8180" />
                    </Row>
                    <Row name="Realm" desc="인증에 사용할 Keycloak Realm 이름.">
                      <Input value={kcRealm} onChange={(e) => setKcRealm(e.target.value)} placeholder="argus" />
                    </Row>
                    <Row name="Client ID" desc="이 애플리케이션의 Keycloak 클라이언트 ID.">
                      <Input value={kcClientId} onChange={(e) => setKcClientId(e.target.value)} placeholder="argus-client" />
                    </Row>
                    <Row name="Client Secret" desc="confidential 클라이언트 시크릿. 기본은 가려서(••••) 표시되며 eye 아이콘으로 확인할 수 있습니다.">
                      <SecretInput value={kcClientSecret} onChange={setKcClientSecret} placeholder="미설정" />
                    </Row>
                    <Row name="Admin 역할" desc="관리자 권한으로 매핑할 Keycloak 역할 이름.">
                      <Input value={kcAdminRole} onChange={(e) => setKcAdminRole(e.target.value)} placeholder="argus-admin" />
                    </Row>
                    <Row name="Superuser 역할" desc="슈퍼유저 권한으로 매핑할 역할 이름.">
                      <Input value={kcSuperuserRole} onChange={(e) => setKcSuperuserRole(e.target.value)} placeholder="argus-superuser" />
                    </Row>
                    <Row name="User 역할" desc="일반 사용자 권한으로 매핑할 역할 이름.">
                      <Input value={kcUserRole} onChange={(e) => setKcUserRole(e.target.value)} placeholder="argus-user" />
                    </Row>
                  </>
                )}
              </SettingsTable>
              <div className="mt-3">
                <Button variant="outline" size="sm" onClick={handleTestAuth} disabled={authTesting}>
                  <Plug className="size-4" />
                  {authTesting ? "테스트 중..." : "연결 테스트"}
                </Button>
              </div>
            </TabsContent>

            {/* CORS */}
            <TabsContent value="cors" className="mt-4">
              <SaveBar desc="브라우저에서 이 API 를 호출할 수 있는 출처(Origin) 허용 목록입니다." />
              <SettingsTable>
                <Row name="허용 Origin" desc="쉼표로 구분합니다. * 는 전체 허용 — 운영 환경에서는 구체적인 도메인 지정을 권장합니다.">
                  <Input value={corsOrigins} onChange={(e) => setCorsOrigins(e.target.value)} placeholder="*" />
                </Row>
              </SettingsTable>
            </TabsContent>

            {/* 기타 — 미리보기 / 관측성 */}
            <TabsContent value="etc" className="mt-4">
              <SaveBar desc="미리보기·관측성 관련 기타 한도 설정입니다." />
              <SettingsTable>
                <Row name="미리보기 최대 행수" desc="S3 브라우저의 parquet/xlsx 미리보기에서 읽을 최대 행 수. 기본 1000.">
                  <Input type="number" value={previewMaxRows} onChange={(e) => setPreviewMaxRows(e.target.value)} />
                </Row>
                <Row name="트레이스 답변 길이(자)" desc="질의 트레이스에 저장할 답변 최대 길이. 기본 2000.">
                  <Input type="number" value={answerLimit} onChange={(e) => setAnswerLimit(e.target.value)} />
                </Row>
              </SettingsTable>

              <p className="mb-2 mt-6 text-sm font-medium text-black">
                표시 설정{" "}
                <span className="text-xs font-normal text-muted-foreground">(이 브라우저에만 저장 · 즉시 적용 · 위 저장 버튼과 무관)</span>
              </p>
              <SettingsTable>
                <Row
                  name="HWP 뷰어 방식"
                  desc="'문서 전체 보기'의 HWP/HWPX 좌측 원본 렌더 방식. image=이미지로 빠르게 표시하고 매칭 페이지를 강조(권장), svg=매칭 셀을 정밀 색칠(복잡한 표 문서는 느릴 수 있음)."
                >
                  <Select
                    value={hwpMode}
                    onValueChange={(v) => {
                      const m = v as HwpViewerMode
                      setHwpMode(m)
                      setHwpViewerMode(m)
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="image">이미지 — 빠름, 매칭 페이지 강조 (권장)</SelectItem>
                      <SelectItem value="svg">SVG — 매칭 셀 정밀 색칠</SelectItem>
                    </SelectContent>
                  </Select>
                </Row>
              </SettingsTable>
            </TabsContent>

            {/* 시스템 (읽기 전용) */}
            <TabsContent value="system" className="mt-4">
              <SaveBar readOnly desc="배포/환경 파일에서 관리되는 항목으로, 화면에서는 조회만 가능합니다." />
              <SettingsTable nameHeader="항목">
                <Row name="로컬(인프로세스) 워커" desc="API 프로세스가 색인 워커를 동거 실행할지 여부. 끄면 원격/분리 워커(에이전트 배포)가 색인을 담당합니다. config.yml 의 ingestion.local_worker_enabled 로 관리합니다.">
                  <ReadOnlyText value={data.ingestion.local_worker_enabled ? "활성" : "비활성"} />
                </Row>
              </SettingsTable>
            </TabsContent>
          </UrlTabs>
        )}
      </div>
    </>
  )
}

// 1설정=1행 테이블: 설정 | 값 | 설명 — 지식베이스 상세 메타데이터 표와 동일한 스타일
// (border-collapse 테두리 셀 + key 셀 bg-muted/60 + text-black).
function SettingsTable({ children, nameHeader }: { children: React.ReactNode; nameHeader?: string }) {
  return (
    <table className="w-full table-fixed border-collapse text-sm text-black">
      <colgroup>
        <col className="w-[180px]" />
        <col className="w-[300px]" />
        <col />
      </colgroup>
      <thead>
        <tr>
          <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">
            {nameHeader ?? "설정"}
          </th>
          <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">값</th>
          <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">설명</th>
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  )
}

function Row({
  name,
  desc,
  children,
  highlight,
  prev,
  prevSecret,
  onRevert,
}: {
  name: string
  desc: React.ReactNode
  children: React.ReactNode
  // true 면 라벨을 빨간색 + * 로 강조 — 기반 환경(Databricks 등) 전환 시 확인·설정이 필요한 항목 표시용.
  highlight?: boolean
  // 자동 변경 전 값. 지정되면 입력 아래에 "이전값: … · 되돌리기" 를 표시한다.
  prev?: string
  // 시크릿 필드면 이전값을 평문으로 노출하지 않고 마스킹해 표시한다.
  prevSecret?: boolean
  onRevert?: () => void
}) {
  return (
    <tr>
      <th
        className={`border bg-muted/60 px-3 py-2 text-left align-middle font-medium ${
          highlight ? "text-red-600 dark:text-red-400" : "text-black"
        }`}
      >
        {name}
        {highlight && (
          <span className="ml-0.5" title="Databricks 기반 환경에서 확인·설정이 필요한 항목">
            *
          </span>
        )}
      </th>
      <td className="border px-3 py-2 align-middle text-black">
        {children}
        {prev !== undefined && (
          <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
            <span>
              이전값:{" "}
              <span className="font-mono">
                {prevSecret ? (prev ? "••••(설정됨)" : "(비어 있음)") : prev || "(비어 있음)"}
              </span>
            </span>
            {onRevert && (
              <button
                type="button"
                onClick={onRevert}
                className="text-primary underline hover:no-underline"
              >
                되돌리기
              </button>
            )}
          </div>
        )}
      </td>
      <td className="border px-3 py-2 align-middle text-muted-foreground">{desc}</td>
    </tr>
  )
}

// 옵션별 상세 설명 — key 강조 + 설명
function Opts({ items }: { items: [string, string][] }) {
  return (
    <ul className="space-y-1">
      {items.map(([k, v]) => (
        <li key={k} className="leading-snug">
          <code className="rounded bg-muted px-1 py-0.5 text-sm font-medium text-foreground">{k}</code>
          <span className="ml-1">{v}</span>
        </li>
      ))}
    </ul>
  )
}

function ReadOnlyText({ value }: { value: string }) {
  return <span className="text-sm font-medium">{value}</span>
}

// 비밀값 입력 — eye 아이콘으로 표시/숨김 토글(타이핑한 값 확인용)
function SecretInput({
  value,
  onChange,
  placeholder,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <Input
        type={show ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="pr-9"
      />
      <button
        type="button"
        onClick={() => setShow((s) => !s)}
        aria-label={show ? "숨기기" : "보기"}
        className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
      >
        {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  )
}
