"use client"

import Link from "next/link"
import { ArrowLeft } from "lucide-react"

import { Button } from "@workspace/ui/components/button"

import { DashboardHeader } from "@/components/dashboard-header"
import { ClustersView } from "@/features/deploy/components/clusters-view"

export default function ClustersPage() {
  return (
    <>
      <DashboardHeader title="클러스터 (Kubernetes 배포)" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <Button variant="ghost" size="sm" asChild className="self-start">
          <Link href="/dashboard/server-management">
            <ArrowLeft className="size-4" /> 에이전트
          </Link>
        </Button>
        <ClustersView />
      </div>
    </>
  )
}
