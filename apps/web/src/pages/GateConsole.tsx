import { Button, DataTable, Input, Select } from '@gplansis/ds'
import type { Column } from '@gplansis/ds'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { FormEvent } from 'react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { VisitStatus, useErrorMessage } from '@/components/VisitStatus'
import type { Visit } from '@/lib/api'
import { api } from '@/lib/api'
import { useFormat } from '@/lib/format'

const EMPTY_FORM = {
  plate: '',
  driver_document: '',
  operation_type_code: '',
  product_sku: '',
  document_number: '',
  seal_number: '',
}

/**
 * Console da guarita. Densidade `touch` deixa isto usável com luva; a leitura por LPR/QR
 * chega na Fatia 4 e entra neste mesmo fluxo — aqui a digitação é o caminho de exceção.
 */
export function GateConsole() {
  const { t } = useTranslation(['gate', 'yard', 'common'])
  const format = useFormat()
  const queryClient = useQueryClient()
  const describeError = useErrorMessage()
  const [form, setForm] = useState(EMPTY_FORM)
  const [failure, setFailure] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const operationTypes = useQuery({ queryKey: ['operation-types'], queryFn: api.operationTypes })
  const products = useQuery({ queryKey: ['products'], queryFn: api.products })
  const open = useQuery({
    queryKey: ['visits', 'open'],
    queryFn: () => api.visits({ onlyOpen: true }),
    refetchInterval: 10_000,
  })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['visits'] })
    void queryClient.invalidateQueries({ queryKey: ['yard'] })
    void queryClient.invalidateQueries({ queryKey: ['overview'] })
  }

  const fail = (error: unknown) => {
    setSuccess(null)
    setFailure(describeError(error))
  }

  const gateIn = useMutation({
    mutationFn: () =>
      api.gateIn({
        plate: form.plate,
        driver_document: form.driver_document,
        operation_type_code: form.operation_type_code,
        product_sku: form.product_sku || undefined,
        document_number: form.document_number || undefined,
        seal_number: form.seal_number || undefined,
        gate_code: 'GATE-01',
        actor: 'gate.console',
      }),
    onSuccess: (visit) => {
      setFailure(null)
      setSuccess(t('gate:checkin.success', { reference: visit.reference }))
      setForm(EMPTY_FORM)
      refresh()
    },
    onError: fail,
  })

  const release = useMutation({
    mutationFn: (visitId: string) => api.assignSlot(visitId),
    onSuccess: () => {
      setFailure(null)
      refresh()
    },
    onError: fail,
  })

  const gateOut = useMutation({
    mutationFn: (visitId: string) => api.gateOut(visitId, 'GATE-02'),
    onSuccess: () => {
      setFailure(null)
      refresh()
    },
    onError: fail,
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    gateIn.mutate()
  }

  const queue = (open.data ?? []).filter((visit) => visit.state === 'at_gate_in')
  const inYard = (open.data ?? []).filter((visit) => visit.state !== 'at_gate_in')

  const queueColumns: Column<Visit>[] = [
    {
      key: 'plate',
      header: t('yard:visit.column.plate'),
      width: 110,
      pinned: true,
      value: (visit) => visit.plate,
    },
    { key: 'driver', priority: 'secondary', header: t('yard:visit.column.driver'), width: 160, value: (v) => v.driver_name },
    {
      key: 'operation',
      priority: 'secondary',
      header: t('yard:visit.column.operation'),
      width: 170,
      render: (visit) => t(`yard:operation.${visit.operation_type_code}`),
    },
    {
      key: 'wait',
      header: t('yard:visit.column.dwell'),
      width: 90,
      align: 'right',
      value: (visit) => visit.dwell_seconds,
      render: (visit) => format.duration(visit.dwell_seconds),
    },
    {
      key: 'actions',
      header: t('yard:visit.column.state'),
      width: 180,
      render: (visit) => (
        <span className="row-actions">
          <Button
            variant="primary"
            disabled={release.isPending}
            onClick={() => release.mutate(visit.id)}
          >
            {t('gate:action.release')}
          </Button>
        </span>
      ),
    },
  ]

  const yardColumns: Column<Visit>[] = [
    {
      key: 'plate',
      header: t('yard:visit.column.plate'),
      width: 110,
      pinned: true,
      value: (visit) => visit.plate,
    },
    {
      key: 'state',
      header: t('yard:visit.column.state'),
      width: 130,
      render: (visit) => (
        <VisitStatus state={visit.state} blocked={Boolean(visit.blocked_reason_code)} />
      ),
    },
    { key: 'slot', header: t('yard:visit.column.slot'), width: 80, value: (v) => v.slot_code ?? '' },
    { key: 'dock', priority: 'detail', header: t('yard:visit.column.dock'), width: 90, value: (v) => v.dock_code ?? '' },
    {
      key: 'dwell',
      header: t('yard:visit.column.dwell'),
      width: 90,
      align: 'right',
      value: (visit) => visit.dwell_seconds,
      render: (visit) => format.duration(visit.dwell_seconds),
    },
    {
      key: 'actions',
      header: t('yard:visit.column.gateOut'),
      width: 190,
      render: (visit) => (
        <span className="row-actions">
          <Button
            disabled={gateOut.isPending || Boolean(visit.blocked_reason_code)}
            title={
              visit.blocked_reason_code
                ? t('yard:visit.blocked', { reason: visit.blocked_reason_code })
                : undefined
            }
            onClick={() => gateOut.mutate(visit.id)}
          >
            {t('gate:action.gateOut')}
          </Button>
        </span>
      ),
    },
  ]

  return (
    <div className="page">
      <div className="page__header">
        <h1 className="page__title">{t('gate:checkin.title')}</h1>
        <span className="page__subtitle">{t('gate:checkin.subtitle')}</span>
      </div>

      {failure && <div className="alert">{failure}</div>}
      {success && <div className="alert alert--ok">{success}</div>}

      <div className="gate">
        <section className="panel">
          <div className="panel__title">{t('gate:checkin.title')}</div>
          <form className="form-grid" onSubmit={submit}>
            <Input
              label={t('gate:checkin.field.plate')}
              operational
              required
              placeholder={t('gate:checkin.placeholder.plate')}
              hint={t('gate:checkin.hint.plate')}
              value={form.plate}
              onChange={(event) => setForm({ ...form, plate: event.target.value })}
            />
            <Input
              label={t('gate:checkin.field.driverDocument')}
              operational
              required
              placeholder={t('gate:checkin.placeholder.driverDocument')}
              value={form.driver_document}
              onChange={(event) => setForm({ ...form, driver_document: event.target.value })}
            />
            <Select
              label={t('gate:checkin.field.operationType')}
              required
              placeholder={t('gate:checkin.placeholder.select')}
              value={form.operation_type_code}
              onChange={(event) => setForm({ ...form, operation_type_code: event.target.value })}
              options={(operationTypes.data ?? []).map((operation) => ({
                value: operation.code,
                label: t(`yard:operation.${operation.code}`),
              }))}
            />
            <Select
              label={t('gate:checkin.field.product')}
              placeholder={t('gate:checkin.placeholder.optional')}
              value={form.product_sku}
              onChange={(event) => setForm({ ...form, product_sku: event.target.value })}
              options={(products.data ?? []).map((product) => ({
                value: product.sku,
                label: product.name,
              }))}
            />
            <div className="form-row">
              <Input
                label={t('gate:checkin.field.documentNumber')}
                hint={t('gate:checkin.hint.documentNumber')}
                value={form.document_number}
                onChange={(event) => setForm({ ...form, document_number: event.target.value })}
              />
              <Input
                label={t('gate:checkin.field.sealNumber')}
                operational
                value={form.seal_number}
                onChange={(event) => setForm({ ...form, seal_number: event.target.value })}
              />
            </div>
            <Button type="submit" variant="primary" block disabled={gateIn.isPending}>
              {t('gate:checkin.submit')}
            </Button>
          </form>
        </section>

        <div className="stack">
          <section className="panel">
            <div className="panel__title">
              <span>{t('gate:queue.title')}</span>
              <span>{format.number(queue.length)}</span>
            </div>
            <div className="panel__body">
              <DataTable
                columns={queueColumns}
                rows={queue}
                rowKey={(visit) => visit.id}
                emptyLabel={t('gate:queue.empty')}
              />
            </div>
          </section>

          <section className="panel">
            <div className="panel__title">
              <span>{t('gate:yard.title')}</span>
              <span>{format.number(inYard.length)}</span>
            </div>
            <div className="panel__body">
              <DataTable
                columns={yardColumns}
                rows={inYard}
                rowKey={(visit) => visit.id}
                emptyLabel={t('gate:yard.empty')}
              />
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
