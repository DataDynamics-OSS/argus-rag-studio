// HWP/HWPX "문서 전체 보기" 좌측 원본 렌더링 방식(클라이언트 표시 취향, 이 브라우저에만 저장).
//  - image: rhwp SVG 를 이미지로 표시(빠름) + 매칭 페이지 강조·스크롤 (기본·권장)
//  - svg  : inline SVG 로 렌더 + 매칭 셀 정밀 색칠(정밀하나 복잡 표는 느릴 수 있음)
export const HWP_MODE_KEY = "argus.hwpViewerMode"
export type HwpViewerMode = "image" | "svg"

export function getHwpViewerMode(): HwpViewerMode {
  if (typeof window === "undefined") return "image"
  return window.localStorage.getItem(HWP_MODE_KEY) === "svg" ? "svg" : "image"
}

export function setHwpViewerMode(mode: HwpViewerMode): void {
  if (typeof window !== "undefined") window.localStorage.setItem(HWP_MODE_KEY, mode)
}
