// S3 스토리지 브라우저 데이터소스 — GET /api/v1/s3-storage/list|download (admin).
// 읽기 전용: 목록 + 다운로드(presigned). 삭제/업로드/이름변경/폴더생성/미리보기는 미지원.

import type {
  FilesystemDataSource,
  FilesystemFile,
  FilesystemFolder,
  ListDirectoryResponse,
} from "@/components/local-filesystem-browser"
import { authFetch, getAccessToken, throwOnError } from "@/features/auth/auth-fetch"

const S3_BASE = "/api/v1/s3-storage"

async function apiFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await authFetch(url, init)
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail || `API 오류 ${res.status}`)
  }
  return res.json()
}

function jsonPost(path: string, body: unknown): Promise<unknown> {
  return apiFetch(`${S3_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

/** 버킷 목록 + 기본 버킷(버킷 선택기용). */
export async function listBuckets(): Promise<{ buckets: string[]; default: string }> {
  return apiFetch<{ buckets: string[]; default: string }>(`${S3_BASE}/buckets`)
}

function toFolder(f: {
  key: string
  name: string
  owner?: string
  group?: string
  permissions?: string
}): FilesystemFolder {
  return { kind: "folder", key: f.key, name: f.name, owner: f.owner, group: f.group, permissions: f.permissions }
}

function toFile(f: {
  key: string
  name: string
  size: number
  last_modified: string
  owner?: string
  group?: string
  permissions?: string
}): FilesystemFile {
  return {
    kind: "file",
    key: f.key,
    name: f.name,
    size: f.size,
    lastModified: f.last_modified,
    owner: f.owner,
    group: f.group,
    permissions: f.permissions,
  }
}

/** 오브젝트 스토리지(S3/MinIO)를 읽기 전용으로 탐색하는 데이터소스. bucket 미지정=기본 버킷. */
export function createS3DataSource(bucket?: string): FilesystemDataSource {
  // 쿼리스트링에 선택 버킷을 항상 덧붙인다.
  const qs = (init: Record<string, string>) => {
    const sp = new URLSearchParams(init)
    if (bucket) sp.set("bucket", bucket)
    return sp
  }
  return {
    async listDirectory(path: string): Promise<ListDirectoryResponse> {
      const params = qs({ path })
      const data = await apiFetch<{
        folders: Array<{ key: string; name: string; owner?: string; group?: string; permissions?: string }>
        files: Array<{
          key: string
          name: string
          size: number
          last_modified: string
          owner?: string
          group?: string
          permissions?: string
        }>
        current_path: string
      }>(`${S3_BASE}/list?${params}`)
      return {
        folders: data.folders.map(toFolder),
        files: data.files.map(toFile),
        currentPath: data.current_path,
      }
    },

    async getDownloadUrl(path: string): Promise<string> {
      const params = qs({ path })
      const data = await apiFetch<{ url: string }>(`${S3_BASE}/download?${params}`)
      return data.url
    },

    // 텍스트/hex 미리보기용 — presigned URL 직접 fetch 는 MinIO CORS 로 막히므로
    // 동일출처 프록시(/content)를 authFetch 로 호출해 바이트를 받는다.
    async getBytes(path: string): Promise<ArrayBuffer> {
      const params = qs({ path })
      const res = await authFetch(`${S3_BASE}/content?${params}`)
      if (!res.ok) throw new Error(`파일을 불러오지 못했습니다 (${res.status})`)
      return res.arrayBuffer()
    },

    async createFolder(path: string): Promise<void> {
      await jsonPost("/folder", { path, bucket })
    },

    async uploadFiles(directoryPath: string, files: File[]): Promise<void> {
      for (const file of files) {
        const fd = new FormData()
        fd.append("directory", directoryPath)
        fd.append("file", file)
        if (bucket) fd.append("bucket", bucket)
        const res = await authFetch(`${S3_BASE}/upload`, { method: "POST", body: fd })
        if (!res.ok) await throwOnError(res, "업로드 실패")
      }
    },

    // 진행률 표시용 — XHR 로 업로드 이벤트를 받아 onProgress 호출
    uploadFileWithProgress(directoryPath, file, onProgress): Promise<void> {
      return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.open("POST", `${S3_BASE}/upload`)
        const token = getAccessToken()
        if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`)
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) onProgress(e.loaded / e.total)
        }
        xhr.onload = () =>
          xhr.status >= 200 && xhr.status < 300
            ? resolve()
            : reject(new Error(`업로드 실패 (${xhr.status})`))
        xhr.onerror = () => reject(new Error("업로드 실패"))
        const fd = new FormData()
        fd.append("directory", directoryPath)
        fd.append("file", file)
        if (bucket) fd.append("bucket", bucket)
        xhr.send(fd)
      })
    },

    async deletePaths(paths: string[]): Promise<void> {
      await jsonPost("/delete", { paths, bucket })
    },

    async renamePath(sourcePath: string, destinationPath: string): Promise<void> {
      await jsonPost("/rename", { source: sourcePath, destination: destinationPath, bucket })
    },

    // 오피스 고충실도 미리보기 — LibreOffice 변환 PDF 바이트. 미설치/실패면 null(→ native 폴백).
    async getOfficePdf(path: string): Promise<ArrayBuffer | null> {
      const params = qs({ path })
      const res = await authFetch(`${S3_BASE}/office-pdf?${params}`)
      if (!res.ok) return null
      return res.arrayBuffer()
    },

    // 오피스/데이터 파일 서버사이드 미리보기 — xlsx/xls/docx/pptx/parquet
    async previewFile(path: string, options?: { sheet?: string; maxRows?: number }): Promise<unknown> {
      const params = qs({ path })
      if (options?.sheet) params.set("sheet", options.sheet)
      if (options?.maxRows) params.set("max_rows", String(options.maxRows))
      return apiFetch(`${S3_BASE}/preview?${params}`)
    },
  }
}
