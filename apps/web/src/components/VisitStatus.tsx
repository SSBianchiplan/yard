import { StatusPill } from '@gplansis/ds'
import type { StatusTone } from '@gplansis/ds'
import { useTranslation } from 'react-i18next'

import type { VisitState } from '@/lib/api'

/** Estado é código estável no banco; a cor e o rótulo nascem aqui. */
const TONE: Record<VisitState, StatusTone> = {
  expected: 'idle',
  at_gate_in: 'waiting',
  in_yard: 'running',
  at_dock: 'moving',
  at_gate_out: 'waiting',
  departed: 'stopped',
  rejected: 'critical',
}

export function VisitStatus({ state, blocked }: { state: VisitState; blocked?: boolean }) {
  const { t } = useTranslation('yard')
  return (
    <StatusPill tone={blocked ? 'critical' : TONE[state]} solid={blocked}>
      {t(`visit.state.${state}`)}
    </StatusPill>
  )
}

export function useErrorMessage() {
  const { t } = useTranslation('errors')
  return (error: unknown) => {
    const code = (error as { code?: string })?.code ?? 'ERR_UNKNOWN'
    const params = (error as { params?: Record<string, unknown> })?.params ?? {}
    return t(code, { ...params, defaultValue: t('ERR_UNKNOWN') })
  }
}
