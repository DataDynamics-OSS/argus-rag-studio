"use client"

/** Map extension to MIME type for the <video> source element. */
const videoMimeTypes: Record<string, string> = {
  mp4: "video/mp4",
  webm: "video/webm",
  ogg: "video/ogg",
  mov: "video/quicktime",
  m4v: "video/x-m4v",
  avi: "video/x-msvideo",
  mkv: "video/x-matroska",
}

type VideoViewerProps = {
  /** Ready-to-use media URL (same-origin blob URL from the dialog). */
  url: string
  /** File extension (without dot). */
  extension: string
}

export function VideoViewer({ url, extension }: VideoViewerProps) {
  // url 은 dialog 가 동일출처 바이트로 만든 blob URL 이라 그대로 사용한다(presigned 직접 fetch 회피).
  const mime = videoMimeTypes[extension] ?? "video/mp4"

  return (
    <div className="flex items-center justify-center">
      <video
        controls
        className="max-w-full max-h-[65vh] rounded"
        preload="metadata"
      >
        <source src={url} type={mime} />
        Your browser does not support this video format.
      </video>
    </div>
  )
}
