import { SidebarInset, SidebarProvider } from "@workspace/ui/components/sidebar"
import { TooltipProvider } from "@workspace/ui/components/tooltip"
import { AppSidebar } from "@/components/app-sidebar"
import { AuthGuardWrapper } from "@/components/auth-guard-wrapper"
import { PermissionProvider } from "@/features/permissions/use-permissions"

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    // 인증 가드 → 권한 컨텍스트 → 사이드바(접힘/크기) → 본문
    <AuthGuardWrapper>
      <TooltipProvider>
        <PermissionProvider>
          <SidebarProvider>
            <AppSidebar />
            <SidebarInset>{children}</SidebarInset>
          </SidebarProvider>
        </PermissionProvider>
      </TooltipProvider>
    </AuthGuardWrapper>
  )
}
