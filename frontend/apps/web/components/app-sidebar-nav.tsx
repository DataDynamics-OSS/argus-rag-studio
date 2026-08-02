"use client"

// 사이드바 내비게이션 — 메뉴 검색(Ctrl+/) + 그룹 접힘(localStorage 유지).
// 사내 자매 제품 사이드바의 검색/접힘 UX 를 shadcn Sidebar 구조에 이식.

import { useEffect, useMemo, useRef, useState } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { ChevronDown, Search } from "lucide-react"

import {
  SidebarContent,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@workspace/ui/components/sidebar"
import { getIcon } from "@/lib/icon-map"
import { usePermissions } from "@/features/permissions/use-permissions"
import { urlToMenuKey } from "@/lib/permission-registry"
import { useAuth } from "@/features/auth"
import type { MenuGroup } from "@/types/menu"

interface AppSidebarNavProps {
  groups: MenuGroup[]
}

// 접힌 그룹 상태 persistence. 저장 형태: string[] (접힌 그룹 id 목록).
// 스키마 변경 시 버전 번호를 올려 기존 값을 무효화.
const COLLAPSED_GROUPS_KEY = "argus-sidebar-collapsed-groups-v1"

function loadCollapsedGroups(): Set<string> {
  if (typeof window === "undefined") return new Set()
  try {
    const raw = window.localStorage.getItem(COLLAPSED_GROUPS_KEY)
    if (!raw) return new Set()
    const arr = JSON.parse(raw)
    return new Set(Array.isArray(arr) ? arr.filter((x) => typeof x === "string") : [])
  } catch {
    return new Set()
  }
}

function saveCollapsedGroups(set: Set<string>) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(COLLAPSED_GROUPS_KEY, JSON.stringify([...set]))
  } catch {
    /* localStorage 비허용 환경은 무시 */
  }
}

