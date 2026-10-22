import { AlarmList, Button, KpiTile, StatusPill } from '@gplansis/ds'
import type { AlarmItem, AlarmPriority } from '@gplansis/ds'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useErrorMessage } from '@/components/VisitStatus'
import type { AiProposal } from '@/lib/api'
import { api } from '@/lib/api'
import { currentActor } from '@/lib/auth'
import { useFormat } from '@/lib/format'

/**
 * Torre de controle com o agente.
 *
 * A regra que a tela torna visível: **aprovar e executar são dois atos**. O botão de
 * executar nem aparece antes da aprovação, e a aprovação grava quem decidiu. Nenhum
 * caminho daqui emite comando físico direto — isso vive no console da guarita, com
 * permissivo do CLP.
 */
export function ControlTowerAI() {
  const { t } = useTranslation(['tower', 'yard', 'common'])
  const format = useFormat()
  const queryClient = useQueryClient()
  const describeError = useErrorMessage()

  // Quem aprova é quem está autenticado — aprovação assinada por campo de texto
  // livre não é aprovação, é bilhete.
  const actor = currentActor()
  const [failure, setFailure] = useState<string | null>(null)

  const overview = useQuery({
    queryKey: ['tower', 'overview'],
    queryFn: api.towerOverview,
    refetchInterval: 15_000,
  })
  const proposals = useQuery({
    queryKey: ['tower', 'proposals'],
    queryFn: () => api.proposals('proposed'),
    refetchInterval: 20_000,
  })
  const approved = useQuery({
    queryKey: ['tower', 'proposals', 'approved'],
    queryFn: () => api.proposals('approved'),
    refetchInterval: 20_000,
  })
  const alarms = useQuery({
    queryKey: ['tower', 'bottlenecks'],
    queryFn: api.bottlenecks,
    refetchInterval: 20_000,
  })

  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['tower'] })
  const fail = (error: unknown) => setFailure(describeError(error))

  const generate = useMutation({
    mutationFn: api.generateProposals,
    onSuccess: () => {
      setFailure(null)
      refresh()
    },
    onError: fail,
  })
  const approve = useMutation({
    mutationFn: (proposal: AiProposal) => api.approveProposal(proposal.id, actor),
    onSuccess: () => {
      setFailure(null)
      refresh()
    },
    onError: fail,
  })
  const reject = useMutation({
    mutationFn: (proposal: AiProposal) =>
      api.rejectProposal(proposal.id, actor, 'OPERATOR_DECISION'),
    onSuccess: () => {
      setFailure(null)
      refresh()
    },
    onError: fail,
  })
  const execute = useMutation({
    mutationFn: (proposal: AiProposal) => api.executeProposal(proposal.id, actor),
    onSuccess: () => {
      setFailure(null)
      refresh()
    },
    onError: fail,
  })
  const acknowledge = useMutation({
    mutationFn: (alarm: AlarmItem) => api.acknowledgeBottleneck(alarm.id, actor),
    onSuccess: () => {
      setFailure(null)
      refresh()
    },
    onError: fail,
  })

  const data = overview.data
  const alarmItems: AlarmItem[] = (alarms.data ?? []).map((signal) => ({
    id: signal.id,
    priority: signal.severity as AlarmPriority,
    label: t(`tower:metric.${signal.metric}`),
    detail: t('tower:threshold', {
      value: format.number(Number(signal.value)),
      threshold: format.number(Number(signal.threshold)),
    }),
    at: format.time(signal.detected_at),
    acknowledged: signal.state === 'acknowledged',
    acknowledgedBy: signal.acknowledged_by,
    shelved: signal.state === 'shelved',
  }))

  const renderProposal = (proposal: AiProposal, executable: boolean) => (
    <li key={proposal.id} className="proposal">
      <div className="proposal__head">
        <StatusPill tone={executable ? 'running' : 'waiting'}>
          {t(`tower:kind.${proposal.kind}`)}
        </StatusPill>
        <span className="page__subtitle">{proposal.reference}</span>
      </div>
      <p className="proposal__rationale">{proposal.rationale}</p>
      <div className="proposal__impact">
        {Object.entries(proposal.impact_json).map(([key, value]) => (
          <span key={key}>
            {t(`tower:impact.${key}`, { defaultValue: key })}: <strong>{String(value)}</strong>
          </span>
        ))}
      </div>
      <div className="page__subtitle">
        {t('tower:expiresAt', { time: format.time(proposal.expires_at) })}
        {proposal.confidence &&
          ` · ${t('tower:confidence', {
            value: format.percent(Number(proposal.confidence) * 100),
          })}`}
      </div>
      <div className="row-actions">
        {!executable && (
          <>
            <Button variant="primary" onClick={() => approve.mutate(proposal)}>
              {t('tower:action.approve')}
            </Button>
            <Button onClick={() => reject.mutate(proposal)}>{t('tower:action.reject')}</Button>
          </>
        )}
        {executable && (
          <>
            <StatusPill tone="running">
              {t('tower:approvedBy', { actor: proposal.approved_by ?? '—' })}
            </StatusPill>
            <Button variant="primary" onClick={() => execute.mutate(proposal)}>
              {t('tower:action.execute')}
            </Button>
          </>
        )}
      </div>
    </li>
  )

  return (
    <div className="page">
      <div className="page__header">
        <h1 className="page__title">{t('tower:title')}</h1>
        <span className="page__subtitle">{t('tower:interlock')}</span>
      </div>

      {failure && <div className="alert">{failure}</div>}

      <div className="kpi-row">
        <KpiTile label={t('tower:kpi.gateQueue')} value={format.number(data?.gate_queue ?? 0)} />
        <KpiTile label={t('tower:kpi.inYard')} value={format.number(data?.in_yard ?? 0)} />
        <KpiTile
          label={t('tower:kpi.overDwell')}
          value={format.number(data?.over_dwell ?? 0)}
          severity={(data?.over_dwell ?? 0) > 0 ? 'warn' : 'normal'}
        />
        <KpiTile
          label={t('tower:kpi.demurrageRisk')}
          value={format.number(data?.demurrage_risk ?? 0)}
          severity={(data?.demurrage_risk ?? 0) > 0 ? 'alarm' : 'normal'}
        />
        <KpiTile
          label={t('tower:kpi.docks')}
          value={`${format.number(data?.docks_busy ?? 0)}/${format.number(data?.docks_total ?? 0)}`}
        />
        <KpiTile
          label={t('tower:kpi.lateAppointments')}
          value={format.number(data?.late_appointments ?? 0)}
        />
        <KpiTile label={t('tower:kpi.openMoves')} value={format.number(data?.open_moves ?? 0)} />
        <KpiTile
          label={t('tower:kpi.openHolds')}
          value={format.number(data?.open_holds ?? 0)}
          severity={(data?.open_holds ?? 0) > 0 ? 'warn' : 'normal'}
        />
      </div>

      <div className="tower">
        <section className="panel">
          <div className="panel__title">
            <span>{t('tower:proposals')}</span>
            <span className="row-actions">
              <span className="toolbar-identity">
                {t('tower:actor')}: <strong>{actor}</strong>
              </span>
              <Button onClick={() => generate.mutate()}>{t('tower:action.generate')}</Button>
            </span>
          </div>
          <div className="panel__body panel__body--padded">
            <ul className="proposal-list">
              {(proposals.data ?? []).map((proposal) => renderProposal(proposal, false))}
              {(approved.data ?? []).map((proposal) => renderProposal(proposal, true))}
              {(proposals.data ?? []).length === 0 && (approved.data ?? []).length === 0 && (
                <li className="page__subtitle">{t('tower:noProposals')}</li>
              )}
            </ul>
          </div>
        </section>

        <section className="panel">
          <div className="panel__title">
            <span>{t('tower:alarms')}</span>
            <span>{format.number(alarmItems.filter((a) => !a.acknowledged).length)}</span>
          </div>
          <div className="panel__body">
            <AlarmList
              alarms={alarmItems}
              onAcknowledge={(alarm) => acknowledge.mutate(alarm)}
              labels={{
                acknowledge: t('tower:action.acknowledge'),
                shelve: t('tower:action.shelve'),
                empty: t('tower:noAlarms'),
                acknowledgedBy: t('tower:acknowledgedBy'),
              }}
            />
          </div>
        </section>
      </div>
    </div>
  )
}
