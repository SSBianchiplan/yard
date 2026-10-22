import { Button, DataTable, Input, Select, StatusPill } from '@gplansis/ds'
import type { Column } from '@gplansis/ds'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { VisitDetailModal } from '@/components/VisitDetailModal'
import { useErrorMessage } from '@/components/VisitStatus'
import type { MoveTask } from '@/lib/api'
import { api } from '@/lib/api'
import { currentActor } from '@/lib/auth'
import { useFormat } from '@/lib/format'

const STATE_TONE: Record<string, 'idle' | 'waiting' | 'moving' | 'running' | 'critical'> = {
  proposed: 'idle',
  queued: 'waiting',
  assigned: 'waiting',
  accepted: 'moving',
  in_progress: 'moving',
  confirmed: 'running',
  cancelled: 'idle',
  failed: 'critical',
}

/**
 * Fila do manobrista. Pensada para o PWA: uma tarefa por vez, alvo grande, aceite
 * explícito e confirmação por leitura do QR da vaga.
 *
 * O botão "concluir" digitado existe, mas exige motivo — e vai para o KPI de exceção
 * manual. Confirmar por botão é dizer que fez; ler o QR é provar onde parou.
 */
export function SpotterQueue() {
  const { t } = useTranslation(['moves', 'yard', 'common'])
  const format = useFormat()
  const queryClient = useQueryClient()
  const describeError = useErrorMessage()

  // O tablet do pátio é compartilhado. Se quem está logado for um manobrista
  // cadastrado, é ele; senão, escolhe-se na lista — e é esse código que assina a
  // execução da tarefa. Campo de texto livre aqui seria assinatura em branco.
  const spotters = useQuery({ queryKey: ['moves', 'spotters'], queryFn: api.spotters })
  const [picked, setPicked] = useState<string | null>(null)
  const registered = spotters.data ?? []
  const identity = currentActor()
  const spotter =
    picked ?? (registered.some((s) => s.code === identity) ? identity : registered[0]?.code ?? '')
  const [selected, setSelected] = useState<MoveTask | null>(null)
  const [scanValue, setScanValue] = useState('')
  const [reasonCode, setReasonCode] = useState('')
  const [failure, setFailure] = useState<string | null>(null)
  const [detail, setDetail] = useState<string | null>(null)

  const queue = useQuery({
    queryKey: ['moves', 'queue', spotter],
    queryFn: () => api.moveQueue(spotter),
    refetchInterval: 10_000,
    enabled: Boolean(spotter),
  })
  const deviations = useQuery({
    queryKey: ['moves', 'deviations'],
    queryFn: api.moveDeviations,
    refetchInterval: 30_000,
  })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['moves'] })
    void queryClient.invalidateQueries({ queryKey: ['yard'] })
  }
  const fail = (error: unknown) => setFailure(describeError(error))

  const accept = useMutation({
    mutationFn: (task: MoveTask) => api.acceptMove(task.id, spotter),
    onSuccess: () => {
      setFailure(null)
      refresh()
    },
    onError: fail,
  })
  const start = useMutation({
    mutationFn: (task: MoveTask) => api.startMove(task.id),
    onSuccess: () => {
      setFailure(null)
      refresh()
    },
    onError: fail,
  })
  const confirm = useMutation({
    mutationFn: ({ task, kind }: { task: MoveTask; kind: 'qr' | 'manual' }) =>
      api.confirmMove(task.id, {
        kind,
        value: kind === 'qr' ? scanValue.trim().toUpperCase() : undefined,
        reason_code: kind === 'manual' ? reasonCode || 'QR_DAMAGED' : undefined,
      }),
    onSuccess: () => {
      setFailure(null)
      setScanValue('')
      setSelected(null)
      refresh()
    },
    onError: fail,
  })

  const columns: Column<MoveTask>[] = [
    {
      key: 'plate',
      header: t('yard:visit.column.plate'),
      width: 100,
      pinned: true,
      value: (row) => row.plate ?? '',
    },
    {
      key: 'route',
      header: t('moves:column.route'),
      width: 150,
      render: (row) => `${row.from_slot_code ?? '—'} → ${row.to_slot_code ?? row.to_dock_code ?? '—'}`,
    },
    {
      key: 'cost',
      priority: 'secondary',
      header: t('moves:column.cost'),
      width: 90,
      align: 'right',
      sortable: true,
      value: (row) => Number(row.cost_score),
      render: (row) => format.number(Number(row.cost_score), 1),
    },
    {
      key: 'distance',
      priority: 'secondary',
      header: t('moves:column.distance'),
      width: 100,
      align: 'right',
      value: (row) => Number(row.distance_m ?? 0),
      render: (row) => `${format.number(Number(row.distance_m ?? 0))} m`,
    },
    {
      key: 'state',
      header: t('moves:column.state'),
      width: 130,
      render: (row) => (
        <StatusPill tone={STATE_TONE[row.state] ?? 'idle'}>
          {t(`moves:state.${row.state}`)}
        </StatusPill>
      ),
    },
    {
      key: 'sla',
      priority: 'secondary',
      header: t('moves:column.sla'),
      width: 120,
      align: 'right',
      value: (row) => row.sla_deadline ?? '',
      render: (row) => (row.sla_deadline ? format.time(row.sla_deadline) : '—'),
    },
  ]

  return (
    <div className="page">
      <div className="page__header">
        <h1 className="page__title">{t('moves:title')}</h1>
        <span className="page__subtitle">{t('moves:subtitle')}</span>
      </div>

      {failure && <div className="alert">{failure}</div>}

      <div className="gate">
        <section className="panel">
          <div className="panel__title">
            <span>{t('moves:queue')}</span>
            <span>{format.number(queue.data?.length ?? 0)}</span>
          </div>
          <div className="panel__body">
            <DataTable
              columns={columns}
              rows={queue.data ?? []}
              rowKey={(row) => row.id}
              selectedKey={selected?.id ?? null}
              onRowClick={(row) => setSelected(row)}
              emptyLabel={t('moves:empty')}
              rowHeight={44}
              toolbar={
                <Select
                  label={t('moves:spotter')}
                  value={spotter}
                  onChange={(event) => setPicked(event.target.value)}
                  options={registered.map((person) => ({
                    value: person.code,
                    label: `${person.code} · ${person.full_name}`,
                  }))}
                />
              }
            />
          </div>
        </section>

        <section className="panel">
          <div className="panel__title">{t('moves:task')}</div>
          <div className="form-grid">
            {!selected && <p className="page__subtitle">{t('moves:selectTask')}</p>}
            {selected && (
              <>
                <div className="page__header">
                  <div>
                    <div className="page__title">{selected.plate}</div>
                    <div className="page__subtitle">
                      {selected.from_slot_code ?? '—'} →{' '}
                      {selected.to_slot_code ?? selected.to_dock_code ?? '—'}
                    </div>
                  </div>
                  <Button variant="ghost" onClick={() => setDetail(selected.visit_id)}>
                    {t('yard:detail.openActions')}
                  </Button>
                </div>

                <div className="row-actions">
                  {selected.state === 'queued' && (
                    <Button variant="primary" onClick={() => accept.mutate(selected)}>
                      {t('moves:action.accept')}
                    </Button>
                  )}
                  {selected.state === 'accepted' && (
                    <Button variant="primary" onClick={() => start.mutate(selected)}>
                      {t('moves:action.start')}
                    </Button>
                  )}
                </div>

                {selected.state === 'in_progress' && (
                  <>
                    <Input
                      label={t('moves:scan')}
                      operational
                      hint={t('moves:scanHint')}
                      value={scanValue}
                      onChange={(event) => setScanValue(event.target.value)}
                    />
                    <Button
                      variant="primary"
                      block
                      disabled={!scanValue}
                      onClick={() => confirm.mutate({ task: selected, kind: 'qr' })}
                    >
                      {t('moves:action.confirmScan')}
                    </Button>

                    <details>
                      <summary className="page__subtitle">{t('moves:manual.title')}</summary>
                      <div className="form-grid form-grid--bare">
                        <Input
                          label={t('moves:manual.reason')}
                          operational
                          value={reasonCode}
                          onChange={(event) => setReasonCode(event.target.value)}
                          hint={t('moves:manual.hint')}
                        />
                        <Button onClick={() => confirm.mutate({ task: selected, kind: 'manual' })}>
                          {t('moves:action.confirmManual')}
                        </Button>
                      </div>
                    </details>
                  </>
                )}
              </>
            )}

            <div>
              <div className="panel__title" style={{ padding: 0, border: 0, background: 'none' }}>
                {t('moves:deviations')}
              </div>
              <ul className="detail-list">
                {(deviations.data ?? []).slice(0, 8).map((deviation) => (
                  <li key={`${deviation.detected_at}-${deviation.vehicle_id}`}>
                    <StatusPill tone="critical">{t('moves:deviation')}</StatusPill>{' '}
                    <span className="page__subtitle">{format.dateTime(deviation.detected_at)}</span>
                  </li>
                ))}
                {(deviations.data ?? []).length === 0 && (
                  <li className="page__subtitle">{t('moves:noDeviations')}</li>
                )}
              </ul>
            </div>
          </div>
        </section>
      </div>

      <VisitDetailModal visitId={detail} onClose={() => setDetail(null)} />
    </div>
  )
}
