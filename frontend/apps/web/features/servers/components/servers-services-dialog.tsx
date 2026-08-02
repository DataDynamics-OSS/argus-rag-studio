// 서비스/배포 다이얼로그 — 통합 배포 API(/api/v1/deploy)로 호스트에 Docker/systemd 배포.
// 배포 폼만 제공(서비스 목록은 상세 페이지의 "서비스/배포" 탭 그리드에서 확인).
"use client"

import { useEffect, useMemo, useState } from "react"
import { Loader2, Rocket } from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import { Checkbox } from "@workspace/ui/components/checkbox"
import { Input } from "@workspace/ui/components/input"
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
import { Table, TableBody, TableCell, TableRow } from "@workspace/ui/components/table"

import { deployStream, listModelCatalog, type CatalogModel, type DeployTarget, type ServiceKind } from "@/features/deploy/api"
import { PrivilegeBadge } from "@/features/deploy/components/privilege-badge"
import {
  DeployProgress,
  reduceEvent,
  type ProgressState,
} from "@/features/deploy/components/deploy-progress"

import { type Server } from "../data/schema"

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  currentRow: Server
}

const KINDS: { value: ServiceKind; label: string; gpu: boolean; scalable: boolean }[] = [
  { value: "worker", label: "워커 (worker)", gpu: false, scalable: true },
  { value: "embedding", label: "임베딩 서버 (embedding)", gpu: true, scalable: false },
  { value: "reranker", label: "리랭커 서버 (reranker)", gpu: true, scalable: false },
  { value: "detection", label: "검출 서버 (detection)", gpu: true, scalable: false },
  { value: "hwp_render", label: "HWP 렌더 서버 (hwp_render)", gpu: false, scalable: false },
  // VLM — 이미지 분류/내용 주입용 비전 LLM(vLLM, GPU 필수). 배포 시 전역 설정
  // (image_classification.server_url)이 새 서버로 연결된다. 모델 변경은 env VLLM_ARGS.
  { value: "vlm", label: "VLM 서버 (vlm)", gpu: true, scalable: false },
]

/** 배포 폼의 한 줄(라벨 | 입력 | 설명 — 설명은 입력값 오른쪽 별도 컬럼). */
function Field({
  label,
  hint,
  children,
}: {
  label: React.ReactNode
  hint?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <TableRow>
      <TableCell className="w-[150px] align-top whitespace-normal pt-3 text-sm font-medium text-black">
        {label}
      </TableCell>
      <TableCell className="w-[240px] align-top">{children}</TableCell>
      <TableCell className="align-top whitespace-normal break-words pt-3 text-xs leading-relaxed text-black">
        {hint}
      </TableCell>
    </TableRow>
  )
}

