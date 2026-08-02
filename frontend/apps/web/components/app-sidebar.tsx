import pkg from "../package.json"

import {
  Sidebar,
  SidebarFooter, // Added for SSO AUTH
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@workspace/ui/components/sidebar"
import { Separator } from "@workspace/ui/components/separator"
import { AppSidebarNav } from "@/components/app-sidebar-nav"
import { Logo } from "@/components/logo"
import { SidebarUser } from "@/components/sidebar-user" // Added for SSO AUTH
import { getMenu } from "@/lib/menu"

export async function AppSidebar() {
  const menu = await getMenu()

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              {/* 브랜드 클릭 → 회사 사이트(새 탭). 대시보드 이동은 메뉴로 충분. */}
              <a href="https://www.data-dynamics.io" target="_blank" rel="noopener noreferrer">
                <div className="hidden h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground group-data-[collapsible=icon]:flex">
                  <Logo className="size-5" />
                </div>
                {/* 자매 제품 헤더와 동일한 2줄 구성·스타일 — 브랜드 폰트(RobotoCondensed) 제품명 + 회사명 */}
                <div className="flex min-w-0 flex-col group-data-[collapsible=icon]:hidden">
                  <span className="font-display truncate text-xl font-semibold leading-none tracking-wide text-sidebar-accent-foreground">
                    Argus RAG Studio
                  </span>
                  <span className="mt-1 truncate text-xs text-sidebar-foreground/60">
                    Data Dynamics Inc
                  </span>
                </div>
              </a>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      {/* 검색창(고정) + SidebarContent(스크롤) 는 AppSidebarNav 내부에서 분리 렌더 */}
      <AppSidebarNav groups={menu.groups} />

      {/* Added for SSO AUTH - displays current user info and logout button */}
      <SidebarFooter>
        <SidebarUser />
        {/* 매우 옅은 구분선 — opacity 로 거의 안 보이게만. 접힘(icon) 시 숨김. */}
        <Separator className="my-1 bg-border/30 group-data-[collapsible=icon]:hidden" />
        {/* 버전 표기(락스텝 — package.json) — 클릭 시 GitHub 리포로 새 탭 이동. 접힘(icon) 시 숨김. */}
        <a
          href="https://github.com/DataDynamics-OSS/argus-rag-studio"
          target="_blank"
          rel="noopener noreferrer"
          className="flex h-[22px] items-center justify-center text-xs text-sidebar-accent-foreground transition-colors hover:underline group-data-[collapsible=icon]:hidden"
        >
          Version {pkg.version}
        </a>
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  )
}
