// 클라이언트(canvas) 썸네일 생성 — 업로드 시·편집기 진입 시 사용.
// 긴 변을 MAX_SIZE 로 축소하고, 투명 배경은 흰색으로 채워 JPEG 로 인코딩한다.

const MAX_SIZE = 320
const QUALITY = 0.85

/** 이미지 소스(File | HTMLImageElement)를 받아 썸네일 Blob(JPEG)을 만든다. */
export async function makeThumbnailBlob(
  source: File | HTMLImageElement
): Promise<Blob> {
  const img = source instanceof HTMLImageElement ? source : await loadImage(source)
  const w = img.naturalWidth || img.width
  const h = img.naturalHeight || img.height
  if (!w || !h) throw new Error("이미지 크기를 읽을 수 없습니다.")

  const scale = Math.min(1, MAX_SIZE / Math.max(w, h))
  const tw = Math.max(1, Math.round(w * scale))
  const th = Math.max(1, Math.round(h * scale))

  const canvas = document.createElement("canvas")
  canvas.width = tw
  canvas.height = th
  const ctx = canvas.getContext("2d")
  if (!ctx) throw new Error("canvas 2D 컨텍스트를 만들 수 없습니다.")
  ctx.fillStyle = "#ffffff" // 투명 PNG 대비 흰 배경
  ctx.fillRect(0, 0, tw, th)
  ctx.drawImage(img, 0, 0, tw, th)

  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("썸네일 인코딩 실패"))),
      "image/jpeg",
      QUALITY
    )
  })
}

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      resolve(img)
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error("이미지를 읽을 수 없습니다."))
    }
    img.src = url
  })
}
