import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'

import { AppShell } from '@/components/AppShell'
import { AdminOnly, AuthGate, LandingPage } from '@/components/AuthGate'
import { ControlTower } from '@/pages/ControlTower'
import { ControlTowerAI } from '@/pages/ControlTowerAI'
import { GateConsole } from '@/pages/GateConsole'
import { GateKiosk } from '@/pages/GateKiosk'
import { Login } from '@/pages/Login'
import { Scheduling } from '@/pages/Scheduling'
import { SpotterQueue } from '@/pages/SpotterQueue'
import { Weighing } from '@/pages/Weighing'
import { VisitsList } from '@/pages/VisitsList'
import { Users } from '@/pages/admin/Users'
import { YardEditor } from '@/pages/admin/YardEditor'
import { Yards } from '@/pages/admin/Yards'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: true, staleTime: 5_000 },
  },
})

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="login" element={<Login />} />
          <Route path="inicio" element={<LandingPage />} />
          <Route
            element={
              <AuthGate>
                <AppShell />
              </AuthGate>
            }
          >
            <Route index element={<ControlTower />} />
            <Route path="gate" element={<GateConsole />} />
            <Route path="kiosk" element={<GateKiosk />} />
            <Route path="scheduling" element={<Scheduling />} />
            <Route path="weighing" element={<Weighing />} />
            <Route path="moves" element={<SpotterQueue />} />
            <Route path="tower" element={<ControlTowerAI />} />
            <Route path="visits" element={<VisitsList />} />
            <Route
              path="admin/users"
              element={
                <AdminOnly>
                  <Users />
                </AdminOnly>
              }
            />
            <Route
              path="admin/yards"
              element={
                <AdminOnly>
                  <Yards />
                </AdminOnly>
              }
            />
            <Route
              path="admin/yards/:plantId"
              element={
                <AdminOnly>
                  <YardEditor />
                </AdminOnly>
              }
            />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