export function AppSidebarNav({ groups }: AppSidebarNavProps) {
  const pathname = usePathname()
  const { isMenuAllowed } = usePermissions()
  const { user } = useAuth()

  // 그룹별 접힘 — 초기엔 빈 Set(모두 펼침). useEffect 로 localStorage 로드
  // (SSR 은 항상 빈 Set 이라 hydration mismatch 없음).
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set())
  useEffect(() => {
    setCollapsedGroups(loadCollapsedGroups())
  }, [])

  function toggleGroup(id: string) {
    setCollapsedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      saveCollapsedGroups(next)
      return next
    })
  }

  // 메뉴 검색 — 라벨 부분일치. 매칭 0건 그룹은 통째로 숨김, 검색 중엔 접힘 무시.
  const [query, setQuery] = useState("")
  const searchInputRef = useRef<HTMLInputElement>(null)
  const isSearching = query.trim().length > 0

  // 전역 단축키: Ctrl/Cmd + / 로 검색 포커스 — modifier 조합이라 입력 필드 안에서도 안전.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "/" || !(e.ctrlKey || e.metaKey)) return
      e.preventDefault()
      searchInputRef.current?.focus()
      searchInputRef.current?.select()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  // 권한 매트릭스(메뉴 및 기능 권한)에서 차단된 메뉴 숨김 + 검색 필터.
  // open-by-default — 설정 없는 메뉴는 항상 통과한다.
  const visibleGroups = useMemo(() => {
    const q = query.trim().toLowerCase()
    return groups
      .map((group) => {
        // Administration group is only visible to admins
        if (group.id === "admin" && !user?.is_admin) return null
        const items = group.items
          .filter((item) => !item.adminOnly || user?.is_admin)
          .filter((item) => isMenuAllowed(urlToMenuKey(item.url)))
          .filter((item) => !q || item.title.toLowerCase().includes(q))
        return items.length > 0 ? { ...group, items } : null
      })
      .filter((g): g is MenuGroup => g !== null)
  }, [groups, user, isMenuAllowed, query])

  // 현재 경로가 속한 그룹은 접힘 상태여도 강제로 펼친다 — 현재 페이지의
  // 네비게이션 맥락을 잃지 않기 위해서. (dashboard 는 prefix 매칭 제외.)
  const activeGroupId = visibleGroups.find((g) =>
    g.items.some(
      (it) => pathname === it.url || (it.url !== "/dashboard" && pathname.startsWith(it.url + "/"))
    )
  )?.id

  return (
    <>
      {/* 메뉴 검색 — SidebarContent(스크롤 영역) 바깥이라 메뉴를 스크롤해도 고정.
          자매 제품과 동일한 사이드바 스타일. 아이콘 접힘 모드에서는 숨김 */}
      <div className="shrink-0 px-2 pb-2 pt-3 group-data-[collapsible=icon]:hidden">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-sidebar-foreground/60" />
          <input
            ref={searchInputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setQuery("")
                searchInputRef.current?.blur()
              }
            }}
            placeholder="메뉴 검색"
            aria-label="메뉴 검색"
            className="h-8 w-full rounded-md border border-transparent bg-sidebar-accent/40 pl-7 pr-10 text-sm text-sidebar-accent-foreground outline-none transition-colors placeholder:text-sidebar-foreground/60 focus:border-sidebar-border focus:bg-sidebar-accent/60"
          />
          {query ? (
            <button
              type="button"
              onClick={() => {
                setQuery("")
                searchInputRef.current?.focus()
              }}
              aria-label="검색 지우기"
              className="absolute right-1 top-1/2 inline-flex size-5 -translate-y-1/2 items-center justify-center rounded text-sidebar-foreground/60 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
            >
              <span className="text-xs leading-none">×</span>
            </button>
          ) : (
            <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded border border-sidebar-border px-1 py-0.5 font-mono text-[10px] leading-none text-sidebar-foreground/60">
              Ctrl /
            </span>
          )}
        </div>
      </div>

      {/* 아이콘 접힘 모드에서도 세로 스크롤 — 기본(overflow-hidden)은 긴 메뉴의 아이콘을 가린다. */}
      <SidebarContent className="group-data-[collapsible=icon]:overflow-y-auto group-data-[collapsible=icon]:overflow-x-hidden">
        {isSearching && visibleGroups.length === 0 && (
          <div className="px-4 pt-1 text-xs text-sidebar-foreground/60 group-data-[collapsible=icon]:hidden">
            &ldquo;{query}&rdquo; 와 일치하는 메뉴 없음
          </div>
        )}

        {visibleGroups.map((group) => {
        // 검색 중엔 접힘 무시(결과를 가리지 않게), 활성 경로 그룹은 강제 펼침.
        const isGroupCollapsed =
          !isSearching && collapsedGroups.has(group.id) && group.id !== activeGroupId
        return (
          <SidebarGroup key={group.id}>
            <SidebarGroupLabel asChild>
              <button
                type="button"
                onClick={() => toggleGroup(group.id)}
                aria-expanded={!isGroupCollapsed}
                className="w-full cursor-pointer justify-between transition-colors hover:font-semibold hover:text-sidebar-accent-foreground"
              >
                <span>{group.label}</span>
                <ChevronDown
                  className={
                    "size-3 transition-transform duration-150" +
                    (isGroupCollapsed ? " -rotate-90" : "")
                  }
                />
              </button>
            </SidebarGroupLabel>
            {/* 아이콘 접힘 모드에서는 그룹 라벨이 숨겨지므로 그룹 접힘을 적용하지 않는다 —
                icon 모드에서는 항상 표시(메뉴 접근을 잃지 않게). */}
            <SidebarMenu
              className={isGroupCollapsed ? "hidden group-data-[collapsible=icon]:flex" : undefined}
            >
              {group.items.map((item) => {
                const Icon = getIcon(item.icon)
                return (
                  <SidebarMenuItem key={item.id}>
                    <SidebarMenuButton
                      asChild
                      isActive={
                        pathname === item.url ||
                        (item.url !== "/dashboard" && pathname.startsWith(item.url + "/"))
                      }
                      tooltip={item.title}
                      className="text-sm"
                    >
                      <Link href={item.url} prefetch={false}>
                        <Icon />
                        <span>{item.title}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroup>
        )
        })}
      </SidebarContent>
    </>
  )
}
