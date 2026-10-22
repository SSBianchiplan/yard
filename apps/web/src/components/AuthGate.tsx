import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Suspense, lazy, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useLocation } from 'react-router-dom'

import { ChangePasswordModal } from '@/components/ChangePasswordModal'
import { authApi } from '@/lib/api'
import { useAuth } from '@/lib/auth'

// Página inicial carregada sob demanda: Three.js e GSAP não entram no bundle da operação.
export const Landing = lazy(() => import('@/pages/landing/Landing'))

export function LandingPage() {
  return (
    <Suspense fallback={<div className="lp-loading" />}>
      <Landing />
    </Suspense>
  )
}

/**
 * Descobre como a API autentica e, se não for modo aberto, exige sessão.
 *
 * O perfil é relido de `/auth/me` ao abrir: se o administrador tirou um perfil ou
 * desativou a conta, a tela reflete agora — não quando o token vencer.
 */
export function useAuthBootstrap() {
  const setMode = useAuth((state) => state.setMode)
  const config = useQuery({ queryKey: ['auth', 'config'], queryFn: authApi.config, staleTime: Infinity })
  useEffect(() => {
    if (config.data) setMode(config.data.mode)
    // API fora do ar: segue como aberto para a tela mostrar o erro de cada consulta
    if (config.isError) setMode('open')
  }, [config.data, config.isError, setMode])
  return useAuth((state) => state.ready)
}

export function AuthGate({ children }: { children: ReactNode }) {
  const { t } = useTranslation('common')
  const ready = useAuthBootstrap()
  const { mode, token, user, updateUser } = useAuth()
  const location = useLocation()

  const me = useQuery({
    queryKey: ['auth', 'me', token],
    queryFn: authApi.me,
    enabled: ready && mode !== 'open' && Boolean(token),
  })
  useEffect(() => {
    if (me.data) updateUser(me.data)
  }, [me.data, updateUser])

  if (!ready) return <div className="page page__subtitle">{t('state.loading')}</div>
  // Visitante sem sessão na raiz vê a página inicial, não a tela de login.
  if (mode !== 'open' && !token && location.pathname === '/') return <LandingPage />
  if (mode !== 'open' && !token) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return (
    <>
      {children}
      <ChangePasswordModal
        open={mode !== 'open' && Boolean(user?.must_change_password)}
        forced
        onClose={() => undefined}
      />
    </>
  )
}

/** Rota só de administrador: quem não é volta para a torre. */
export function AdminOnly({ children }: { children: ReactNode }) {
  const can = useAuth((state) => state.can)
  if (!can()) return <Navigate to="/" replace />
  return <>{children}</>
}
