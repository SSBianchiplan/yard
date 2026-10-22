import { Button, Input, Modal, Select, StatusPill } from '@gplansis/ds'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useErrorMessage } from '@/components/VisitStatus'
import { api } from '@/lib/api'
import { useUiStore } from '@/lib/uiStore'
import { useFormat } from '@/lib/format'

export interface NewAppointmentModalProps {
  open: boolean
  onClose: () => void
  /** Doca e horário pré-preenchidos quando o programador clica num vão livre do gantt. */
  preset?: { dockCode?: string; startsAt?: Date } | null
}

function toLocalInput(date: Date): string {
  const offset = date.getTimezoneOffset() * 60000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

/**
 * Nova janela de doca.
 *
 * A disponibilidade aparece **antes** de tentar: a grade mostra o que está livre por
 * doca, e confirmar já reserva a vaga. Deixar o programador descobrir o conflito no
 * erro do servidor é fazer ele trabalhar duas vezes.
 */
export function NewAppointmentModal({ open, onClose, preset }: NewAppointmentModalProps) {
  const { t } = useTranslation(['scheduling', 'gate', 'yard', 'common'])
  const format = useFormat()
  const queryClient = useQueryClient()
  const describeError = useErrorMessage()

  const start = preset?.startsAt ?? new Date(Date.now() + 2 * 3600_000)
  const [form, setForm] = useState({
    plate: '',
    dock_code: preset?.dockCode ?? '',
    operation_type_code: '',
    product_sku: '',
    resource_code: '',
    starts_at: toLocalInput(start),
    duration: '90',
  })
  const [failure, setFailure] = useState<string | null>(null)
  const [created, setCreated] = useState<string | null>(null)

  const map = useQuery({ queryKey: ['yard', 'map'], queryFn: () => api.yardMap(useUiStore.getState().plantCode), enabled: open })
  const operations = useQuery({
    queryKey: ['operation-types'],
    queryFn: api.operationTypes,
    enabled: open,
  })
  const products = useQuery({ queryKey: ['products'], queryFn: api.products, enabled: open })
  const availability = useQuery({
    queryKey: ['availability', form.dock_code],
    queryFn: () => api.availability(new Date(form.starts_at).toISOString()),
    enabled: open && Boolean(form.dock_code),
  })

  const endsAt = new Date(
    new Date(form.starts_at).getTime() + Number(form.duration || 90) * 60000,
  )

  const create = useMutation({
    mutationFn: () =>
      api.createAppointment({
        plate: form.plate.trim().toUpperCase(),
        dock_code: form.dock_code,
        operation_type_code: form.operation_type_code,
        product_sku: form.product_sku || undefined,
        resource_code: form.resource_code || undefined,
        starts_at: new Date(form.starts_at).toISOString(),
        ends_at: endsAt.toISOString(),
      }),
    onSuccess: (appointment) => {
      setFailure(null)
      setCreated(appointment.id)
      void queryClient.invalidateQueries({ queryKey: ['appointments'] })
    },
    onError: (error) => setFailure(describeError(error)),
  })

  const confirm = useMutation({
    mutationFn: () => api.confirmAppointment(created as string, 1),
    onSuccess: () => {
      setFailure(null)
      void queryClient.invalidateQueries({ queryKey: ['appointments'] })
      void queryClient.invalidateQueries({ queryKey: ['yard'] })
      onClose()
      setCreated(null)
    },
    onError: (error) => setFailure(describeError(error)),
  })

  // Janelas livres da doca escolhida, nas próximas horas.
  const windows = (availability.data ?? [])
    .filter((slot) => slot.dock_code === form.dock_code)
    .slice(0, 8)

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('scheduling:form.title')}
      subtitle={t('scheduling:subtitle')}
      closeLabel={t('common:action.close')}
      actions={
        <>
          {!created && (
            <Button
              variant="primary"
              disabled={!form.plate || !form.dock_code || !form.operation_type_code}
              onClick={() => create.mutate()}
            >
              {t('scheduling:form.submit')}
            </Button>
          )}
          {created && (
            <Button variant="primary" onClick={() => confirm.mutate()}>
              {t('scheduling:form.confirm')}
            </Button>
          )}
        </>
      }
    >
      {failure && <div className="alert">{failure}</div>}
      {created && (
        <div className="alert alert--ok">{t('scheduling:form.createdHint')}</div>
      )}

      <div className="modal-grid">
        <Input
          label={t('scheduling:form.plate')}
          operational
          placeholder={t('gate:checkin.placeholder.plate')}
          value={form.plate}
          onChange={(event) => setForm({ ...form, plate: event.target.value })}
        />
        <Select
          label={t('scheduling:form.dock')}
          value={form.dock_code}
          placeholder={t('gate:checkin.placeholder.select')}
          onChange={(event) => setForm({ ...form, dock_code: event.target.value })}
          options={(map.data?.docks ?? []).map((dock) => ({
            value: dock.code,
            label: dock.code,
            disabled: dock.status === 'blocked',
          }))}
        />
        <Select
          label={t('scheduling:form.operation')}
          value={form.operation_type_code}
          placeholder={t('gate:checkin.placeholder.select')}
          onChange={(event) => setForm({ ...form, operation_type_code: event.target.value })}
          options={(operations.data ?? []).map((operation) => ({
            value: operation.code,
            label: t(`yard:operation.${operation.code}`),
          }))}
        />
        <Select
          label={t('scheduling:form.product')}
          value={form.product_sku}
          placeholder={t('gate:checkin.placeholder.optional')}
          onChange={(event) => setForm({ ...form, product_sku: event.target.value })}
          options={(products.data ?? []).map((product) => ({
            value: product.sku,
            label: product.name,
          }))}
        />
        <Input
          label={t('scheduling:form.startsAt')}
          type="datetime-local"
          value={form.starts_at}
          onChange={(event) => setForm({ ...form, starts_at: event.target.value })}
        />
        <Input
          label={t('scheduling:form.duration')}
          type="number"
          value={form.duration}
          hint={t('scheduling:form.endsAtHint', { time: format.time(endsAt.toISOString()) })}
          onChange={(event) => setForm({ ...form, duration: event.target.value })}
        />
      </div>

      {form.dock_code && (
        <section>
          <h3 className="modal-section">{t('scheduling:form.availability')}</h3>
          <div className="row-actions">
            {windows.map((slot) => (
              <Button
                key={slot.starts_at}
                variant={slot.available ? 'default' : 'ghost'}
                disabled={!slot.available}
                onClick={() =>
                  setForm({ ...form, starts_at: toLocalInput(new Date(slot.starts_at)) })
                }
              >
                {format.time(slot.starts_at)}
              </Button>
            ))}
            {windows.length === 0 && (
              <StatusPill tone="idle">{t('scheduling:empty')}</StatusPill>
            )}
          </div>
        </section>
      )}
    </Modal>
  )
}
