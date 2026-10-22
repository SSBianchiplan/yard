import { Button, DetailRow, Modal, Select, StatusPill } from '@gplansis/ds'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { VisitStatus, useErrorMessage } from '@/components/VisitStatus'
import { api } from '@/lib/api'
import { useUiStore } from '@/lib/uiStore'
import { useFormat } from '@/lib/format'

export interface VisitDetailModalProps {
  visitId: string | null
  /** Vaga/doca de onde o modal foi aberto, para dar contexto ao título. */
  originCode?: string | null
  onClose: () => void
}

/**
 * O que está nesta vaga, e o que dá para fazer com isso.
 *
 * O mapa mostra o pátio; o operador clica e precisa **agir** — mandar manobrar, chamar
 * para a balança, encostar na doca, liberar a saída. Modal que só informa obriga a
 * procurar a mesma visita noutra tela, e é aí que o tempo de pátio vira dwell.
 *
 * Cada ação é a mesma regra do backend: pendência aberta bloqueia saída, tarefa ativa
 * impede outra, pesagem exige ticket. A tela não reimplementa nada disso — ela mostra
 * o código de erro traduzido quando a regra recusa.
 */
export function VisitDetailModal({ visitId, originCode, onClose }: VisitDetailModalProps) {
  const { t } = useTranslation(['yard', 'moves', 'weighing', 'common'])
  const format = useFormat()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const describeError = useErrorMessage()

  const [targetSlot, setTargetSlot] = useState('')
  const [targetDock, setTargetDock] = useState('')
  const [failure, setFailure] = useState<string | null>(null)

  const open = Boolean(visitId)
  const visit = useQuery({
    queryKey: ['visits', 'detail', visitId],
    queryFn: () => api.visit(visitId as string),
    enabled: open,
  })
  const map = useQuery({ queryKey: ['yard', 'map'], queryFn: () => api.yardMap(useUiStore.getState().plantCode), enabled: open })
  const tickets = useQuery({
    queryKey: ['weighing', 'tickets', visit.data?.reference],
    queryFn: () => api.weighingTickets(visit.data?.reference),
    enabled: open && Boolean(visit.data?.reference),
  })
  const holds = useQuery({
    queryKey: ['holds', visitId],
    queryFn: () => api.holds(visitId as string),
    enabled: open,
  })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['visits'] })
    void queryClient.invalidateQueries({ queryKey: ['yard'] })
    void queryClient.invalidateQueries({ queryKey: ['moves'] })
    void queryClient.invalidateQueries({ queryKey: ['overview'] })
  }
  const fail = (error: unknown) => setFailure(describeError(error))
  const done = () => {
    setFailure(null)
    refresh()
  }

  const createMove = useMutation({
    mutationFn: () =>
      api.createMove({
        visit_reference: visit.data?.reference as string,
        to_slot_code: targetSlot || undefined,
        to_dock_code: targetSlot ? undefined : targetDock || undefined,
        priority_rank: 200,
      }),
    onSuccess: () => {
      done()
      navigate('/moves')
    },
    onError: fail,
  })

  const sendToDock = useMutation({
    mutationFn: () => api.assignDock(visitId as string, targetDock),
    onSuccess: done,
    onError: fail,
  })

  const gateOut = useMutation({
    mutationFn: () => api.gateOut(visitId as string),
    onSuccess: () => {
      done()
      onClose()
    },
    onError: fail,
  })

  const openWeighing = useMutation({
    mutationFn: () =>
      api.openWeighing({
        visit_reference: visit.data?.reference as string,
        scale_code: map.data?.scales[0]?.code ?? 'SCALE-01',
        document_number: visit.data?.document_number ?? undefined,
      }),
    onSuccess: (ticket) => {
      done()
      navigate(`/weighing?ticket=${ticket.id}`)
    },
    onError: fail,
  })

  const data = visit.data
  const freeSlots = (map.data?.slots ?? []).filter(
    (slot) => !slot.occupied && slot.status === 'available',
  )
  const freeDocks = (map.data?.docks ?? []).filter((dock) => dock.status === 'available')
  const openTicket = (tickets.data ?? []).find((ticket) => ticket.state !== 'closed')
  const openHolds = (holds.data ?? []).filter((hold) => !hold.released_at)

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="wide"
      closeLabel={t('common:action.close')}
      title={data ? `${data.plate} · ${data.reference}` : (originCode ?? '')}
      subtitle={
        data
          ? t('yard:detail.subtitle', {
              operation: t(`yard:operation.${data.operation_type_code}`),
              position: data.slot_code ?? data.dock_code ?? originCode ?? '—',
            })
          : undefined
      }
      actions={
        data && (
          <>
            <Button
              onClick={() => openWeighing.mutate()}
              disabled={Boolean(openTicket) || openWeighing.isPending}
              title={openTicket ? t('yard:detail.ticketOpen', { reference: openTicket.reference }) : undefined}
            >
              {openTicket ? t('yard:detail.goToWeighing') : t('yard:detail.startWeighing')}
            </Button>
            <Button
              onClick={() => createMove.mutate()}
              disabled={(!targetSlot && !targetDock) || createMove.isPending}
            >
              {t('yard:detail.createMove')}
            </Button>
            <Button
              onClick={() => sendToDock.mutate()}
              disabled={!targetDock || data.state !== 'in_yard' || sendToDock.isPending}
            >
              {t('yard:detail.sendToDock')}
            </Button>
            <Button
              variant="primary"
              onClick={() => gateOut.mutate()}
              disabled={Boolean(data.blocked_reason_code) || openHolds.length > 0}
              title={
                data.blocked_reason_code
                  ? t('yard:visit.blocked', { reason: data.blocked_reason_code })
                  : undefined
              }
            >
              {t('yard:visit.action.gateOut')}
            </Button>
          </>
        )
      }
    >
      {failure && <div className="alert">{failure}</div>}
      {!data && <p className="page__subtitle">{t('common:state.loading')}</p>}

      {data && (
        <>
          {(data.blocked_reason_code || openHolds.length > 0) && (
            <div className="alert">
              {t('yard:visit.blocked', {
                reason: data.blocked_reason_code ?? openHolds[0]?.reason_code,
              })}
            </div>
          )}

          <div className="modal-grid">
            <div>
              <DetailRow label={t('yard:visit.column.state')}>
                <VisitStatus state={data.state} blocked={Boolean(data.blocked_reason_code)} />
              </DetailRow>
              <DetailRow label={t('yard:visit.column.driver')}>{data.driver_name}</DetailRow>
              <DetailRow label={t('yard:visit.column.carrier')}>
                {data.carrier_name ?? '—'}
              </DetailRow>
              <DetailRow label={t('yard:visit.column.product')}>
                {data.product_name ?? '—'}
              </DetailRow>
              <DetailRow label={t('yard:visit.column.document')}>
                {data.document_number ?? '—'}
              </DetailRow>
            </div>
            <div>
              <DetailRow label={t('yard:visit.column.arrived')}>
                {format.dateTime(data.arrived_at)}
              </DetailRow>
              <DetailRow label={t('yard:visit.column.gateIn')}>
                {format.dateTime(data.gate_in_at)}
              </DetailRow>
              <DetailRow label={t('yard:visit.column.dwell')}>
                <span
                  style={{
                    color:
                      data.dwell_seconds > data.target_dwell_minutes * 60
                        ? 'var(--color-alarm-high)'
                        : undefined,
                  }}
                >
                  {format.duration(data.dwell_seconds)}
                </span>
              </DetailRow>
              <DetailRow label={t('yard:detail.target')}>
                {format.duration(data.target_dwell_minutes * 60)}
              </DetailRow>
              <DetailRow label={t('yard:visit.column.slot')}>
                {data.slot_code ?? data.dock_code ?? '—'}
              </DetailRow>
            </div>
          </div>

          {/* Pesagens desta visita: o vínculo balança × visita fica explícito aqui. */}
          <section>
            <h3 className="modal-section">{t('weighing:tickets')}</h3>
            {(tickets.data ?? []).length === 0 && (
              <p className="page__subtitle">{t('weighing:empty')}</p>
            )}
            <ul className="detail-list">
              {(tickets.data ?? []).map((ticket) => (
                <li key={ticket.id} className="row-actions">
                  <StatusPill tone={ticket.state === 'closed' ? 'stopped' : 'running'}>
                    {t(`weighing:state.${ticket.state}`)}
                  </StatusPill>
                  <span>{ticket.reference}</span>
                  <span className="page__subtitle">
                    {ticket.net_kg ? format.weight(ticket.net_kg) : '—'}
                    {ticket.divergence_pct !== null &&
                      ` · ${format.percent(Number(ticket.divergence_pct))}`}
                  </span>
                  <Button variant="ghost" onClick={() => navigate(`/weighing?ticket=${ticket.id}`)}>
                    {t('yard:detail.open')}
                  </Button>
                </li>
              ))}
            </ul>
          </section>

          {/* Destino da manobra: escolher aqui é o que transforma o mapa em ação. */}
          <section className="modal-grid">
            <Select
              label={t('yard:detail.targetSlot')}
              value={targetSlot}
              placeholder={t('gate:checkin.placeholder.select')}
              onChange={(event) => {
                setTargetSlot(event.target.value)
                setTargetDock('')
              }}
              options={freeSlots.slice(0, 60).map((slot) => ({
                value: slot.code,
                label: slot.code,
              }))}
            />
            <Select
              label={t('yard:detail.targetDock')}
              value={targetDock}
              placeholder={t('gate:checkin.placeholder.select')}
              onChange={(event) => {
                setTargetDock(event.target.value)
                setTargetSlot('')
              }}
              options={freeDocks.map((dock) => ({ value: dock.code, label: dock.code }))}
            />
          </section>

          <section>
            <h3 className="modal-section">{t('yard:visit.events')}</h3>
            <ul className="timeline-list">
              {data.events.slice(0, 8).map((event) => (
                <li key={`${event.occurred_at}-${event.event_type}`}>
                  <span className="timeline-list__time">{format.dateTime(event.occurred_at)}</span>
                  <span className="row-actions">
                    <StatusPill tone={event.source === 'manual' ? 'waiting' : 'running'}>
                      {t(`yard:visit.eventSource.${event.source}`)}
                    </StatusPill>
                    <span>{event.event_type}</span>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </Modal>
  )
}
