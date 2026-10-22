import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { ChangePasswordModal } from '@/components/ChangePasswordModal'
import { yardConfigApi } from '@/lib/api'
import { useAuth } from '@/lib/auth'

import { useYardLive } from '@/lib/live'
import type { Density, Theme } from '@/lib/uiStore'
import { useUiStore } from '@/lib/uiStore'
import { SUPPORTED_LOCALES } from '@/i18n'

export function AppShell() {
  const { t, i18n } = useTranslation('common')
  const { theme, density, setTheme, setDensity, plantCode, setPlantCode } = useUiStore()
  const { connected } = useYardLive()
  const { mode, name, subject, can, signOut } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [changing, setChanging] = useState(false)
  const plants = useQuery({ queryKey: ['plants'], queryFn: yardConfigApi.plants, staleTime: 60_000 })
  const activePlants = (plants.data ?? []).filter((plant) => plant.active)

  return (
    <div className="shell">
      <header className="shell__top">
        <div>
          <div className="shell__brand">
            <img src="/icons/icon.svg" alt="" width={22} height={22} />
            {t('app.name')}
          </div>
          <div className="shell__plant">{t('app.tagline')}</div>
        </div>

        <nav className="shell__nav">
          <NavLink to="/">{t('nav.controlTower')}</NavLink>
          <NavLink to="/gate">{t('nav.gate')}</NavLink>
          <NavLink to="/kiosk">{t('nav.kiosk')}</NavLink>
          <NavLink to="/scheduling">{t('nav.scheduling')}</NavLink>
          <NavLink to="/weighing">{t('nav.weighing')}</NavLink>
          <NavLink to="/moves">{t('nav.moves')}</NavLink>
          <NavLink to="/tower">{t('nav.tower')}</NavLink>
          <NavLink to="/visits">{t('nav.visits')}</NavLink>
          {can() && <NavLink to="/admin/yards">{t('nav.yards')}</NavLink>}
          {can() && <NavLink to="/admin/users">{t('nav.users')}</NavLink>}
        </nav>

        <div className="shell__tools">
          {activePlants.length > 1 && (
            <select
              aria-label={t('user.plant')}
              value={plantCode ?? activePlants[0]?.code ?? ''}
              onChange={(event) => setPlantCode(event.target.value)}
            >
              {activePlants.map((plant) => (
                <option key={plant.id} value={plant.code}>
                  {plant.code} · {plant.name}
                </option>
              ))}
            </select>
          )}

          <span title={connected ? t('label.liveOn') : t('label.liveOff')}>
            <span className={`live-dot ${connected ? '' : 'live-dot--off'}`} />
          </span>

          <select
            aria-label={t('label.language')}
            value={i18n.language}
            onChange={(event) => void i18n.changeLanguage(event.target.value)}
          >
            {SUPPORTED_LOCALES.map((locale) => (
              <option key={locale} value={locale}>
                {locale}
              </option>
            ))}
          </select>

          <select
            aria-label={t('label.theme')}
            value={theme}
            onChange={(event) => setTheme(event.target.value as Theme)}
          >
            <option value="light">{t('theme.light')}</option>
            <option value="dark">{t('theme.dark')}</option>
            <option value="hmi">{t('theme.hmi')}</option>
          </select>

          <select
            aria-label={t('label.density')}
            value={density}
            onChange={(event) => setDensity(event.target.value as Density)}
          >
            <option value="compact">{t('density.compact')}</option>
            <option value="default">{t('density.default')}</option>
            <option value="touch">{t('density.touch')}</option>
          </select>

          {mode !== 'open' && (
            <details className="user-menu">
              <summary title={subject}>{name}</summary>
              <div className="user-menu__panel">
                <span className="page__subtitle">{subject}</span>
                <button type="button" onClick={() => setChanging(true)}>
                  {t('user.changePassword')}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    signOut()
                    queryClient.clear()
                    navigate('/login')
                  }}
                >
                  {t('user.signOut')}
                </button>
              </div>
            </details>
          )}
        </div>
      </header>

      <main className="shell__main">
        <Outlet />
      </main>

      <ChangePasswordModal open={changing} onClose={() => setChanging(false)} />
    </div>
  )
}
