/**
 * 권한 레지스트리 — 메뉴/기능의 단일 정의처.
 *
 * 백엔드는 key 문자열만 저장하므로(open-by-default), 여기 정의가 곧
 * 권한 관리 화면의 행이 된다. 새 메뉴/기능을 통제하려면 이 파일에
 * 항목을 추가하면 끝 — 백엔드 변경 불필요.
 *
 * 메뉴 key 는 사이드바(menu.json)의 url 과 매핑된다 (urlToMenuKey).
 */

export const MANAGED_ROLES = ["argus-superuser", "argus-user"] as const
export type ManagedRole = (typeof MANAGED_ROLES)[number]

export const ROLE_LABELS: Record<string, string> = {
  "argus-admin": "Admin",
  "argus-superuser": "Superuser",
  "argus-user": "User",
}

export type MenuEntry = { key: string; label: string; group: string; url: string }
export type FeatureEntry = { key: string; label: string; menuKey: string; description: string }

// ---------------------------------------------------------------------------
// 메뉴 — 사이드바(menu.json) 와 1:1
// ---------------------------------------------------------------------------

export const MENU_REGISTRY: MenuEntry[] = [
  { key: "dashboard", label: "대시보드", group: "RAG Studio", url: "/dashboard" },
  { key: "overview", label: "RAG 개요", group: "RAG Studio", url: "/dashboard/overview" },
  { key: "collections", label: "지식베이스", group: "RAG Studio", url: "/dashboard/collections" },
  { key: "playground", label: "Playground", group: "RAG Studio", url: "/dashboard/playground" },
  { key: "chat", label: "Chat", group: "RAG Studio", url: "/dashboard/chat" },
  { key: "pipelines", label: "파이프라인", group: "RAG Studio", url: "/dashboard/pipelines" },
  { key: "evaluation", label: "평가", group: "RAG Studio", url: "/dashboard/evaluation" },
  { key: "feedback", label: "피드백", group: "RAG Studio", url: "/dashboard/feedback" },
  { key: "jobs", label: "잡 모니터링", group: "RAG Studio", url: "/dashboard/jobs" },
  { key: "observability", label: "운영", group: "RAG Studio", url: "/dashboard/observability" },
  { key: "finetuning-overview", label: "파인 튜닝 개요", group: "파인 튜닝", url: "/dashboard/fine-tuning/overview" },
  { key: "finetuning-glossary", label: "용어 사전", group: "파인 튜닝", url: "/dashboard/fine-tuning/glossary" },
  { key: "finetuning-labeling", label: "텍스트 라벨링", group: "파인 튜닝", url: "/dashboard/fine-tuning/labeling" },
  { key: "annotations-explorer", label: "이미지 라벨링", group: "파인 튜닝", url: "/dashboard/annotations/explorer" },
  { key: "image-recognition", label: "이미지 추출 및 분석", group: "파인 튜닝", url: "/dashboard/annotations/recognition" },
  { key: "finetuning-datasets", label: "학습 데이터셋", group: "파인 튜닝", url: "/dashboard/fine-tuning/datasets" },
  { key: "finetuning-jobs", label: "학습 작업", group: "파인 튜닝", url: "/dashboard/fine-tuning/jobs" },
  { key: "finetuning-models", label: "모델", group: "파인 튜닝", url: "/dashboard/fine-tuning/models" },
  { key: "users", label: "사용자", group: "관리", url: "/dashboard/users" },
  { key: "server-management", label: "에이전트", group: "관리", url: "/dashboard/server-management" },
  { key: "s3-storage", label: "S3 스토리지", group: "관리", url: "/dashboard/s3-storage" },
  { key: "storage-sources", label: "스토리지 소스", group: "관리", url: "/dashboard/storage-sources" },
  { key: "models", label: "모델", group: "관리", url: "/dashboard/models" },
  { key: "permissions", label: "메뉴 및 기능 권한", group: "관리", url: "/dashboard/permissions" },
  { key: "pii-rules", label: "PII Rule", group: "관리", url: "/dashboard/pii-rules" },
  { key: "routing", label: "RAG 문서 라우팅", group: "관리", url: "/dashboard/routing" },
  { key: "api-keys", label: "API 키", group: "관리", url: "/dashboard/api-keys" },
  { key: "settings", label: "설정", group: "관리", url: "/dashboard/settings" },
]

export const MENU_GROUP_ORDER = ["RAG Studio", "파인 튜닝", "관리"]

/** 사이드바 url → 메뉴 key (필터링용). 가장 긴 prefix 매칭. */
export function urlToMenuKey(url: string): string | null {
  let best: MenuEntry | null = null
  for (const m of MENU_REGISTRY) {
    if (url === m.url || url.startsWith(m.url + "/")) {
      if (!best || m.url.length > best.url.length) best = m
    }
  }
  return best?.key ?? null
}

// ---------------------------------------------------------------------------
// 기능 — 메뉴 내부 버튼·동작 (지식베이스/문서 인제스천)
// ---------------------------------------------------------------------------

export const FEATURE_REGISTRY: FeatureEntry[] = [
  { key: "collections.manage", label: "지식베이스 생성/수정", menuKey: "collections", description: "컬렉션 생성·메타데이터 수정" },
  { key: "collections.delete", label: "지식베이스 삭제", menuKey: "collections", description: "컬렉션 삭제(하위 문서 포함)" },
  { key: "documents.upload", label: "문서 업로드/인제스천", menuKey: "collections", description: "파일 업로드 → 파싱·청킹·임베딩" },
  { key: "documents.reindex", label: "문서 재처리", menuKey: "collections", description: "기존 문서 재인덱싱" },
  { key: "documents.delete", label: "문서 삭제", menuKey: "collections", description: "문서·청크 삭제" },
  { key: "pipelines.manage", label: "파이프라인 생성/수정", menuKey: "pipelines", description: "파이프라인 생성·설정 편집(새 버전 저장)·버전 활성화" },
  { key: "pipelines.delete", label: "파이프라인 삭제", menuKey: "pipelines", description: "파이프라인 삭제(버전 포함)" },
  { key: "evaluation.manage", label: "평가 데이터셋/항목 관리", menuKey: "evaluation", description: "골든 데이터셋·항목 생성/삭제" },
  { key: "evaluation.run", label: "평가 실행", menuKey: "evaluation", description: "평가 Run·설정 스윕 실행" },
  { key: "feedback.promote", label: "피드백 승격/무시", menuKey: "feedback", description: "피드백을 골든셋으로 승격·무시 처리" },
  { key: "feedback.delete", label: "피드백 삭제", menuKey: "feedback", description: "수집된 피드백 삭제" },
  { key: "jobs.manage", label: "잡 재처리", menuKey: "jobs", description: "실패 잡 재인덱싱 등 잡 제어" },
]
