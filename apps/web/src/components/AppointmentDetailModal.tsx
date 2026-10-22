import { Button, DetailRow, Input, Modal, Select, StatusPill } from '@gplansis/ds'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useErrorMessage } from '@/components/VisitStatus'
import type { Appointment } from '@/lib/api'
import { api } from '@/lib/api'
import { currentActor } from '@/lib/auth'
import { useFormat } from '@/lib/format'

const STATE_TONE: Record<
  string,
  'running' | 'idle' | 'waiting' | 'stopped' | 'moving' | 'critical'
> = {
  draft: 'idle',
  requested: 'waiting',
  confirmed: 'running',
  checked_in: 'moving',
  in_progress: 'moving',
  completed: 'stopped',
  cancelled: 'critical',
  no_show: 'critical',
  rescheduled: 'waiting',
}

export interface AppointmentDetailModalProps {
  appointment: Appointment | null
  /** Docas para reprogramar sem sair do modal. */
  docks: { code: string }[]
  onClose: () => void
}

/**
 * O que é esta janela, e o que dá para fazer com ela.
 *
 * A faixa no gráfico mostra quando; o programador clica porque precisa decidir — confirmar
 * e reservar a vaga, trocar de doca, marcar não comparecimento, cancelar. Antes, clicar só
 * selecionava e a informação aparecia num painel lá embaixo, fora do campo de visão de quem
 * estava olhando o Gantt.
 *
 * O rastro de mudanças vem junto: reprogramação sem motivo não existe, e quem olha a janela
 * precisa ver quantas vezes ela já andou e por quê.
 */
