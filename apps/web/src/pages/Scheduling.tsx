import { Button, DataTable, DockTimeline, StatusPill } from '@gplansis/ds'
import type { Column, TimelineBooking } from '@gplansis/ds'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { AppointmentDetailModal } from '@/components/AppointmentDetailModal'
import { NewAppointmentModal } from '@/components/NewAppointmentModal'
import { useErrorMessage } from '@/components/VisitStatus'
import type { Appointment } from '@/lib/api'
import { api } from '@/lib/api'
import { useUiStore } from '@/lib/uiStore'
import { getPlantTimeZone, useFormat } from '@/lib/format'

const STATE_TONE: Record<string, 'running' | 'idle' | 'waiting' | 'stopped' | 'moving' | 'critical'> =
  {
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

export function Scheduling() {
  const { t } = useTranslation(['scheduling', 'yard', 'common'])
  const format = useFormat()
  const queryClient = useQueryClient()
  const describeError = useErrorMessage()

  const [selected, setSelected] = useState<Appointment | null>(null)
  const [creating, setCreating] = useState<{ dockCode?: string; startsAt?: Date } | null>(
    null,
  )
  const [failure, setFailure] = useState<string | null>(null)

  const [from, to] = useMemo(() => {
    const start = new Date()
    start.setMinutes(0, 0, 0)
    const end = new Date(start.getTime() + 14 * 3600_000)
    return [start, end]
  }, [])

  const appointments = useQuery({
    queryKey: ['appointments', from.toISOString()],
    queryFn: () => api.appointments({ dateFrom: from.toISOString(), dateTo: to.toISOString() }),
    refetchInterval: 20_000,
  })
  const map = useQuery({ queryKey: ['yard', 'map'], queryFn: () => api.yardMap(useUiStore.getState().plantCode) })
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['appointments'] })
    void queryClient.invalidateQueries({ queryKey: ['yard'] })
  }

  const reschedule = useMutation({
    mutationFn: ({
      appointment,
      dockCode,
      startsAt,
    }: {
      appointment: Appointment
      dockCode: string
      startsAt: Date
    }) => {
      const duration =
        new Date(appointment.ends_at).getTime() - new Date(appointment.starts_at).getTime()
      return api.rescheduleAppointment(appointment.id, {
        starts_at: startsAt.toISOString(),
        ends_at: new Date(startsAt.getTime() + duration).toISOString(),
        dock_code: dockCode,
        // Arrastar a faixa é reprogramar: motivo obrigatório, aqui o da própria manobra.
        reason_code: 'OPERATIONAL',
        version: appointment.version,
      })
    },
    onSuccess: () => {
      setFailure(null)
      refresh()
    },
    onError: (error) => setFailure(describeError(error)),
  })

  const docks = (map.data?.docks ?? []).map((dock) => ({
    id: dock.id,
    code: dock.code,
    // `occupied` é estado de agora, não de calendário: doca com caminhão às 9h
    // continua agendável às 15h. Só bloqueio real hachura a faixa do dia inteiro.
    status: dock.status === 'blocked' ? 'blocked' : 'available',
  }))
  const dockByCode = new Map(docks.map((dock) => [dock.code, dock.id]))
  const dockById = new Map(docks.map((dock) => [dock.id, dock.code]))

  const bookings: TimelineBooking[] = (appointments.data ?? [])
    .filter((appointment) => appointment.state !== 'cancelled')
    .map((appointment) => ({
      id: appointment.id,
      dockId: dockByCode.get(appointment.dock_code) ?? appointment.dock_code,
      label: appointment.plate,
      startsAt: new Date(appointment.starts_at),
      endsAt: new Date(appointment.ends_at),
      state: appointment.state,
    }))

  const columns: Column<Appointment>[] = [
    {
      key: 'reference',
      priority: 'secondary',
      header: t('scheduling:column.reference'),
      width: 160,
      pinned: true,
      sortable: true,
      value: (row) => row.reference,
    },
    { key: 'dock', header: t('scheduling:column.dock'), width: 100, value: (row) => row.dock_code },
    { key: 'plate', priority: 'essential', header: t('scheduling:column.plate'), width: 100, value: (row) => row.plate },
    {
      key: 'window',
      header: t('scheduling:column.window'),
      width: 170,
      sortable: true,
      value: (row) => row.starts_at,
      render: (row) => `${format.dateTime(row.starts_at)} · ${format.time(row.ends_at)}`,
    },
    {
      key: 'state',
      header: t('scheduling:column.state'),
      width: 130,
      render: (row) => (
        <StatusPill tone={STATE_TONE[row.state] ?? 'idle'}>
          {t(`scheduling:state.${row.state}`)}
        </StatusPill>
      ),
    },
    {
      key: 'priority',
      priority: 'secondary',
      header: t('scheduling:column.priority'),
      width: 150,
      sortable: true,
      value: (row) => row.priority_rank,
      render: (row) =>
        row.priority_code
          ? t(`scheduling:priority.${row.priority_code}`)
          : t('scheduling:priority.none'),
    },
    {
      key: 'channel',
      priority: 'detail',
      header: t('scheduling:column.channel'),
      width: 100,
      render: (row) => t(`scheduling:channel.${row.channel}`),
    },
    {
      key: 'slot',
      priority: 'detail',
      header: t('scheduling:column.slot'),
      width: 110,
      value: (row) => row.slot_code ?? '',
    },
  ]

  return (
    <div className="page">
      <div className="page__header">
        <h1 className="page__title">{t('scheduling:title')}</h1>
        <span className="page__subtitle">{t('scheduling:timeline.dragHint')}</span>
      </div>

      {failure && <div className="alert">{failure}</div>}

      <section className="panel panel--timeline">
        <div className="panel__title">
          <span>{t('scheduling:subtitle')}</span>
          <span className="row-actions">
            <span className="toolbar-identity">{format.dateTime(from.toISOString())}</span>
            <Button variant="primary" onClick={() => setCreating({})}>
              {t('scheduling:form.title')}
            </Button>
          </span>
        </div>
        <div className="panel__body">
          <DockTimeline
            docks={docks}
            bookings={bookings}
            from={from}
            to={to}
            selectedId={selected?.id ?? null}
            locale={format.locale}
            timeZone={getPlantTimeZone()}
            onSelect={(booking) =>
              setSelected(
                (appointments.data ?? []).find((item) => item.id === booking.id) ?? null,
              )
            }
            onEmptyClick={(dockId: string, startsAt: Date) =>
              setCreating({ dockCode: dockById.get(dockId), startsAt })
            }
            onMove={(booking, dockId, startsAt) => {
              const appointment = (appointments.data ?? []).find((item) => item.id === booking.id)
              if (!appointment) return
              reschedule.mutate({
                appointment,
                dockCode: dockById.get(dockId) ?? appointment.dock_code,
                startsAt,
              })
            }}
            labels={{
              hour: t('scheduling:timeline.dock'),
              empty: t('scheduling:timeline.empty'),
              blocked: t('scheduling:timeline.blocked'),
              now: t('scheduling:timeline.now'),
            }}
          />
        </div>
      </section>

      <section className="panel">
        <div className="panel__body">
          <DataTable
            columns={columns}
            rows={appointments.data ?? []}
            rowKey={(row) => row.id}
            selectedKey={selected?.id ?? null}
            onRowClick={(row) => setSelected(row)}
            emptyLabel={t('scheduling:empty')}
            footer={t('scheduling:footer', { count: appointments.data?.length ?? 0 })}
          />
        </div>
      </section>

      <AppointmentDetailModal
        appointment={selected}
        docks={docks}
        onClose={() => setSelected(null)}
      />

      <NewAppointmentModal
        open={creating !== null}
        preset={creating}
        onClose={() => setCreating(null)}
      />
    </div>
  )
}
