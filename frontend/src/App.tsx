import { Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from '@/components/AppShell'
import { ProtectedRoute } from '@/components/ProtectedRoute'
import { AskPage } from '@/pages/AskPage'
import { ConnectionsPage } from '@/pages/ConnectionsPage'
import { DashboardsPage } from '@/pages/DashboardsPage'
import { GlossaryPage } from '@/pages/GlossaryPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { LoginPage } from '@/pages/LoginPage'

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <AppShell>{children}</AppShell>
    </ProtectedRoute>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/ask"
        element={
          <Shell>
            <AskPage />
          </Shell>
        }
      />
      <Route
        path="/connections"
        element={
          <Shell>
            <ConnectionsPage />
          </Shell>
        }
      />
      <Route
        path="/dashboards"
        element={
          <Shell>
            <DashboardsPage />
          </Shell>
        }
      />
      <Route
        path="/glossary"
        element={
          <Shell>
            <GlossaryPage />
          </Shell>
        }
      />
      <Route
        path="/settings"
        element={
          <Shell>
            <SettingsPage />
          </Shell>
        }
      />
      <Route path="/" element={<Navigate to="/ask" replace />} />
      <Route path="*" element={<Navigate to="/ask" replace />} />
    </Routes>
  )
}
