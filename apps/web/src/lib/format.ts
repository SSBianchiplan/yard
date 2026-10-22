/** Formatação por locale via Intl. Fuso de exibição é o da PLANTA, não o do navegador. */

import { useTranslation } from 'react-i18next'

// ASSUNÇÃO: uma planta por instância na Fatia 1 — o fuso vem de /yard/map e cai aqui.
let plantTimeZone = 'America/Sao_Paulo'

export function setPlantTimeZone(timeZone: string) {
  plantTimeZone = timeZone
}

export function getPlantTimeZone() {
  return plantTimeZone
}

export type WeightUnit = 'kg' | 't' | 'lb'

/**
 * Qualidade do dado: o campo fala 'good' (OPC UA/Sparkplug), a UI fala 'fresh'.
 * A tradução mora aqui, num lugar só — dois vocabulários soltos viram bug de cor.
 */
export type DataQuality = 'fresh' | 'stale' | 'invalid' | 'no_comm'

export function toDataQuality(fieldQuality: string | null | undefined): DataQuality {
  switch (fieldQuality) {
    case 'good':
      return 'fresh'
    case 'stale':
    case 'invalid':
    case 'no_comm':
      return fieldQuality
    default:
      return 'no_comm'
  }
}

export function formatDateTime(locale: string, iso: string | null | undefined) {
  if (!iso) return '—'
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'short',
    timeStyle: 'short',
    timeZone: plantTimeZone,
  }).format(new Date(iso))
}

export function formatTime(locale: string, iso: string | null | undefined) {
  if (!iso) return '—'
  return new Intl.DateTimeFormat(locale, {
    timeStyle: 'medium',
    timeZone: plantTimeZone,
  }).format(new Date(iso))
}

export function formatNumber(locale: string, value: number, digits = 0) {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value)
}

/** Peso trafega em kg no dado; a unidade de exibição é configurável. */
export function formatWeight(locale: string, kg: number, unit: WeightUnit = 'kg') {
  const value = unit === 't' ? kg / 1000 : unit === 'lb' ? kg * 2.2046226218 : kg
  return `${formatNumber(locale, value, unit === 't' ? 3 : 0)} ${unit}`
}

export function useFormat() {
  const { i18n, t } = useTranslation('common')
  const locale = i18n.language

  return {
    locale,
    dateTime: (iso: string | null | undefined) => formatDateTime(locale, iso),
    time: (iso: string | null | undefined) => formatTime(locale, iso),
    number: (value: number, digits = 0) => formatNumber(locale, value, digits),
    percent: (value: number) => `${formatNumber(locale, value, 1)}${t('unit.percent')}`,
    weight: (kg: number, unit: WeightUnit = 'kg') => formatWeight(locale, kg, unit),
    duration: (seconds: number) => {
      const total = Math.max(0, Math.round(seconds / 60))
      const hours = Math.floor(total / 60)
      const minutes = total % 60
      return hours > 0
        ? t('time.hoursMinutes', { hours, minutes: String(minutes).padStart(2, '0') })
        : t('time.minutes', { minutes })
    },
  }
}
