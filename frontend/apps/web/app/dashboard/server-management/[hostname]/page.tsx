import { DashboardHeader } from "@/components/dashboard-header"
import { AgentDetail } from "@/features/servers/components/detail/agent-detail"

export default async function AgentDetailPage({
  params,
}: {
  params: Promise<{ hostname: string }>
}) {
  const { hostname } = await params
  const decoded = decodeURIComponent(hostname)
  return (
    <>
      <DashboardHeader title="에이전트 상세" />
      <AgentDetail hostname={decoded} />
    </>
  )
}
