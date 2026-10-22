import { Button, Input, Select, StatusPill, StepFlow } from '@gplansis/ds'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useErrorMessage } from '@/components/VisitStatus'
import { api } from '@/lib/api'
import { useUiStore } from '@/lib/uiStore'
import { currentActor } from '@/lib/auth'
import { useFormat } from '@/lib/format'

/**
 * Totem da guarita: um passo por tela, alvo grande, usável com luva.
 *
 * A ordem é a regra do produto e não se pula: identificar → checklist → liberar.
 * O botão de cancela só habilita depois que a triagem passou e o permissivo do CLP
 * voltou verdadeiro — e mesmo assim o comando vai com quem autorizou.
 */
export function GateKiosk() {
  const { t } = useTranslation(['gate', 'yard', 'common'])
  const format = useFormat()
  const queryClient = useQueryClient()
  const describeError = useErrorMessage()
  const actor = currentActor()

  const [step, setStep] = useState(0)
  const [gateCode, setGateCode] = useState('GATE-01')
  const [method, setMethod] = useState<'lpr' | 'qr' | 'rfid' | 'manual'>('lpr')
  const [value, setValue] = useState('')
  const [confidence, setConfidence] = useState('0.95')
  const [visitId, setVisitId] = useState<string | null>(null)
  // Sem valor padrão: item não respondido é item não conferido, e não deixa avançar.
  const [answers, setAnswers] = useState<Record<string, boolean | undefined>>({})
  const [failure, setFailure] = useState<string | null>(null)
  const [decision, setDecision] = useState<string | null>(null)
  const [commandState, setCommandState] = useState<string | null>(null)

  const map = useQuery({ queryKey: ['yard', 'map'], queryFn: () => api.yardMap(useUiStore.getState().plantCode) })
  const devices = useQuery({ queryKey: ['gate', 'devices'], queryFn: () => api.devices('barrier') })
  const identifications = useQuery({
    queryKey: ['gate', 'identifications', gateCode],
    queryFn: () => api.identifications(gateCode),
    refetchInterval: 10_000,
  })
  const queue = useQuery({
    queryKey: ['visits', 'open'],
    queryFn: () => api.visits({ onlyOpen: true }),
    refetchInterval: 10_000,
  })
  const checklist = useQuery({
    queryKey: ['gate', 'checklist', visitId],
    queryFn: () => api.checklist(visitId as string),
    enabled: Boolean(visitId),
  })

  const fail = (error: unknown) => setFailure(describeError(error))

  const identify = useMutation({
    mutationFn: () =>
      api.identify({
        gate_code: gateCode,
        method,
        value,
        confidence: method === 'lpr' ? Number(confidence) : undefined,
        image_ref: method === 'lpr' ? `s3://yard/lpr/${value}.jpg` : undefined,
        actor: method === 'manual' ? actor : undefined,
      }),
    onSuccess: (result) => {
      setFailure(null)
      setDecision(result.decision)
      void queryClient.invalidateQueries({ queryKey: ['gate', 'identifications'] })
      setStep(1)
    },
    onError: fail,
  })

  const submitChecklist = useMutation({
    mutationFn: () =>
      api.answerChecklist(visitId as string, {
        actor,
        answers: (checklist.data ?? []).map((item) => ({
          item_id: item.id,
          passed: answers[item.id] === true,
          photo_ref:
            answers[item.id] === false ? `s3://yard/checklist/${item.code}.jpg` : undefined,
        })),
      }),
    onSuccess: (failedItems) => {
      setFailure(
        failedItems.length ? t('gate:checklist.blocked', { items: failedItems.join(', ') }) : null,
      )
      if (!failedItems.length) setStep(2)
    },
    onError: fail,
  })

  const openBarrier = useMutation({
    mutationFn: (deviceCode: string) =>
      api.gateCommand({
        device_code: deviceCode,
        action: 'open_barrier',
        visit_id: visitId ?? undefined,
        origin: 'human',
        authorized_by: actor,
      }),
    onSuccess: (command) => {
      setFailure(null)
      setCommandState(command.state)
    },
    onError: (error) => {
      setCommandState(null)
      fail(error)
    },
  })

  const barrier = (devices.data ?? []).find((device) => device.status === 'online')
  const items = checklist.data ?? []
  const pending = items.filter((item) => answers[item.id] === undefined)
  const failedItems = items.filter(
    (item) => answers[item.id] === false && item.severity === 'blocking',
  )

  return (
    <div className="page">
      <div className="page__header">
        <h1 className="page__title">{t('gate:kiosk.title')}</h1>
        <span className="page__subtitle">{t('gate:kiosk.subtitle')}</span>
      </div>

      {failure && <div className="alert">{failure}</div>}

      <div className="kiosk">
        <section className="panel panel--flow">
          <StepFlow
            currentIndex={step}
            onChange={setStep}
            onFinish={() => barrier && openBarrier.mutate(barrier.code)}
            labels={{
              back: t('common:action.cancel'),
              next: t('gate:kiosk.next'),
              finish: t('gate:kiosk.release'),
              step: t('gate:kiosk.step'),
              of: t('gate:kiosk.of'),
            }}
            steps={[
              {
                id: 'identify',
                title: t('gate:kiosk.step1'),
                hint: t('gate:kiosk.step1Hint'),
                content: (
                  <>
                    <Select
                      label={t('gate:checkin.field.gate')}
                      value={gateCode}
                      onChange={(event) => setGateCode(event.target.value)}
                      options={(map.data?.gates ?? []).map((gate) => ({
                        value: gate.code,
                        label: gate.code,
                      }))}
                    />
                    <Select
                      label={t('gate:kiosk.method')}
                      value={method}
                      onChange={(event) => setMethod(event.target.value as typeof method)}
                      options={[
                        { value: 'lpr', label: t('gate:method.lpr') },
                        { value: 'qr', label: t('gate:method.qr') },
                        { value: 'rfid', label: t('gate:method.rfid') },
                        { value: 'manual', label: t('gate:method.manual') },
                      ]}
                    />
                    <Input
                      label={t('gate:kiosk.value')}
                      operational
                      value={value}
                      onChange={(event) => setValue(event.target.value)}
                      hint={t('gate:kiosk.valueHint')}
                    />
                    {method === 'lpr' && (
                      <Input
                        label={t('gate:kiosk.confidence')}
                        operational
                        value={confidence}
                        onChange={(event) => setConfidence(event.target.value)}
                        hint={t('gate:kiosk.confidenceHint')}
                      />
                    )}
                    <Button variant="primary" onClick={() => identify.mutate()}>
                      {t('gate:kiosk.identify')}
                    </Button>
                    {decision && (
                      <StatusPill tone={decision === 'admit' ? 'running' : 'waiting'}>
                        {t(`gate:decision.${decision}`)}
                      </StatusPill>
                    )}
                  </>
                ),
              },
              {
                id: 'checklist',
                title: t('gate:kiosk.step2'),
                hint: t('gate:kiosk.step2Hint'),
                // Sem visita escolhida não há o que conferir — e liberar cancela sem
                // conferir é o buraco que o checklist existe para fechar.
                blocked: !visitId || failedItems.length > 0 || pending.length > 0,
                blockedReason: !visitId
                  ? t('gate:checklist.selectVisit')
                  : failedItems.length
                    ? t('gate:checklist.blocked', {
                        items: failedItems.map((item) => t(`gate:item.${item.code}`)).join(', '),
                      })
                    : t('gate:checklist.pending', { count: pending.length }),
                content: (
                  <>
                    <Select
                      label={t('gate:kiosk.visit')}
                      value={visitId ?? ''}
                      placeholder={t('gate:checkin.placeholder.select')}
                      onChange={(event) => setVisitId(event.target.value)}
                      options={(queue.data ?? [])
                        .filter((visit) => visit.state === 'at_gate_in')
                        .map((visit) => ({
                          value: visit.id,
                          label: `${visit.plate} · ${visit.reference}`,
                        }))}
                    />
                    <ul className="checklist">
                      {items.map((item) => (
                        <li key={item.id} className="checklist__item">
                          <span className="checklist__label">
                            {t(`gate:item.${item.code}`)}
                            {item.severity !== 'blocking' && (
                              <StatusPill tone="idle">
                                {t(`gate:severity.${item.severity}`)}
                              </StatusPill>
                            )}
                          </span>
                          <span className="checklist__answer">
                            <Button
                              variant={answers[item.id] === true ? 'primary' : 'default'}
                              onClick={() => setAnswers({ ...answers, [item.id]: true })}
                            >
                              {t('gate:checklist.pass')}
                            </Button>
                            <Button
                              variant={answers[item.id] === false ? 'danger' : 'default'}
                              onClick={() => setAnswers({ ...answers, [item.id]: false })}
                            >
                              {t('gate:checklist.fail')}
                            </Button>
                          </span>
                        </li>
                      ))}
                    </ul>
                    <Button
                      block
                      disabled={!visitId || pending.length > 0 || submitChecklist.isPending}
                      onClick={() => submitChecklist.mutate()}
                    >
                      {t('gate:kiosk.submitChecklist')}
                    </Button>
                  </>
                ),
              },
              {
                id: 'release',
                title: t('gate:kiosk.step3'),
                hint: t('gate:kiosk.step3Hint'),
                blocked: !barrier,
                blockedReason: t('gate:kiosk.noDevice'),
                content: (
                  <>
                    <div className="page__subtitle">
                      {t('gate:kiosk.device', { code: barrier?.code ?? '—' })}
                    </div>
                    {commandState && (
                      <StatusPill tone={commandState === 'acknowledged' ? 'running' : 'waiting'}>
                        {t(`gate:command.${commandState}`)}
                      </StatusPill>
                    )}
                    <p className="page__subtitle">{t('gate:kiosk.permissiveNote')}</p>
                  </>
                ),
              },
            ]}
          />
        </section>

        <section className="panel">
          <div className="panel__title">
            <span>{t('gate:identifications.title')}</span>
            <span>{format.number(identifications.data?.length ?? 0)}</span>
          </div>
          <div className="panel__body panel__body--padded">
            <ul className="event-feed">
              {(identifications.data ?? []).slice(0, 25).map((event) => (
                <li className="event-feed__item" key={`${event.occurred_at}-${event.value}`}>
                  <span className="timeline-list__time">{format.time(event.occurred_at)}</span>
                  <StatusPill tone={event.state === 'matched' ? 'running' : 'waiting'}>
                    {t(`gate:method.${event.method}`)}
                  </StatusPill>
                  <span className="event-feed__value">{event.value}</span>
                  <span className="event-feed__meta">
                    {event.confidence ? format.percent(Number(event.confidence) * 100) : ''}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </div>
    </div>
  )
}
