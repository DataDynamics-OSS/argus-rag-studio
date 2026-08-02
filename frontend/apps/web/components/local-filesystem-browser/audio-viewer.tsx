"use client"

import { Music } from "lucide-react"

/** Map extension to MIME type for the <audio> source element. */
const audioMimeTypes: Record<string, string> = {
  mp3: "audio/mpeg",
  wav: "audio/wav",
  m4a: "audio/mp4",
  flac: "audio/flac",
  aac: "audio/aac",
  ogg: "audio/ogg",
  wma: "audio/x-ms-wma",
}

type AudioViewerProps = {
  /** Ready-to-use media URL (same-origin blob URL from the dialog). */
  url: string
  /** File extension (without dot). */
  extension: string
  /** File name for display. */
  fileName: string
}

export function AudioViewer({ url, extension, fileName }: AudioViewerProps) {
  // url 은 dialog 가 동일출처 바이트로 만든 blob URL 이라 그대로 사용한다(presigned 직접 fetch 회피).
  const mime = audioMimeTypes[extension] ?? "audio/mpeg"

  return (
    <div className="flex flex-col items-center justify-center gap-6 py-8">
      <div className="flex items-center justify-center w-24 h-24 rounded-full bg-muted">
        <Music className="h-10 w-10 text-muted-foreground" />
      </div>
      <p className="text-sm text-muted-foreground truncate max-w-[400px]">{fileName}</p>
      <audio controls preload="metadata" className="w-full max-w-[500px]">
        <source src={url} type={mime} />
        Your browser does not support this audio format.
      </audio>
    </div>
  )
}