export function AppointmentDetailModal({
  appointment,
  docks,
  onClose,
}: AppointmentDetailModalProps) {
  const { t } = useTranslation(['scheduling', 'common'])
  const format = useFormat()
  const queryClient = useQueryClient()
  const describeError = useErrorMessage()

  const [reason, setReason] = useState('')
  const [failure, setFailure] = useState<string | null>(null)

  const open = Boolean(appointment)
  const id = appointment?.id

  const history = useQuery({
    queryKey: ['appointments', 'history', id],
    queryFn: () => api.appointmentHistory(id as string),
    enabled: open,
  })

  // Impacto de empurrar esta janela 30 min adiante: o programador decide vendo o custo,
  // não depois de soltar a faixa em cima de outra.
  const impact = useQuery({
    queryKey: ['appointments', 'impact', id],
    queryFn: () => {
      const current = appointment as Appointment
      const starts = new Date(new Date(current.starts_at).getTime() + 30 * 60000)
      const duration =
        new Date(current.ends_at).getTime() - new Date(current.starts_at).getTime()
      return api.appointmentImpact(
        current.id,
        starts.toISOString(),
        new Date(starts.getTime() + duration).toISOString(),
      )
    },
    enabled: open,
  })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['appointments'] })
    void queryClient.invalidateQueries({ queryKey: ['yard'] })
  }

  const confirm = useMutation({
    mutationFn: (current: Appointment) => api.confirmAppointment(current.id, current.version),
    onSuccess: () => {
      setFailure(null)
      refresh()
      onClose()
    },
    onError: (error) => setFailure(describeError(error)),
  })

  const reschedule = useMutation({
    mutationFn: ({ current, dockCode }: { current: Appointment; dockCode: string }) => {
      const duration =
        new Date(current.ends_at).getTime() - new Date(current.starts_at).getTime()
      const starts = new Date(current.starts_at)
      return api.rescheduleAppointment(current.id, {
        starts_at: starts.toISOString(),
        ends_at: new Date(starts.getTime() + duration).toISOString(),
        dock_code: dockCode,
        // Reprogramação sem motivo não existe — a API recusa e o banco também.
        reason_code: reason || 'OPERATIONAL',
        version: current.version,
      })
    },
    onSuccess: () => {
      setFailure(null)
      refresh()
    },
    onError: (error) => setFailure(describeError(error)),
  })

  const noShow = useMutation({
    mutationFn: (current: Appointment) => api.noShowAppointment(current.id, currentActor()),
    onSuccess: () => {
      setFailure(null)
      refresh()
      onClose()
    },
    onError: (error) => setFailure(describeError(error)),
  })

  const cancel = useMutation({
    mutationFn: (current: Appointment) =>
      api.cancelAppointment(current.id, {
        reason_code: reason || 'CARRIER_REQUEST',
        version: current.version,
      }),
    onSuccess: () => {
      setFailure(null)
      refresh()
      onClose()
    },
    onError: (error) => setFailure(describeError(error)),
  })

  const entries = history.data ?? []

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={appointment?.reference ?? ''}
      subtitle={
        appointment
          ? `${appointment.dock_code} · ${appointment.plate} · ${format.dateTime(
              appointment.starts_at,
            )}`
          : undefined
      }
      closeLabel={t('common:action.close')}
      actions={
        appointment && (
          <>
            {appointment.state === 'requested' && (
              <Button variant="primary" onClick={() => confirm.mutate(appointment)}>
                {t('scheduling:form.confirm')}
              </Button>
            )}
            {appointment.state === 'confirmed' && (
              <Button onClick={() => noShow.mutate(appointment)}>{t('scheduling:noShow')}</Button>
            )}
            <Button variant="danger" onClick={() => cancel.mutate(appointment)}>
              {t('scheduling:cancel.submit')}
            </Button>
          </>
        )
      }
    >
      {failure && <div className="alert">{failure}</div>}

      {appointment && (
        <div className="stack">
          <div>
            <DetailRow label={t('scheduling:column.state')}>
              <StatusPill tone={STATE_TONE[appointment.state] ?? 'idle'}>
                {t(`scheduling:state.${appointment.state}`)}
              </StatusPill>
            </DetailRow>
            <DetailRow label={t('scheduling:column.window')}>
              {format.dateTime(appointment.starts_at)} · {format.time(appointment.ends_at)}
            </DetailRow>
            <DetailRow label={t('scheduling:column.dock')}>{appointment.dock_code}</DetailRow>
            <DetailRow label={t('scheduling:column.plate')}>{appointment.plate}</DetailRow>
            <DetailRow label={t('scheduling:column.priority')}>
              {appointment.priority_code
                ? t(`scheduling:priority.${appointment.priority_code}`)
                : t('scheduling:priority.none')}
            </DetailRow>
            <DetailRow label={t('scheduling:column.channel')}>
              {t(`scheduling:channel.${appointment.channel}`)}
            </DetailRow>
            <DetailRow label={t('scheduling:column.slot')}>
              {appointment.slot_code ?? t('scheduling:detail.noSlot')}
            </DetailRow>
          </div>

          <div className="stack">
            <span className="page__subtitle">{t('scheduling:reschedule.title')}</span>
            <Input
              label={t('scheduling:reschedule.reason')}
              operational
              placeholder={t('scheduling:reschedule.reasonPlaceholder')}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
            <Select
              label={t('scheduling:column.dock')}
              value={appointment.dock_code}
              onChange={(event) =>
                reschedule.mutate({ current: appointment, dockCode: event.target.value })
              }
              options={docks.map((dock) => ({ value: dock.code, label: dock.code }))}
            />
            {impact.data && (
              <span className="page__subtitle">
                {impact.data.displaced_appointments > 0
                  ? t('scheduling:reschedule.impact', {
                      count: impact.data.displaced_appointments,
                      minutes: impact.data.delayed_minutes,
                    })
                  : t('scheduling:reschedule.noImpact')}
              </span>
            )}
          </div>

          <div className="stack">
            <span className="page__subtitle">{t('scheduling:history.title')}</span>
            {entries.length === 0 && (
              <span className="page__subtitle">{t('scheduling:history.empty')}</span>
            )}
            <ul className="timeline-list">
              {entries.map((entry) => (
                <li key={entry.occurred_at}>
                  <span className="timeline-list__time">{format.dateTime(entry.occurred_at)}</span>
                  <span>
                    {entry.from_state ? t(`scheduling:state.${entry.from_state}`) : '—'}
                    {' → '}
                    {entry.to_state ? t(`scheduling:state.${entry.to_state}`) : '—'}
                    {entry.reason_code ? ` · ${entry.reason_code}` : ''}
                  </span>
                  {typeof entry.impact_json?.displaced_appointments === 'number' && (
                    <span className="page__subtitle">
                      {t('scheduling:reschedule.impact', {
                        count: entry.impact_json.displaced_appointments,
                        minutes: entry.impact_json.delayed_minutes ?? 0,
                      })}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </Modal>
  )
}
