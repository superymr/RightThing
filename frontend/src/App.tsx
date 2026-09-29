import { Navigate, Route, Routes } from 'react-router-dom'

import { Layout } from './components/Layout'
import { AnalyzePage } from './pages/AnalyzePage'
import { DashboardPage } from './pages/DashboardPage'
import { HistoryPage } from './pages/HistoryPage'
import { JobDetailPage } from './pages/JobDetailPage'
import { SkillInputPage } from './pages/SkillInputPage'
import { SettingsPage } from './pages/SettingsPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<SkillInputPage />} />
        <Route path="analyze" element={<AnalyzePage />} />
        <Route path="sessions/:sessionId" element={<DashboardPage />} />
        <Route path="jobs/:jobId" element={<JobDetailPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