export function ServersServicesDialog({ open, onOpenChange, currentRow }: Props) {
  const isRegistered = currentRow.status === "REGISTERED"

  const [method, setMethod] = useState<"docker" | "systemd">("docker")
  const [kind, setKind] = useState<ServiceKind>("embedding")
  const [replicas, setReplicas] = useState("1")
  const [variantChoice, setVariantChoice] = useState("auto") // auto | cpu | gpu
  const [force, setForce] = useState(false)
  const [version, setVersion] = useState("")
  const [image, setImage] = useState("")
  // 모델 레지스트리(보유 여부 포함) — vlm 은 단일 선택(env.VLM_MODEL),
  // embedding/reranker 는 다중 선택 + 기본 지정(env.MODEL_NAMES/DEFAULT_MODEL).
  const [catalogModels, setCatalogModels] = useState<CatalogModel[]>([])
  const [vlmModel, setVlmModel] = useState("qwen2-vl-7b")
  const [selModels, setSelModels] = useState<string[]>([])
  const [defaultModel, setDefaultModel] = useState("")
  const [allowOnline, setAllowOnline] = useState(false)
  const [deploying, setDeploying] = useState(false)
  // 진행(progress) — 배포 중/완료 시 폼 대신 단계 진행 표시
  const [progress, setProgress] = useState<ProgressState | null>(null)
  const [finished, setFinished] = useState<"done" | "error" | null>(null)

  // 닫으면 진행 상태 초기화(다음에 폼부터).
  useEffect(() => {
    if (!open) {
      setProgress(null)
      setFinished(null)
    }
  }, [open])

  // 모델 레지스트리(보유 여부 포함) — 열릴 때 1회 로드. 비활성 모델은 선택 제외.
  useEffect(() => {
    if (open)
      listModelCatalog()
        .then((r) => setCatalogModels(r.models.filter((m) => m.enabled !== false)))
        .catch(() => {})
  }, [open])

  const vlmModels = useMemo(() => catalogModels.filter((m) => m.kind === "vlm"), [catalogModels])
  const kindModels = useMemo(
    () => catalogModels.filter((m) => m.kind === kind),
    [catalogModels, kind]
  )
  // kind 변경 시 선택 초기화(모델 목록이 kind 별로 다름).
  useEffect(() => {
    setSelModels([])
    setDefaultModel("")
  }, [kind])

  function toggleModel(name: string) {
    setSelModels((prev) => {
      const next = prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]
      // 기본 모델이 선택에서 빠지면 첫 항목으로 재지정.
      setDefaultModel((d) => (next.includes(d) ? d : (next[0] ?? "")))
      return next
    })
  }

  // 네트워킹(docker)
  const [hostPort, setHostPort] = useState("") // 호스트 포트 오버라이드(docker, 서버형)
  const [network, setNetwork] = useState("bridge") // bridge | host | custom
  const [networkCustom, setNetworkCustom] = useState("")
  const [extraHostsText, setExtraHostsText] = useState("")
  const [dbUrl, setDbUrl] = useState("")
  const [osEndpoint, setOsEndpoint] = useState("")
  // systemd(worker)
  const [workingDirectory, setWorkingDirectory] = useState("")
  const [pythonPath, setPythonPath] = useState("")

  // systemd 는 worker 만.
  useEffect(() => {
    if (method === "systemd" && kind !== "worker") setKind("worker")
  }, [method, kind])

  const kindsForMethod = useMemo(
    () => (method === "systemd" ? KINDS.filter((k) => k.value === "worker") : KINDS),
    [method]
  )
  const meta = KINDS.find((k) => k.value === kind) ?? KINDS[0]!
  const target: DeployTarget = { type: "agent_host", hostname: currentRow.hostname, method }

  async function handleDeploy() {
    const n = meta.scalable ? Number(replicas) : 1
    if (meta.scalable && (!Number.isInteger(n) || n < 1 || n > 32)) {
      toast.error("워커 수는 1~32 사이여야 합니다.")
      return
    }
    if (method === "systemd" && !workingDirectory.trim()) {
      toast.error("systemd 워커 배포에는 작업 디렉터리가 필요합니다.")
      return
    }
    const useGpu = method === "docker" && meta.gpu && variantChoice === "gpu"
    const env: Record<string, string> = {}
    if (kind === "vlm" && vlmModel) env.VLM_MODEL = vlmModel
    if ((kind === "embedding" || kind === "reranker") && selModels.length) {
      env.MODEL_NAMES = selModels.join(",")
      env.DEFAULT_MODEL = defaultModel || selModels[0]!
    }
    if ((kind === "vlm" || kind === "embedding" || kind === "reranker") && allowOnline)
      env.ALLOW_ONLINE_MODEL = "1"
    if (method === "systemd") {
      env.working_directory = workingDirectory.trim()
      if (pythonPath.trim()) env.python_path = pythonPath.trim()
      if (dbUrl.trim()) env.ARGUS_DB_URL = dbUrl.trim()
      if (osEndpoint.trim()) env.ARGUS_OS_ENDPOINT = osEndpoint.trim()
    }
    const hp = Number(hostPort)
    if (hostPort.trim() && (!Number.isInteger(hp) || hp < 1 || hp > 65535)) {
      toast.error("호스트 포트는 1~65535 사이여야 합니다.")
      return
    }
    const resolvedNetwork =
      network === "bridge" ? undefined : network === "custom" ? networkCustom.trim() || undefined : network
    const extraHosts = extraHostsText
      .split(/[\n,\s]+/)
      .map((l) => l.trim())
      .filter((l) => l.includes(":"))
    const specObj = {
      kind,
      replicas: n,
      variant: useGpu ? "auto" : variantChoice,
      gpu: useGpu,
      version: version.trim() || undefined,
      image: image.trim() || undefined,
      env,
      ...(method === "docker"
        ? {
            network: resolvedNetwork,
            extra_hosts: extraHosts.length ? extraHosts : undefined,
            db_url: kind === "worker" && dbUrl.trim() ? dbUrl.trim() : undefined,
            os_endpoint: kind === "worker" && osEndpoint.trim() ? osEndpoint.trim() : undefined,
            host_port: kind !== "worker" && hostPort.trim() ? hp : undefined,
          }
        : {}),
    }

    setProgress({})
    setFinished(null)
    setDeploying(true)
    let serviceName: string | null = null
    let appliedKeys: string[] = []
    let errored = false
    try {
      await deployStream(specObj, target, (e) => {
        setProgress((prev) => reduceEvent(prev ?? {}, e))
        if (e.phase === "done" && e.service) {
          serviceName = e.service.name
          appliedKeys = Object.keys(e.applied_settings ?? {})
        }
        if (e.phase === "error") errored = true
      })
      if (errored) {
        setFinished("error")
      } else {
        toast.success(
          `${serviceName ?? "서비스"} 배포됨${appliedKeys.length ? ` · 설정 주입: ${appliedKeys.join(", ")}` : ""}`
        )
        setFinished("done")
      }
    } catch (err) {
      setProgress((prev) => ({ ...(prev ?? {}), _error: err instanceof Error ? err.message : "배포 실패" }))
      setFinished("error")
    } finally {
      setDeploying(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[950px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            서비스 / 배포 <PrivilegeBadge runtime={method} />
          </DialogTitle>
          <DialogDescription>
            {currentRow.hostname} ({currentRow.ipAddress})
          </DialogDescription>
        </DialogHeader>

        {progress ? (
          <div className="rounded-md border p-4">
            <DeployProgress state={progress} />
          </div>
        ) : (
        <div className="rounded-md border">
          <div className="flex items-center gap-2 border-b bg-muted/40 px-3 py-2 text-sm font-medium">
            <Rocket className="size-4" /> 배포
            <Badge variant="outline" className="ml-auto font-normal">
              arch: {currentRow.arch ?? "?"}
            </Badge>
          </div>
          {!isRegistered && (
            <p className="px-3 py-2 text-xs text-destructive">
              등록(REGISTERED)된 서버에만 배포할 수 있습니다. 먼저 서버를 등록하세요.
            </p>
          )}

          <Table className="table-fixed">
            <TableBody>
              <Field
                label="방식(method)"
                hint="Docker 컨테이너 또는 systemd 유닛으로 배포. systemd 는 worker 만 가능하며 호스트에 backend 코드가 설치돼 있어야 합니다."
              >
                <Select value={method} onValueChange={(v) => setMethod(v as "docker" | "systemd")} disabled={!isRegistered}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="docker">Docker 컨테이너</SelectItem>
                    <SelectItem value="systemd">systemd (worker, root)</SelectItem>
                  </SelectContent>
                </Select>
              </Field>

              <Field
                label="배포 대상(kind)"
                hint="배포할 서비스 종류 — worker(색인 워커), embedding/reranker/detection(추론 서버), hwp_render(HWP 렌더)."
              >
                <Select value={kind} onValueChange={(v) => setKind(v as ServiceKind)} disabled={!isRegistered || method === "systemd"}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {kindsForMethod.map((k) => (
                      <SelectItem key={k.value} value={k.value}>
                        {k.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>

              {kind === "vlm" && (
                <Field
                  label="VLM 모델"
                  hint="모델 관리에 등록된 VLM 중에서 선택합니다. 목록에 없는 모델은 관리 > 모델 관리에서 등록하거나, 고급으로 env VLLM_ARGS 에 서빙 인자를 직접 지정하세요. 배포 시 전역 설정(server_url·model)이 이 서버·모델로 연결됩니다."
                >
                  <Select value={vlmModel} onValueChange={setVlmModel} disabled={!isRegistered}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {vlmModels.length ? (
                        vlmModels.map((m) => (
                          <SelectItem key={m.name} value={m.name}>
                            {m.name} — {m.note} {m.available ? "· 보유" : "· 미보유"}
                          </SelectItem>
                        ))
                      ) : (
                        <SelectItem value="qwen2-vl-7b">qwen2-vl-7b — 기본</SelectItem>
                      )}
                    </SelectContent>
                  </Select>
                </Field>
              )}

              {(kind === "embedding" || kind === "reranker") && (
                <Field
                  label="서빙 모델(선택)"
                  hint="모델 관리에 등록된 모델 중 이 서버가 서빙할 것을 고릅니다. 보유(반입 완료) 모델은 배포 시 서버 볼륨에 자동 설치되어 오프라인 서빙됩니다. 미보유 모델이 있으면 배포가 거부됩니다(온라인 허용 제외). 아무것도 선택하지 않으면 서버 자체 설정의 기본 모델 세트로 뜹니다."
                >
                  <div className="flex flex-col gap-1.5 rounded-md border p-2">
                    {kindModels.length === 0 ? (
                      <p className="text-sm text-muted-foreground">모델 관리에 등록된 {kind === "embedding" ? "임베딩" : "리랭커"} 모델이 없습니다.</p>
                    ) : (
                      kindModels.map((m) => (
                        <label key={m.name} className="flex cursor-pointer items-center gap-2 text-sm">
                          <Checkbox
                            checked={selModels.includes(m.name)}
                            onCheckedChange={() => toggleModel(m.name)}
                            disabled={!isRegistered}
                          />
                          <span className="flex-1 truncate" title={m.repo}>{m.name}</span>
                          <Badge
                            variant="outline"
                            className={m.available
                              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600"
                              : "border-amber-500/30 bg-amber-500/10 text-amber-600"}
                          >
                            {m.available ? "보유" : "미보유"}
                          </Badge>
                        </label>
                      ))
                    )}
                  </div>
                </Field>
              )}

              {(kind === "embedding" || kind === "reranker") && selModels.length > 1 && (
                <Field
                  label="기본 모델"
                  hint="요청에서 모델을 지정하지 않았을 때 사용할 모델(선택한 것 중 하나)."
                >
                  <Select value={defaultModel || selModels[0]} onValueChange={setDefaultModel} disabled={!isRegistered}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {selModels.map((n) => (
                        <SelectItem key={n} value={n}>{n}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
              )}

              {(kind === "vlm" || ((kind === "embedding" || kind === "reranker") && selModels.length > 0)) && (
                <Field
                  label="온라인 다운로드 허용"
                  hint="모델 저장소(argus-models)에 미보유인 모델을 HF 에서 직접 내려받도록 허용합니다(개발망 전용 — 에어갭에서는 pack_model 로 반입하세요). 꺼져 있으면 미보유 모델 배포는 거부됩니다."
                >
                  <Select value={allowOnline ? "yes" : "no"} onValueChange={(v) => setAllowOnline(v === "yes")} disabled={!isRegistered}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="no">허용 안 함(에어갭 기본)</SelectItem>
                      <SelectItem value="yes">허용(개발망)</SelectItem>
                    </SelectContent>
                  </Select>
                </Field>
              )}

              <Field
                label="버전(태그, 선택)"
                hint="이미지/유닛 태그. 비우면 레지스트리 기본 태그(latest)를 사용합니다."
              >
                <Input placeholder="레지스트리 기본값 사용" value={version} onChange={(e) => setVersion(e.target.value)} disabled={!isRegistered} />
              </Field>

              {meta.scalable && (
                <Field
                  label="개수(replicas)"
                  hint="동시에 띄울 워커 수(1~32). 잡은 SKIP LOCKED 큐로 분배되어 중복 없이 병렬 처리됩니다."
                >
                  <Input inputMode="numeric" value={replicas} onChange={(e) => setReplicas(e.target.value)} disabled={!isRegistered} />
                </Field>
              )}

              {method === "docker" && (
                <Field
                  label="이미지 override(선택)"
                  hint="기본 이미지 대신 사용할 전체 경로. 사내 레지스트리나 호스트 로컬 빌드 태그를 지정합니다."
                >
                  <Input placeholder="예: reg.local/argus-...:tag" value={image} onChange={(e) => setImage(e.target.value)} disabled={!isRegistered} />
                </Field>
              )}

              {method === "docker" && kind !== "worker" && (
                <Field
                  label="호스트 포트(선택)"
                  hint="기본 포트가 호스트에서 점유된 경우 대체 포트. 컨테이너 내부 포트는 그대로 두고 매핑·설정 주입 주소만 바뀝니다."
                >
                  <Input inputMode="numeric" placeholder="kind 기본 포트 사용" value={hostPort} onChange={(e) => setHostPort(e.target.value)} disabled={!isRegistered} />
                </Field>
              )}

              {method === "systemd" && (
                <>
                  <Field label="작업 디렉터리 *" hint="systemd 워커가 실행될 호스트의 backend 코드 경로(필수).">
                    <Input placeholder="/opt/argus-rag-studio/backend" value={workingDirectory} onChange={(e) => setWorkingDirectory(e.target.value)} disabled={!isRegistered} className="font-mono text-xs" />
                  </Field>
                  <Field label="python 경로(선택)" hint="워커 실행에 쓸 venv python 경로. 비우면 'python'.">
                    <Input placeholder="/opt/.../.venv/bin/python" value={pythonPath} onChange={(e) => setPythonPath(e.target.value)} disabled={!isRegistered} className="font-mono text-xs" />
                  </Field>
                </>
              )}

              {method === "docker" && (
                <Field
                  label="네트워크"
                  hint="컨테이너 네트워크. bridge=격리(컨테이너 localhost ≠ 호스트 → DB·MinIO override 필요), host=호스트 네트워크 공유."
                >
                  <Select value={network} onValueChange={setNetwork} disabled={!isRegistered}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="bridge">기본 (bridge)</SelectItem>
                      <SelectItem value="host">host (호스트 네트워크)</SelectItem>
                      <SelectItem value="custom">사용자 지정…</SelectItem>
                    </SelectContent>
                  </Select>
                </Field>
              )}
              {method === "docker" && network === "custom" && (
                <Field label="네트워크 이름" hint="사용할 사용자 지정 docker 네트워크 이름.">
                  <Input placeholder="예: argus-net" value={networkCustom} onChange={(e) => setNetworkCustom(e.target.value)} disabled={!isRegistered} />
                </Field>
              )}
              {method === "docker" && (
                <Field
                  label="extra hosts"
                  hint="컨테이너 /etc/hosts 에 추가할 항목(--add-host). 'name:ip' 형식, 쉼표/공백 구분."
                >
                  <Input placeholder="studio-db:192.0.2.10" value={extraHostsText} onChange={(e) => setExtraHostsText(e.target.value)} disabled={!isRegistered} className="font-mono text-xs" />
                </Field>
              )}

              {kind === "worker" && (
                <>
                  <Field
                    label="DB URL override(선택)"
                    hint="워커가 접속할 DB 주소. bridge 네트워크에선 localhost 대신 라우팅 가능한 주소(예: 192.0.2.50)를 입력합니다."
                  >
                    <Input placeholder="postgresql+asyncpg://argus:***@192.0.2.10:5432/argus_rag_studio" value={dbUrl} onChange={(e) => setDbUrl(e.target.value)} disabled={!isRegistered} className="font-mono text-xs" />
                  </Field>
                  <Field
                    label="MinIO 엔드포인트 override(선택)"
                    hint="워커가 원본 문서를 읽을 MinIO(S3) 주소. bridge 에선 라우팅 가능한 주소를 입력합니다."
                  >
                    <Input placeholder="http://192.0.2.10:9000" value={osEndpoint} onChange={(e) => setOsEndpoint(e.target.value)} disabled={!isRegistered} className="font-mono text-xs" />
                  </Field>
                </>
              )}

              {method === "docker" && meta.gpu && (
                <Field
                  label="실행 변형"
                  hint="GPU 사용 방식. 자동=호스트 arch로 결정(amd64=gpu(onnx), arm64=gpu-torch), CPU=CPU 전용, GPU=GPU 강제."
                >
                  <div className="flex items-center gap-3">
                    <Select value={variantChoice} onValueChange={setVariantChoice} disabled={!isRegistered}>
                      <SelectTrigger className="w-40">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="auto">자동 (호스트 기준)</SelectItem>
                        <SelectItem value="cpu">CPU</SelectItem>
                        <SelectItem value="gpu">GPU</SelectItem>
                      </SelectContent>
                    </Select>
                    {variantChoice === "gpu" && (
                      <label className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Checkbox checked={force} onCheckedChange={(v) => setForce(v === true)} disabled={!isRegistered} />
                        GPU 미탑재여도 강제
                      </label>
                    )}
                  </div>
                </Field>
              )}

              {method === "systemd" && (
                <Field
                  label="실행 변형"
                  hint="systemd 워커는 호스트의 backend 코드를 직접 실행하므로 이미지 변형(GPU/CPU) 개념이 없습니다. 호스트 환경 그대로 동작합니다."
                >
                  <span className="text-sm text-black">호스트 바이너리 (변형 없음)</span>
                </Field>
              )}
            </TableBody>
          </Table>
        </div>
        )}

        <DialogFooter>
          {progress ? (
            finished ? (
              <>
                {finished === "error" && (
                  <Button variant="outline" onClick={() => { setProgress(null); setFinished(null) }}>
                    다시 배포
                  </Button>
                )}
                <Button onClick={() => onOpenChange(false)}>닫기</Button>
              </>
            ) : (
              <Button disabled>
                <Loader2 className="size-4 animate-spin" /> 배포 중…
              </Button>
            )
          ) : (
            <Button onClick={handleDeploy} disabled={!isRegistered || deploying}>
              {deploying ? <Loader2 className="size-4 animate-spin" /> : <Rocket className="size-4" />}
              배포
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
