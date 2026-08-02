// 모델 상세 — 서빙 연결·상태·발행 편집 + 지표·출처 + 삭제.
"use client"

import { useCallback, useEffect, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import Link from "next/link"
import { ArrowLeft, Trash2 } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import { Badge } from "@workspace/ui/components/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard-header"
import { useAuth } from "@/features/auth"
import { deleteModel, getModel, updateModel } from "@/features/finetune/api"
import type { FtModel } from "@/features/finetune/data/schema"

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm text-foreground">{children}</span>
    </div>
  )
}

export default function FtModelDetailPage() {
  const params = useParams<{ id: string }>()
  // 외부 노출은 모델 UUID. 내부 작업은 해석된 model.id(정수 PK)를 쓴다.
  const uuid = String(params.id)
  const router = useRouter()
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser

  const [model, setModel] = useState<FtModel | null>(null)
  const [loading, setLoading] = useState(true)
  const [servingUrl, setServingUrl] = useState("")
  const [status, setStatus] = useState("registered")
  const [publishedUri, setPublishedUri] = useState("")
  const [saving, setSaving] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const m = await getModel(uuid)
      setModel(m)
      setServingUrl(m.serving_url ?? "")
      setStatus(m.status)
      setPublishedUri(m.published_uri ?? "")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [uuid])

  useEffect(() => {
    if (uuid && uuid !== "undefined") refresh()
  }, [uuid, refresh])

  async function onSave() {
    if (!model) return
    setSaving(true)
    try {
      const m = await updateModel(model.id, {
        serving_url: servingUrl.trim() || null,
        status,
        published_uri: publishedUri.trim() || null,
      })
      setModel(m)
      toast.success("저장했습니다.")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "저장 실패")
    } finally {
      setSaving(false)
    }
  }

  async function onDelete() {
    if (!model) return
    try {
      await deleteModel(model.id)
      toast.success("모델을 삭제했습니다.")
      router.push("/dashboard/fine-tuning/models")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "삭제 실패")
    }
  }

  return (
    <>
      <DashboardHeader title={model?.name ?? "모델"} />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <div className="flex items-center justify-between">
          <Link
            href="/dashboard/fine-tuning/models"
            className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-4" /> 모델 목록
          </Link>
          {canManage && model && (
            <Button variant="outline" size="sm" onClick={onDelete}>
              <Trash2 className="size-4" /> 삭제
            </Button>
          )}
        </div>

        {loading ? (
          <p className="text-sm text-muted-foreground">불러오는 중…</p>
        ) : !model ? (
          <p className="text-sm text-muted-foreground">모델을 찾을 수 없습니다.</p>
        ) : (
          <>
            <div className="grid gap-4 rounded-lg border p-4 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="대상">
                <Badge variant="outline" className="font-normal">
                  {model.task === "reranker" ? "리랭커" : "임베딩"}
                </Badge>
              </Field>
              <Field label="베이스 모델">
                <span className="font-mono text-xs">{model.base_model ?? "—"}</span>
              </Field>
              <Field label="포맷 / 차원">
                <span className="font-mono text-xs">
                  {model.format ?? "—"}
                  {model.embedding_dim ? ` · ${model.embedding_dim}d` : ""}
                </span>
              </Field>
              <Field label="출처">
                <span className="text-xs">
                  {model.job_id ? (
                    <Link href={`/dashboard/fine-tuning/jobs/${model.job_id}`} className="text-primary hover:underline">
                      작업 #{model.job_id}
                    </Link>
                  ) : (
                    "수동 등록"
                  )}
                  {model.dataset_id ? (
                    <>
                      {" · "}
                      <Link href={`/dashboard/fine-tuning/datasets/${model.dataset_id}`} className="text-primary hover:underline">
                        데이터셋 #{model.dataset_id}
                      </Link>
                    </>
                  ) : null}
                </span>
              </Field>
              <Field label="아티팩트">
                <span className="font-mono text-xs break-all">{model.artifact_uri ?? "—"}</span>
              </Field>
            </div>

            {model.metrics && (
              <div className="rounded-lg border p-4">
                <p className="mb-2 text-sm font-semibold">학습 valid 지표</p>
                <div className="flex flex-wrap gap-4 text-sm">
                  {Object.entries(model.metrics).map(([k, v]) => (
                    <span key={k} className="text-muted-foreground">
                      {k}: <span className="font-medium text-foreground">{v}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* 서빙 연결 + 발행 편집 */}
            <div className="flex max-w-2xl flex-col gap-4 rounded-lg border p-4">
              <p className="text-sm font-semibold">서빙 · 발행</p>
              <div className="flex flex-col gap-2">
                <Label htmlFor="m-serving">서빙 URL</Label>
                <Input
                  id="m-serving"
                  value={servingUrl}
                  onChange={(e) => setServingUrl(e.target.value)}
                  placeholder={
                    model.task === "reranker"
                      ? "리랭크 서버 (cross_encoder)"
                      : "OpenAI 호환 임베딩 서버 (예: http://host:8080/v1)"
                  }
                  disabled={!canManage}
                />
                <p className="text-xs text-muted-foreground">
                  {model.task === "reranker"
                    ? "컬렉션 리랭커를 cross_encoder 로 두고 이 URL 을 가리킵니다(재인덱싱 불필요)."
                    : "컬렉션 임베딩 프로바이더를 OpenAI 호환으로 두고 이 URL 을 가리킵니다(차원 일치 필요)."}
                </p>
              </div>
              <div className="flex flex-col gap-2">
                <Label>상태</Label>
                <Select value={status} onValueChange={setStatus} disabled={!canManage}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="registered">registered (등록됨)</SelectItem>
                    <SelectItem value="serving">serving (서빙 중)</SelectItem>
                    <SelectItem value="archived">archived (보관)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="m-published">발행 위치 (선택 — OCI/MLflow)</Label>
                <Input
                  id="m-published"
                  value={publishedUri}
                  onChange={(e) => setPublishedUri(e.target.value)}
                  placeholder="예: oci://registry/argus/tax-law-e5:v1"
                  disabled={!canManage}
                />
              </div>
              {canManage && (
                <div>
                  <Button size="sm" onClick={onSave} disabled={saving}>
                    {saving ? "저장 중…" : "저장"}
                  </Button>
                </div>
              )}
            </div>

            <p className="text-xs text-muted-foreground">
              연결 후, 새 컬렉션을 이 모델로 만들고{" "}
              <Link href="/dashboard/evaluation" className="text-primary hover:underline">
                평가
              </Link>
              에서 홀드아웃 골든셋으로 기존 모델과 비교하십시오.
            </p>
          </>
        )}
      </div>
    </>
  )
}
