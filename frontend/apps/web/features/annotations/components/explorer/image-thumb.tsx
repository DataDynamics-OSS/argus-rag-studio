"use client"

// 어노테이션 이미지 썸네일 — 썸네일이 있으면 /thumbnail, 없으면 원본 /file 로 폴백.

import { useEffect, useState } from "react"
import { ImageIcon, Loader2 } from "lucide-react"
import { getImageBlobUrl, getObjectBlobUrl, getThumbBlobUrl } from "../../api"

export function ImageThumb({
  imageId,
  alt,
  hasThumbnail,
  objectKey,
}: {
  imageId: string
  alt: string
  hasThumbnail?: boolean
  /** 주어지면 DB 미등록 오브젝트(분할 크롭 등)를 키로 직접 로드한다(읽기전용). */
  objectKey?: string | null
}) {
  const [url, setUrl] = useState<string>("")
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let revoked = ""
    let cancelled = false
    ;(async () => {
      try {
        let u: string | null = null
        if (objectKey) {
          u = await getObjectBlobUrl(objectKey)
        } else {
          if (hasThumbnail) u = await getThumbBlobUrl(imageId)
          if (!u) u = await getImageBlobUrl(imageId)
        }
        revoked = u
        if (!cancelled) setUrl(u)
      } catch {
        if (!cancelled) setFailed(true)
      }
    })()
    return () => {
      cancelled = true
      if (revoked) URL.revokeObjectURL(revoked)
    }
  }, [imageId, hasThumbnail, objectKey])

  if (failed) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-muted text-muted-foreground">
        <ImageIcon className="h-6 w-6" />
      </div>
    )
  }
  if (!url) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-muted">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={url} alt={alt} className="h-full w-full object-contain" draggable={false} />
  )
}
