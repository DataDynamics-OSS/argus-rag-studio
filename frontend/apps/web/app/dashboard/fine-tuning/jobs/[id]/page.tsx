// 학습 작업 상세 — 상태·진행·설정·지표·아티팩트 + 실행 방법 + 취소/삭제.
"use client"

import { useCallback, useEffect, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import Link from "next/link"
import { ArrowLeft, Ban, Copy, PackageCheck, Trash2 } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Badge } from "@workspace/ui/components/badge"
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard-header"
import { formatDateTime } from "@/lib/format"
import { useAuth } from "@/features/auth"
import { cancelJob, deleteJob, getJob, registerFromJob } from "@/features/finetune/api"
import type { FtJob } from "@/features/finetune/data/schema"
import { CodeViewer } from "@/components/code-viewer"
import { JobStatusBadge } from "@/features/finetune/job-status"

export default function FtJobDetailPage() {
  const params = useParams<{ id: string }>()
  // 외부 노출은 작업 UUID. 내부 작업은 해석된 job.id(정수 PK)를 쓴다.
  const uuid = String(params.id)
  const router = useRouter()
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser

  const [job, setJob] = useState<FtJob | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setJob(await getJob(uuid))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [uuid])

  useEffect(() => {
    if (uuid && uuid !== "undefined") refresh()
  }, [uuid, refresh])

  async function onCancel() {
    if (!job) return
    try {
      setJob(await cancelJob(job.id))
      toast.success("작업을 취소했습니다.")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "취소 실패")
    }
  }

  async function onDelete() {
    if (!job) return
    try {
      await deleteJob(job.id)
      toast.success("작업을 삭제했습니다.")
      router.push("/dashboard/fine-tuning/jobs")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "삭제 실패")
    }
  }

  async function onRegister() {
    if (!job) return
    try {
      const m = await registerFromJob(job.id)
      toast.success("모델로 등록했습니다.")
      router.push(`/dashboard/fine-tuning/models/${m.model_id}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "모델 등록 실패")
    }
  }

  async function copyToken(token: string) {
    try {
      await navigator.clipboard.writeText(token)
      toast.success("콜백 토큰을 복사했습니다.")
    } catch {
      toast.error("복사에 실패했습니다.")
    }
  }

  const terminal = job ? ["succeeded", "failed", "canceled"].includes(job.status) : false
  const cfg = job?.config ?? {}
  const apiBase = typeof window !== "undefined" ? window.location.origin : "https://<argus-host>"
  const runCmd = job
    ? `# 0) 환경변수 (한 번만)\n` +
      `export ARGUS_BASE="${apiBase}"\n` +
      `export ARGUS_TOKEN="${job.callback_token ?? "<이 잡의 콜백 토큰>"}"   # 이 잡 전용 콜백 토큰\n` +
      `\n` +
      `# 1) 데이터셋 내보내기 (train/valid)\n` +
      `mkdir -p dataset\n` +
      `curl -fsSL -H "Authorization: Bearer $ARGUS_TOKEN" \\\n` +
      `  "$ARGUS_BASE/api/v1/finetune/datasets/${job.dataset_id}/export/train" -o dataset/train.jsonl\n` +
      `curl -fsSL -H "Authorization: Bearer $ARGUS_TOKEN" \\\n` +
      `  "$ARGUS_BASE/api/v1/finetune/datasets/${job.dataset_id}/export/valid" -o dataset/valid.jsonl\n` +
      `\n` +
      `# 2) 외부 트레이너 실행\n` +
      `python -m finetune train \\\n` +
      `  --dataset ./dataset \\\n` +
      `  --output ./out/job-${job.id} \\\n` +
      `  --task ${job.task} \\\n` +
      (job.base_model ? `  --base-model ${job.base_model} \\\n` : "") +
      `  --epochs ${cfg.epochs ?? 3} --batch-size ${cfg.batch_size ?? 32}\n` +
      `\n` +
      `# 3) 진행/결과를 Argus 에 콜백 (PATCH)\n` +
      `curl -fsSL -X PATCH -H "Authorization: Bearer $ARGUS_TOKEN" -H "Content-Type: application/json" \\\n` +
      `  "$ARGUS_BASE/api/v1/finetune/jobs/${job.id}" \\\n` +
      `  -d '{"status":"succeeded","progress":100,"metrics":{"mrr":0.81},"artifact_uri":"s3://..."}'`
    : ""

  return (
    <>
      <DashboardHeader title={job ? `학습 작업 #${job.id}` : "학습 작업"} />
      <div className="flex min-w-0 flex-1 flex-col gap-4 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Link
            href="/dashboard/fine-tuning/jobs"
            className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-4" /> 작업 목록
          </Link>
          {canManage && job && (
            <div className="flex items-center gap-2">
              {job.status === "succeeded" && (
                <Button
                  size="sm"
                  onClick={onRegister}
                  className="bg-emerald-600 text-white hover:bg-emerald-600/90"
                >
                  <PackageCheck className="size-4" /> 모델로 등록
                </Button>
              )}
              {!terminal && (
                <Button
                  size="sm"
                  onClick={onCancel}
                  className="bg-amber-500 text-white hover:bg-amber-500/90"
                >
                  <Ban className="size-4" /> 취소
                </Button>
              )}
              <Button variant="destructive" size="sm" onClick={onDelete}>
                <Trash2 className="size-4" /> 삭제
              </Button>
            </div>
          )}
        </div>

        {loading ? (
          <p className="text-sm text-muted-foreground">불러오는 중…</p>
        ) : !job ? (
          <p className="text-sm text-muted-foreground">작업을 찾을 수 없습니다.</p>
        ) : (
          <>
            <table className="w-full table-fixed border-collapse text-sm text-black">
              <colgroup>
                <col className="w-[100px]" />
                <col />
                <col className="w-[100px]" />
                <col />
                <col className="w-[100px]" />
                <col />
              </colgroup>
              <tbody>
                <tr>
                  <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">상태</th>
                  <td className="border px-3 py-2 align-middle">
                    <span className="flex items-center gap-2">
                      <JobStatusBadge status={job.status} />
                      {job.stage && <span className="text-sm text-muted-foreground">{job.stage}</span>}
                    </span>
                  </td>
                  <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">진행</th>
                  <td className="border px-3 py-2 align-middle">{job.progress}%</td>
                  <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">데이터셋</th>
                  <td className="border px-3 py-2 align-middle">
                    <Link href={`/dashboard/fine-tuning/datasets/${job.dataset_id}`} className="text-primary hover:underline">
                      {job.dataset_name ?? `#${job.dataset_id}`}
                    </Link>
                  </td>
                </tr>
                <tr>
                  <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">대상</th>
                  <td className="border px-3 py-2 align-middle">
                    <Badge variant="outline" className="font-normal">
                      {job.task === "reranker" ? "리랭커" : "임베딩"}
                    </Badge>
                  </td>
                  <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">베이스 모델</th>
                  <td className="border px-3 py-2 align-middle">{job.base_model ?? "—"}</td>
                  <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">설정</th>
                  <td className="border px-3 py-2 align-middle">
                    epochs {cfg.epochs ?? "—"} · batch {cfg.batch_size ?? "—"} · lr {cfg.lr ?? "—"}
                  </td>
                </tr>
                <tr>
                  <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">아티팩트</th>
                  <td className="border px-3 py-2 align-middle break-all font-mono text-sm">{job.artifact_uri ?? "—"}</td>
                  <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">생성일</th>
                  <td className="border px-3 py-2 align-middle">{formatDateTime(job.created_at)}</td>
                  <th className="border bg-muted/60" />
                  <td className="border" />
                </tr>
                <tr>
                  <th className="border bg-muted/60 px-3 py-2 text-left align-middle font-medium text-black">콜백 토큰</th>
                  <td className="border px-3 py-2 align-middle" colSpan={5}>
                    {job.callback_token ? (
                      <span className="flex items-center gap-2">
                        <span className="break-all font-mono text-sm">{job.callback_token}</span>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-6 shrink-0"
                          title="콜백 토큰 복사"
                          onClick={() => copyToken(job.callback_token!)}
                        >
                          <Copy className="size-3.5 text-muted-foreground" />
                        </Button>
                      </span>
                    ) : (
                      <span className="text-sm text-muted-foreground">
                        — (이 기능 추가 전 생성된 잡입니다. 새 잡을 만들면 자동 발급됩니다.)
                      </span>
                    )}
                  </td>
                </tr>
              </tbody>
            </table>

            {job.metrics && (
              <div className="rounded-lg border p-4">
                <p className="mb-2 text-sm font-semibold">valid 지표</p>
                <div className="flex flex-wrap gap-4 text-sm">
                  {Object.entries(job.metrics).map(([k, v]) => (
                    <span key={k} className="text-muted-foreground">
                      {k}: <span className="font-medium text-foreground">{v}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}

            {job.error && (
              <div className="rounded-lg border border-red-500/40 bg-red-500/5 p-4 text-sm text-red-600 dark:text-red-400">
                <p className="mb-1 font-semibold">오류</p>
                <pre className="whitespace-pre-wrap text-xs">{job.error}</pre>
              </div>
            )}

            <div>
              <p className="mb-2 text-sm font-semibold">실행 방법 (외부 트레이너)</p>
              <p className="mb-2 text-sm text-muted-foreground">
                실제 학습은 외부 프로그램이 수행합니다. 아래 절차로 데이터셋을 받아 학습하고, 진행·결과를
                Argus 에 콜백하면 이 화면에 반영됩니다. <span className="font-medium text-foreground">ARGUS_TOKEN
                은 이 잡 전용 콜백 토큰</span>으로, 이 잡의 export·콜백만 인증합니다(사용자 자격증명 노출 없음).
              </p>
              <CodeViewer
                code={runCmd}
                language="shell"
                height={runCmd.split("\n").length * 19 + 20}
                copyLabel="실행 명령"
                border
                wordWrap="on"
                options={{ fontSize: 14 }}
              />
            </div>
          </>
        )}
      </div>
    </>
  )
}
