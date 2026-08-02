// S3 스토리지 관리 — 오브젝트 스토리지(S3/MinIO) 파일 브라우저. 버킷 선택기 + 탐색/다운로드.
"use client"

import { useEffect, useMemo, useState } from "react"
import { Database } from "lucide-react"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { toast } from "sonner"

import { DashboardHeader } from "@/components/dashboard-header"
import { LocalFilesystemBrowser } from "@/components/local-filesystem-browser"
import { createS3DataSource, listBuckets } from "@/features/filesystem/api"

export default function S3StoragePage() {
  const [buckets, setBuckets] = useState<string[]>([])
  const [bucket, setBucket] = useState<string>("")

  // 버킷 목록 로드 → 기본 버킷 선택
  useEffect(() => {
    void (async () => {
      try {
        const { buckets: list, default: def } = await listBuckets()
        setBuckets(list)
        setBucket((prev) => prev || def || list[0] || "")
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "버킷 목록 조회 실패")
      }
    })()
  }, [])

  // 선택 버킷 기준 데이터소스(버킷 변경 시 재생성)
  const dataSource = useMemo(() => createS3DataSource(bucket || undefined), [bucket])

  return (
    <>
      <DashboardHeader title="S3 스토리지" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">버킷</span>
          <Select
            value={bucket}
            onValueChange={(b) => {
              // 버킷이 바뀌면 이전 버킷의 ?path 는 무효 — 히스토리 엔트리 없이 제거.
              const q = new URLSearchParams(window.location.search)
              if (q.has("path")) {
                q.delete("path")
                const qs = q.toString()
                window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname)
              }
              setBucket(b)
            }}
            disabled={buckets.length === 0}
          >
            <SelectTrigger className="h-8 w-72">
              <SelectValue placeholder="버킷 선택" />
            </SelectTrigger>
            <SelectContent>
              {buckets.map((b) => (
                <SelectItem key={b} value={b}>
                  {b}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {bucket ? (
          // 버킷 변경 시 key 로 강제 리마운트 → 경로를 루트로 초기화
          <LocalFilesystemBrowser
            key={bucket}
            initialPath="/"
            urlParam="path"
            dataSource={dataSource}
            className="flex-1"
          />
        ) : (
          <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
            버킷을 선택하세요.
          </div>
        )}
      </div>
    </>
  )
}
