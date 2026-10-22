import { Button, DataTable, Input, ScaleDisplay, Select, StatusPill } from '@gplansis/ds'
import type { Column } from '@gplansis/ds'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { useErrorMessage } from '@/components/VisitStatus'
import type { WeighingTicket } from '@/lib/api'
import { api } from '@/lib/api'
import { useUiStore } from '@/lib/uiStore'
import { currentActor } from '@/lib/auth'
import { toDataQuality, useFormat } from '@/lib/format'

/**
 * Console de balança. Fluxo guiado de um passo por vez (padrão Tulip): o balanceiro vê
 * o peso grande, captura bruto, captura tara, fecha. Peso instável não deixa capturar —
 * o botão fica desabilitado, não adianta insistir.
 */
export function Weighing() {
  const { t } = useTranslation(['weighing', 'yard', 'common'])
  const format = useFormat()
  const queryClient = useQueryClient()
  const describeError = useErrorMessage()
  const actor = currentActor()

  const [scaleCode, setScaleCode] = useState('SCALE-01')
  // O modal da visita manda para cá com `?ticket=` — o balanceiro cai direto no
  // ticket daquele caminhão, sem procurar na lista.
  const [params, setParams] = useSearchParams()
  const [ticketId, setTicketId] = useState<string | null>(params.get('ticket'))

  useEffect(() => {
    const fromUrl = params.get('ticket')
    if (fromUrl && fromUrl !== ticketId) setTicketId(fromUrl)
    // só a URL dispara: incluir ticketId faria o efeito brigar com a própria escolha
  }, [params])
  const [visitReference, setVisitReference] = useState('')
  const [documentNet, setDocumentNet] = useState('')
  const [manualWeight, setManualWeight] = useState('')
  const [reasonCode, setReasonCode] = useState('')
  const [secondFactor, setSecondFactor] = useState('')
  const [failure, setFailure] = useState<string | null>(null)

  const map = useQuery({ queryKey: ['yard', 'map'], queryFn: () => api.yardMap(useUiStore.getState().plantCode) })
  const live = useQuery({
    queryKey: ['weighing', 'live', scaleCode],
    queryFn: () => api.scaleLive(scaleCode),
    // 1s enquanto há ticket aberto — display de balança parado é quadro pintado.
    // Sem ticket, 5s: não faz sentido interrogar o indicador o dia inteiro.
    refetchInterval: ticketId ? 1000 : 5000,
    retry: false,
  })
  const tickets = useQuery({
    queryKey: ['weighing', 'tickets'],
    queryFn: () => api.weighingTickets(),
    refetchInterval: 15_000,
  })
  const ticket = useQuery({
    queryKey: ['weighing', 'ticket', ticketId],
    queryFn: () => api.weighingTicket(ticketId as string),
    enabled: Boolean(ticketId),
  })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['weighing'] })
    void queryClient.invalidateQueries({ queryKey: ['visits'] })
  }
  const fail = (error: unknown) => setFailure(describeError(error))

  const open = useMutation({
    mutationFn: () =>
      api.openWeighing({
        visit_reference: visitReference.trim(),
        scale_code: scaleCode,
        document_net_kg: documentNet ? Number(documentNet) : undefined,
        operator: actor,
      }),
    onSuccess: (created) => {
      setFailure(null)
      setTicketId(created.id)
      refresh()
    },
    onError: fail,
  })

  const capture = useMutation({
    mutationFn: (kind: 'gross' | 'tare') =>
      api.captureWeighing(ticketId as string, {
        kind,
        vehicle_positioned: true,
        image_ref: `s3://yard/weighing/${ticketId}-${kind}.jpg`,
        operator: actor,
        manual_weight_kg: manualWeight ? Number(manualWeight) : undefined,
        reason_code: reasonCode || undefined,
        second_factor_user: secondFactor || undefined,
      }),
    onSuccess: () => {
      setFailure(null)
      setManualWeight('')
      refresh()
    },
    onError: fail,
  })

  const close = useMutation({
    mutationFn: () =>
      api.closeWeighing(ticketId as string, {
        document_net_kg: documentNet ? Number(documentNet) : undefined,
      }),
    onSuccess: () => {
      setFailure(null)
      refresh()
    },
    onError: fail,
  })

  const reading = live.data
  // Peso manual exige motivo E segundo fator — a API recusa sem os dois, então o botão
  // recusa também: descobrir a regra depois do clique desperdiça o tempo do operador.
  const manualComplete = Boolean(manualWeight && reasonCode && secondFactor)
  const readingUsable = Boolean(reading?.stable) && toDataQuality(reading?.quality) === 'fresh'
  const canCapture = Boolean(ticketId) && (readingUsable || manualComplete)

  const columns: Column<WeighingTicket>[] = [
    {
      key: 'reference',
      header: t('weighing:column.reference'),
      width: 160,
      pinned: true,
      sortable: true,
      value: (row) => row.reference,
    },
    { key: 'plate', header: t('yard:visit.column.plate'), width: 100, value: (row) => row.plate ?? '' },
    {
      key: 'state',
      header: t('weighing:column.state'),
      width: 130,
      render: (row) => (
        <StatusPill tone={row.state === 'closed' ? 'stopped' : 'running'}>
          {t(`weighing:state.${row.state}`)}
        </StatusPill>
      ),
    },
    {
      key: 'gross',
      priority: 'secondary',
      header: t('weighing:column.gross'),
      width: 110,
      align: 'right',
      value: (row) => row.gross_kg ?? 0,
      render: (row) => (row.gross_kg ? format.weight(row.gross_kg) : '—'),
    },
    {
      key: 'tare',
      priority: 'secondary',
      header: t('weighing:column.tare'),
      width: 110,
      align: 'right',
      value: (row) => row.tare_kg ?? 0,
      render: (row) =>
        row.tare_kg
          ? `${format.weight(row.tare_kg)} · ${t(`weighing:tareSource.${row.tare_source ?? 'registered'}`)}`
          : '—',
    },
    {
      key: 'net',
      header: t('weighing:column.net'),
      width: 110,
      align: 'right',
      sortable: true,
      value: (row) => row.net_kg ?? 0,
      render: (row) => (row.net_kg ? format.weight(row.net_kg) : '—'),
    },
    {
      key: 'divergence',
      priority: 'secondary',
      header: t('weighing:column.divergence'),
      width: 130,
      align: 'right',
      render: (row) =>
        row.divergence_pct === null || row.divergence_pct === undefined ? (
          '—'
        ) : (
          <StatusPill tone={row.within_tolerance ? 'running' : 'critical'}>
            {format.percent(Number(row.divergence_pct))}
          </StatusPill>
        ),
    },
    {
      key: 'source',
      priority: 'detail',
      header: t('weighing:column.source'),
      width: 110,
      render: (row) => t(`weighing:source.${row.source}`),
    },
    {
      key: 'hash',
      priority: 'detail',
      header: t('weighing:column.hash'),
      width: 130,
      render: (row) => (row.integrity_hash ? row.integrity_hash.slice(0, 12) : '—'),
    },
  ]

  return (
    <div className="page">
      <div className="page__header">
        <h1 className="page__title">{t('weighing:title')}</h1>
        <span className="page__subtitle">{t('weighing:subtitle')}</span>
      </div>

      {failure && <div className="alert">{failure}</div>}
      {ticket.data?.within_tolerance === false && (
        <div className="alert">
          {t('weighing:divergenceBlocks', {
            value: format.percent(Number(ticket.data.divergence_pct ?? 0)),
          })}
        </div>
      )}

      <div className="gate">
        <section className="panel">
          <div className="panel__title">{t('weighing:console')}</div>
          <div className="form-grid">
            <Select
              label={t('weighing:field.scale')}
              value={scaleCode}
              onChange={(event) => setScaleCode(event.target.value)}
              options={(map.data?.scales ?? []).map((scale) => ({
                value: scale.code,
                label: scale.code,
              }))}
            />

            <ScaleDisplay
              scaleCode={scaleCode}
              weightKg={reading?.weight_kg ?? 0}
              formattedWeight={format.weight(reading?.weight_kg ?? 0)}
              stable={Boolean(reading?.stable)}
              quality={live.isError ? 'no_comm' : toDataQuality(reading?.quality)}
              labels={{
                stable: t('weighing:reading.stable'),
                unstable: t('weighing:reading.unstable'),
                quality: t('weighing:reading.noComm'),
                scale: t('weighing:field.scale'),
              }}
              reference={
                ticket.data?.tare_kg
                  ? { label: t('weighing:column.tare'), value: format.weight(ticket.data.tare_kg) }
                  : undefined
              }
            />

            {!ticketId && (
              <>
                <Input
                  label={t('weighing:field.visit')}
                  operational
                  placeholder={t('weighing:field.visitPlaceholder')}
                  value={visitReference}
                  onChange={(event) => setVisitReference(event.target.value)}
                />
                <Input
                  label={t('weighing:field.documentNet')}
                  operational
                  hint={t('weighing:field.documentNetHint')}
                  value={documentNet}
                  onChange={(event) => setDocumentNet(event.target.value)}
                />
                <Button variant="primary" block onClick={() => open.mutate()}>
                  {t('weighing:action.open')}
                </Button>
              </>
            )}

            {ticketId && ticket.data && (
              <div className="page__subtitle">
                {t('weighing:linkedVisit', {
                  visit: ticket.data.visit_reference ?? '—',
                  plate: ticket.data.plate ?? '—',
                  document: ticket.data.document_number ?? '—',
                })}
              </div>
            )}

            {ticketId && (
              <>
                <div className="row-actions">
                  <Button
                    variant="primary"
                    disabled={!canCapture || capture.isPending}
                    onClick={() => capture.mutate('gross')}
                  >
                    {t('weighing:action.captureGross')}
                  </Button>
                  <Button
                    disabled={!canCapture || capture.isPending}
                    onClick={() => capture.mutate('tare')}
                  >
                    {t('weighing:action.captureTare')}
                  </Button>
                  <Button
                    disabled={!ticket.data?.gross_kg || !ticket.data?.tare_kg}
                    onClick={() => close.mutate()}
                  >
                    {t('weighing:action.close')}
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setTicketId(null)
                      setParams({})
                    }}
                  >
                    {t('common:action.close')}
                  </Button>
                </div>

                <details>
                  <summary className="page__subtitle">{t('weighing:manual.title')}</summary>
                  <div className="form-grid form-grid--bare">
                    <Input
                      label={t('weighing:manual.weight')}
                      operational
                      hint={t('weighing:manual.hint')}
                      value={manualWeight}
                      onChange={(event) => setManualWeight(event.target.value)}
                    />
                    <Input
                      label={t('weighing:manual.reason')}
                      operational
                      value={reasonCode}
                      onChange={(event) => setReasonCode(event.target.value)}
                    />
                    <Input
                      label={t('weighing:manual.secondFactor')}
                      value={secondFactor}
                      onChange={(event) => setSecondFactor(event.target.value)}
                    />
                  </div>
                </details>
              </>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel__title">
            <span>{t('weighing:tickets')}</span>
            <span>{format.number(tickets.data?.length ?? 0)}</span>
          </div>
          <div className="panel__body">
            <DataTable
              columns={columns}
              rows={tickets.data ?? []}
              rowKey={(row) => row.id}
              selectedKey={ticketId}
              onRowClick={(row) => setTicketId(row.id)}
              emptyLabel={t('weighing:empty')}
            />
          </div>
        </section>
      </div>
    </div>
  )
}
