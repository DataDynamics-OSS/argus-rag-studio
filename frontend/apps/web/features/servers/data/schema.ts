import { z } from "zod"

/**
 * Server status enum schema.
 *
 * Defines the possible lifecycle states of a server (agent):
 * - REGISTERED:   The server has been registered and is actively managed by the platform.
 * - UNREGISTERED: The server has been discovered (agent reported in) but is not yet
 *                 registered for management, or was previously unregistered by an admin.
 * - DISCONNECTED: The server was registered but has lost connectivity (heartbeat timeout).
 */
const serverStatusSchema = z.union([
  z.literal("REGISTERED"),
  z.literal("UNREGISTERED"),
  z.literal("DISCONNECTED"),
])
export type ServerStatus = z.infer<typeof serverStatusSchema>

/**
 * Server (agent) schema.
 *
 * Represents a single managed server as returned by the backend API.
 * Fields use camelCase on the frontend (converted from the backend's snake_case
 * via the `mapServer` function in `api.ts`).
 *
 * Nullable fields (version, osVersion, coreCount, etc.) may be null when the
 * agent has not yet reported system information to the server.
 */
const serverSchema = z.object({
  /** Unique identifier — the machine hostname reported by the agent. */
  hostname: z.string(),
  /** IPv4 or IPv6 address of the agent. */
  ipAddress: z.string(),
  /** Agent software version (e.g. "0.1.0"). Null if not yet reported. */
  version: z.string().nullable(),
  /** Operating system version string (e.g. "Rocky Linux 9.3"). Null if not yet reported. */
  osVersion: z.string().nullable(),
  /** CPU 아키텍처(amd64|arm64). 이미지 변형 선택에 사용. Null if not yet reported. */
  arch: z.string().nullable(),
  /** Number of CPU cores. Null if not yet reported. */
  coreCount: z.number().nullable(),
  /** Total physical memory in bytes. Null if not yet reported. */
  totalMemory: z.number().nullable(),
  /** Current CPU usage as a percentage (0-100). Null if not yet reported. */
  cpuUsage: z.number().nullable(),
  /** Current memory usage as a percentage (0-100). Null if not yet reported. */
  memoryUsage: z.number().nullable(),
  /** Current disk swap usage as a percentage (0-100). Null if not yet reported. */
  diskSwapPercent: z.number().nullable(),
  /** NVIDIA GPU 수. GPU 미탑재거나 미보고 시 null. */
  gpuCount: z.number().nullable(),
  /** 평균 GPU 이용률(0-100). GPU 없거나 미보고 시 null. */
  gpuUsage: z.number().nullable(),
  /** 평균 GPU 메모리 점유율(0-100). GPU 없거나 미보고 시 null. */
  gpuMemoryUsage: z.number().nullable(),
  /** 첫 GPU 모델명. GPU 없거나 미보고 시 null. */
  gpuName: z.string().nullable(),
  /** Current lifecycle status of the server. */
  status: serverStatusSchema,
  /** Seconds elapsed since the last heartbeat was received. Null if no heartbeat recorded. */
  lastHeartbeatSeconds: z.number().nullable(),
  /** Timestamp when the agent first registered with the server. */
  createdAt: z.coerce.date(),
  /** Timestamp of the most recent update to this record. */
  updatedAt: z.coerce.date(),
})
export type Server = z.infer<typeof serverSchema>

/** Zod schema for validating an array of Server objects. */
export const serverListSchema = z.array(serverSchema)
