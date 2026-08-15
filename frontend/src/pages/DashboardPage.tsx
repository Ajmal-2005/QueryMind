import { AppShell } from '@/components/AppShell'
import { ConnectionsPage } from '@/pages/ConnectionsPage'

export function DashboardPage() {
  return (
    <AppShell>
      <ConnectionsPage />
    </AppShell>
  )
}
