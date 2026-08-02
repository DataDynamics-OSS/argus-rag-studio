// 에이전트 — 서버 관리(에이전트 호스트 테이블) / 서비스 관리(전체 배포 서비스 집계) 탭.
// 설계 design/agent-services-overview.md. 탭은 ?tab= URL 동기화(UrlTabs).
"use client"

import Link from "next/link"
import { Boxes } from "lucide-react"

import { Button } from "@workspace/ui/components/button"
import { TabsContent, TabsList, TabsTrigger } from "@workspace/ui/components/tabs"

import { DashboardHeader } from "@/components/dashboard-header"
import { UrlTabs } from "@/components/url-tabs"
import { ServersProvider } from "@/features/servers/components/servers-provider"
import { ServersTableWrapper } from "@/features/servers/components/servers-table-wrapper"
import { ServicesOverview } from "@/features/servers/components/services-overview"

export default function ServerManagementPage() {
  return (
    <>
      <DashboardHeader title="에이전트" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <UrlTabs defaultValue="servers" className="flex flex-1 flex-col gap-4">
          <div className="flex items-center justify-between">
            <TabsList>
              <TabsTrigger value="servers">서버 관리</TabsTrigger>
              <TabsTrigger value="services">서비스 관리</TabsTrigger>
            </TabsList>
            <Button variant="outline" size="sm" asChild>
              <Link href="/dashboard/server-management/clusters">
                <Boxes className="size-4" /> Kubernetes 클러스터
              </Link>
            </Button>
          </div>
          <TabsContent value="servers">
            <ServersProvider>
              <ServersTableWrapper />
            </ServersProvider>
          </TabsContent>
          <TabsContent value="services">
            <ServicesOverview />
          </TabsContent>
        </UrlTabs>
      </div>
    </>
  )
}
