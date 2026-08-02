import { type ServerStatus } from "./schema"

/**
 * Visual style mapping for server status badges.
 *
 * Maps each ServerStatus value to a Tailwind CSS class string used by the
 * Badge component in the servers table. The classes control background color,
 * text color, and border color to provide at-a-glance status indication:
 *
 * - REGISTERED   → Green  (active, healthy)
 * - UNREGISTERED → Yellow (pending registration or intentionally unregistered)
 * - DISCONNECTED → Red    (lost connectivity, needs attention)
 */
export const serverStatusStyles = new Map<ServerStatus, string>([
  [
    "REGISTERED",
    "bg-green-500/10 text-green-600 border-green-500/30",
  ],
  [
    "UNREGISTERED",
    "bg-yellow-500/10 text-yellow-600 border-yellow-500/30",
  ],
  [
    "DISCONNECTED",
    "bg-destructive/10 dark:bg-destructive/50 text-destructive dark:text-primary border-destructive/10",
  ],
])

/** 상태 배지에 표시할 한글 라벨. */
export const serverStatusLabels = new Map<ServerStatus, string>([
  ["REGISTERED", "등록됨"],
  ["UNREGISTERED", "미등록"],
  ["DISCONNECTED", "연결 끊김"],
])
