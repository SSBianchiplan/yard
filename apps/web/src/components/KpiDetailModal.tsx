import { DataTable, DetailRow, Modal } from '@gplansis/ds'
import type { Column } from '@gplansis/ds'
import { useTranslation } from 'react-i18next'

import { VisitStatus } from '@/components/VisitStatus'
import type { Visit, YardMapData, YardOverview } from '@/lib/api'
import { useFormat } from '@/lib/format'

/** Cada card da torre abre um destes. */
export type KpiMetric =
  | 'vehiclesInYard'
  | 'atGateIn'
  | 'atDock'
  | 'slotOccupancy'
  | 'dockOccupancy'
  | 'p95Dwell'
  | 'overTargetDwell'
  | 'manualEventRate'

export interface KpiDetailModalProps {
  metric: KpiMetric | null
  overview?: YardOverview
  visits: Visit[]
  map?: YardMapData
  onClose: () => void
  /** Abre a visita: do número para o caminhão, sem procurar noutra tela. */
  onOpenVisit: (visit: Visit) => void
}

const isOverTarget = (visit: Visit) =>
  visit.target_dwell_minutes > 0 && visit.dwell_seconds > visit.target_dwell_minutes * 60

/**
 * O que há atrás do número.
 *
 * KPI que não abre é placar: informa que algo está ruim e deixa o operador procurar onde.
 * Aqui cada card mostra como a conta é feita, os números vizinhos que dão contexto e a
 * lista nominal por trás dele — e dessa lista se abre a visita para agir.
 */
