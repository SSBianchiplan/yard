import { Button, Input } from '@gplansis/ds'
import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'

import { useAuthBootstrap } from '@/components/AuthGate'
import { useErrorMessage } from '@/components/VisitStatus'
import { authApi } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useInstallPrompt } from '@/lib/pwa'

export function Login() {
  const { t } = useTranslation(['admin', 'common'])
  const errorMessage = useErrorMessage()
  const ready = useAuthBootstrap()
  const { mode, token, signIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const install = useInstallPrompt()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const from = (location.state as { from?: string } | null)?.from ?? '/'

  const login = useMutation({
    mutationFn: () => authApi.login(email.trim(), password),
    onSuccess: (session) => {
      signIn(session.token, session.expires_at, session.user)
      navigate(from, { replace: true })
    },
  })

  if (ready && (mode === 'open' || token)) return <Navigate to={from} replace />

  return (
    <main className="login">
      <form
        className="login__card"
        onSubmit={(event) => {
          event.preventDefault()
          login.mutate()
        }}
      >
        <div className="login__brand">
          <img src="/icons/icon.svg" alt="" width={56} height={56} />
          <div>
            <div className="login__name">{t('common:app.name')}</div>
            <div className="page__subtitle">{t('admin:auth.subtitle')}</div>
          </div>
        </div>

        <h1 className="page__title">{t('admin:auth.title')}</h1>

        <Input
          label={t('admin:auth.email')}
          type="email"
          autoComplete="username"
          inputMode="email"
          autoFocus
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <Input
          label={t('admin:auth.password')}
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />

        {login.error && (
          <div className="alert" role="alert">
            {errorMessage(login.error)}
          </div>
        )}

        <Button type="submit" variant="primary" block disabled={login.isPending || !ready}>
          {login.isPending ? t('admin:auth.submitting') : t('admin:auth.submit')}
        </Button>
        <p className="page__subtitle">{t('admin:auth.forgot')}</p>
        <Link className="page__subtitle" to="/inicio">
          {t('admin:auth.home')}
        </Link>
        {install.available && (
          <Button variant="ghost" block onClick={install.prompt}>
            {t('admin:auth.install')}
          </Button>
        )}
      </form>
    </main>
  )
}
