import { Button, DataTable, Input, StatusPill } from '@gplansis/ds'
import type { Column } from '@gplansis/ds'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { VisitDetailModal } from '@/components/VisitDetailModal'
import { VisitStatus } from '@/components/VisitStatus'
import type { Visit } from '@/lib/api'
import { api } from '@/lib/api'
import { useFormat } from '@/lib/format'

export function VisitsList() {
  const { t } = useTranslation(['yard', 'common'])
  const format = useFormat()
  const [search, setSearch] = useState('')
  const [onlyOpen, setOnlyOpen] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [detailModal, setDetailModal] = useState<string | null>(null)

  const visits = useQuery({
    queryKey: ['visits', 'list', search, onlyOpen],
    queryFn: () => api.visits({ search: search || undefined, onlyOpen }),
  })

  const detail = useQuery({
    queryKey: ['visits', 'detail', selected],
    queryFn: () => api.visit(selected as string),
    enabled: Boolean(selected),
  })

  const columns: Column<Visit>[] = [
    {
      key: 'plate',
      header: t('yard:visit.column.plate'),
      width: 110,
      pinned: true,
      sortable: true,
      value: (visit) => visit.plate,
    },
    {
      key: 'reference',
      priority: 'secondary',
      header: t('yard:visit.column.reference'),
      width: 160,
      sortable: true,
      value: (visit) => visit.reference,
    },
    {
      key: 'state',
      header: t('yard:visit.column.state'),
      width: 130,
      render: (visit) => (
        <VisitStatus state={visit.state} blocked={Boolean(visit.blocked_reason_code)} />
      ),
    },
    {
      key: 'operation',
      priority: 'secondary',
      header: t('yard:visit.column.operation'),
      width: 180,
      value: (visit) => visit.operation_type_code,
      render: (visit) => t(`yard:operation.${visit.operation_type_code}`),
    },
    {
      key: 'driver',
      priority: 'secondary',
      header: t('yard:visit.column.driver'),
      width: 170,
      sortable: true,
      value: (visit) => visit.driver_name,
    },
    {
      key: 'carrier',
      priority: 'detail',
      header: t('yard:visit.column.carrier'),
      width: 180,
      value: (visit) => visit.carrier_name ?? '',
    },
    { key: 'slot', priority: 'detail', header: t('yard:visit.column.slot'), width: 80, value: (v) => v.slot_code ?? '' },
    { key: 'dock', priority: 'detail', header: t('yard:visit.column.dock'), width: 90, value: (v) => v.dock_code ?? '' },
    {
      key: 'arrived',
      priority: 'detail',
      header: t('yard:visit.column.arrived'),
      width: 150,
      sortable: true,
      value: (visit) => visit.arrived_at,
      render: (visit) => format.dateTime(visit.arrived_at),
    },
    {
      key: 'dwell',
      header: t('yard:visit.column.dwell'),
      width: 100,
      align: 'right',
      sortable: true,
      value: (visit) => visit.dwell_seconds,
      render: (visit) => format.duration(visit.dwell_seconds),
    },
  ]

  return (
    <div className="page">
      <div className="page__header">
        <h1 className="page__title">{t('yard:visit.title')}</h1>
        <span className="page__subtitle">
          {t('yard:visit.footer', { count: visits.data?.length ?? 0 })}
        </span>
      </div>

      <div className="tower">
        <section className="panel">
          <div className="panel__body">
            <DataTable
              columns={columns}
              rows={visits.data ?? []}
              rowKey={(visit) => visit.id}
              selectedKey={selected}
              onRowClick={(visit) => setSelected(visit.id)}
              emptyLabel={t('yard:visit.empty')}
              toolbar={
                <>
                  <Input
                    label={t('common:action.search')}
                    operational
                    placeholder={t('yard:visit.searchPlaceholder')}
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                  />
                  <Button
                    variant={onlyOpen ? 'primary' : 'default'}
                    onClick={() => setOnlyOpen((value) => !value)}
                  >
                    {t('yard:visit.onlyOpen')}
                  </Button>
                </>
              }
              footer={t('yard:visit.footer', { count: visits.data?.length ?? 0 })}
            />
          </div>
        </section>

        <section className="panel">
          <div className="panel__title">
            <span>{t('yard:visit.events')}</span>
            {selected && (
              <Button variant="ghost" onClick={() => setSelected(null)}>
                {t('common:action.close')}
              </Button>
            )}
          </div>
          <div className="panel__body panel__body--padded">
            {!selected && <p className="page__subtitle">{t('yard:map.emptySelection')}</p>}
            {detail.data && (
              <div className="stack">
                <div className="page__header">
                  <div>
                    <div className="page__title">{detail.data.plate}</div>
                    <div className="page__subtitle">{detail.data.reference}</div>
                  </div>
                  <Button variant="primary" onClick={() => setDetailModal(selected)}>
                    {t('yard:detail.openActions')}
                  </Button>
                </div>
                {detail.data.blocked_reason_code && (
                  <div className="alert">
                    {t('yard:visit.blocked', { reason: detail.data.blocked_reason_code })}
                  </div>
                )}
                <ul className="timeline-list">
                  {detail.data.events.map((event) => (
                    <li
                      key={`${event.occurred_at}-${event.event_type}`}
                    >
                      <span className="timeline-list__time">
                        {format.dateTime(event.occurred_at)}
                      </span>
                      <span className="row-actions">
                        <StatusPill tone={event.source === 'manual' ? 'waiting' : 'running'}>
                          {t(`yard:visit.eventSource.${event.source}`)}
                        </StatusPill>
                        <span>{event.event_type}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>
      </div>

      <VisitDetailModal visitId={detailModal} onClose={() => setDetailModal(null)} />
    </div>
  )
}