export function KpiDetailModal({
  metric,
  overview,
  visits,
  map,
  onClose,
  onOpenVisit,
}: KpiDetailModalProps) {
  const { t } = useTranslation(['yard', 'common'])
  const format = useFormat()

  const inYard = visits.filter((visit) => visit.state === 'in_yard')
  const atGate = visits.filter((visit) => visit.state === 'at_gate_in')
  const atDock = visits.filter((visit) => visit.state === 'at_dock')
  const blocked = visits.filter((visit) => visit.blocked_reason_code)
  const overTarget = visits.filter(isOverTarget)
  const slots = map?.slots ?? []
  const docks = map?.docks ?? []

  const byDwell = (rows: Visit[]) => [...rows].sort((a, b) => b.dwell_seconds - a.dwell_seconds)

  const detail: Record<
    KpiMetric,
    { value: string; rows: Visit[]; figures: [string, string][] }
  > = {
    vehiclesInYard: {
      value: format.number(overview?.vehicles_in_yard ?? 0),
      rows: byDwell([...inYard, ...atDock]),
      figures: [
        [t('yard:kpi.detail.inYard'), format.number(inYard.length)],
        [t('yard:kpi.atDock'), format.number(atDock.length)],
        [t('yard:kpi.atGateIn'), format.number(atGate.length)],
        [t('yard:kpi.detail.blocked'), format.number(blocked.length)],
        [t('yard:kpi.detail.avgDwell'), format.duration(overview?.avg_dwell_seconds ?? 0)],
      ],
    },
    atGateIn: {
      value: format.number(overview?.at_gate_in ?? 0),
      rows: byDwell(atGate),
      figures: [
        [t('yard:kpi.detail.gateInToday'), format.number(overview?.gate_in_today ?? 0)],
        [t('yard:kpi.detail.gateOutToday'), format.number(overview?.gate_out_today ?? 0)],
        [
          t('yard:kpi.detail.blocked'),
          format.number(atGate.filter((visit) => visit.blocked_reason_code).length),
        ],
      ],
    },
    atDock: {
      value: format.number(overview?.at_dock ?? 0),
      rows: byDwell(atDock),
      figures: [
        [t('yard:kpi.detail.docksOccupied'), format.number(overview?.docks_occupied ?? 0)],
        [t('yard:kpi.detail.docksTotal'), format.number(overview?.docks_total ?? 0)],
        [
          t('yard:kpi.detail.docksBlocked'),
          format.number(docks.filter((dock) => dock.status === 'blocked').length),
        ],
      ],
    },
    slotOccupancy: {
      value: format.percent(overview?.slot_occupancy_pct ?? 0),
      rows: byDwell(inYard),
      figures: [
        [t('yard:kpi.detail.slotsOccupied'), format.number(overview?.slots_occupied ?? 0)],
        [
          t('yard:kpi.detail.slotsFree'),
          format.number(
            slots.filter((slot) => !slot.occupied && slot.status === 'available').length,
          ),
        ],
        [
          t('yard:kpi.detail.slotsBlocked'),
          format.number(slots.filter((slot) => slot.status !== 'available').length),
        ],
        [t('yard:kpi.detail.slotsTotal'), format.number(overview?.slots_total ?? 0)],
      ],
    },
    dockOccupancy: {
      value: format.percent(overview?.dock_occupancy_pct ?? 0),
      rows: byDwell(atDock),
      figures: [
        [t('yard:kpi.detail.docksOccupied'), format.number(overview?.docks_occupied ?? 0)],
        [
          t('yard:kpi.detail.docksFree'),
          format.number(docks.filter((dock) => dock.status === 'available').length),
        ],
        [
          t('yard:kpi.detail.docksBlocked'),
          format.number(docks.filter((dock) => dock.status === 'blocked').length),
        ],
        [t('yard:kpi.detail.docksTotal'), format.number(overview?.docks_total ?? 0)],
      ],
    },
    p95Dwell: {
      value: format.duration(overview?.p95_dwell_seconds ?? 0),
      rows: byDwell(visits).slice(0, 15),
      figures: [
        [t('yard:kpi.detail.avgDwell'), format.duration(overview?.avg_dwell_seconds ?? 0)],
        [t('yard:kpi.p95Dwell'), format.duration(overview?.p95_dwell_seconds ?? 0)],
        [
          t('yard:kpi.detail.worstDwell'),
          format.duration(Math.max(0, ...visits.map((visit) => visit.dwell_seconds))),
        ],
        [t('yard:kpi.overTargetDwell'), format.number(overTarget.length)],
      ],
    },
    overTargetDwell: {
      value: format.number(overview?.over_target_dwell ?? 0),
      rows: byDwell(overTarget),
      figures: [
        [t('yard:kpi.detail.openVisits'), format.number(visits.length)],
        [t('yard:kpi.detail.blocked'), format.number(blocked.length)],
        [t('yard:kpi.p95Dwell'), format.duration(overview?.p95_dwell_seconds ?? 0)],
      ],
    },
    manualEventRate: {
      value: format.percent(overview?.manual_event_pct ?? 0),
      rows: [],
      figures: [
        [t('yard:kpi.detail.manualShare'), format.percent(overview?.manual_event_pct ?? 0)],
        [
          t('yard:kpi.detail.automaticShare'),
          format.percent(100 - (overview?.manual_event_pct ?? 0)),
        ],
        [t('yard:kpi.detail.gateInToday'), format.number(overview?.gate_in_today ?? 0)],
        [t('yard:kpi.detail.gateOutToday'), format.number(overview?.gate_out_today ?? 0)],
      ],
    },
  }

  const current = metric ? detail[metric] : null

  const columns: Column<Visit>[] = [
    {
      key: 'plate',
      priority: 'essential',
      header: t('yard:visit.column.plate'),
      width: 100,
      value: (visit) => visit.plate,
    },
    {
      key: 'state',
      header: t('yard:visit.column.state'),
      width: 130,
      render: (visit) => <VisitStatus state={visit.state} blocked={Boolean(visit.blocked_reason_code)} />,
    },
    {
      key: 'position',
      priority: 'secondary',
      header: t('yard:visit.column.slot'),
      width: 90,
      value: (visit) => visit.slot_code ?? visit.dock_code ?? '',
    },
    {
      key: 'dwell',
      header: t('yard:visit.column.dwell'),
      width: 90,
      align: 'right',
      sortable: true,
      value: (visit) => visit.dwell_seconds,
      render: (visit) => format.duration(visit.dwell_seconds),
    },
  ]

  return (
    <Modal
      open={Boolean(metric)}
      onClose={onClose}
      size="wide"
      title={metric ? t(`yard:kpi.${metric}`) : ''}
      subtitle={metric ? t(`yard:kpi.detail.how.${metric}`) : undefined}
      closeLabel={t('common:action.close')}
    >
      {current && (
        <div className="stack">
          <div>
            <DetailRow label={t('yard:kpi.detail.current')}>{current.value}</DetailRow>
            {current.figures.map(([label, value]) => (
              <DetailRow key={label} label={label}>
                {value}
              </DetailRow>
            ))}
          </div>

          {current.rows.length > 0 && (
            <div className="stack">
              <span className="page__subtitle">
                {t('yard:kpi.detail.behind', { count: current.rows.length })}
              </span>
              <DataTable
                columns={columns}
                rows={current.rows}
                rowKey={(visit) => visit.id}
                onRowClick={onOpenVisit}
                emptyLabel={t('yard:visit.empty')}
              />
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}
