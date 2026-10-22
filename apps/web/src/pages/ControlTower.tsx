import { Button, DataTable, KpiTile, YardMap } from '@gplansis/ds'
import type { Column, MapSlot } from '@gplansis/ds'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { KpiMetric } from '@/components/KpiDetailModal'
import { KpiDetailModal } from '@/components/KpiDetailModal'
import { VisitDetailModal } from '@/components/VisitDetailModal'
import { VisitStatus, useErrorMessage } from '@/components/VisitStatus'
import type { Visit } from '@/lib/api'
import { api } from '@/lib/api'
import { useUiStore } from '@/lib/uiStore'
import { setPlantTimeZone, useFormat } from '@/lib/format'

export function ControlTower() {
  const { t } = useTranslation(['yard', 'common'])
  const format = useFormat()
  const queryClient = useQueryClient()
  const describeError = useErrorMessage()
  const [selectedSlotId, setSelectedSlotId] = useState<string | null>(null)
  // Clicar numa posição abre o que dá para fazer com ela, não só o que ela é.
  const [detail, setDetail] = useState<{ visitId: string; code: string } | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  // Card é pergunta, não placar: clicar abre as contagens que formam o número.
  const [metric, setMetric] = useState<KpiMetric | null>(null)

  const plantCode = useUiStore((state) => state.plantCode)
  const map = useQuery({
    queryKey: ['yard', 'map', plantCode],
    queryFn: async () => {
      const data = await api.yardMap(plantCode)
      setPlantTimeZone(data.timezone)
      return data
    },
    refetchInterval: 15_000,
  })
  const overview = useQuery({
    queryKey: ['overview'],
    queryFn: api.overview,
    refetchInterval: 15_000,
  })
  const visits = useQuery({
    queryKey: ['visits', 'open'],
    queryFn: () => api.visits({ onlyOpen: true }),
    refetchInterval: 15_000,
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['yard'] })
    void queryClient.invalidateQueries({ queryKey: ['visits'] })
    void queryClient.invalidateQueries({ queryKey: ['overview'] })
  }

  const moveVehicle = useMutation({
    mutationFn: ({ visitId, slotCode }: { visitId: string; slotCode: string }) =>
      api.assignSlot(visitId, slotCode),
    onSuccess: () => {
      setFailure(null)
      invalidate()
    },
    onError: (error) => setFailure(describeError(error)),
  })

  const slots: MapSlot[] = (map.data?.slots ?? []).map((slot) => ({
    id: slot.id,
    code: slot.code,
    x: slot.x,
    y: slot.y,
    width: slot.width,
    height: slot.height,
    status: slot.status,
    occupied: slot.occupied,
    plate: slot.plate,
    visitId: slot.visit_id,
    dwellSeconds: slot.dwell_seconds,
  }))

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
      width: 170,
      value: (visit) => visit.operation_type_code,
      render: (visit) => t(`yard:operation.${visit.operation_type_code}`),
    },
    {
      key: 'slot',
      priority: 'secondary',
      header: t('yard:visit.column.slot'),
      width: 80,
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

  const kpi = overview.data

  return (
    <div className="page">
      <div className="page__header">
        <h1 className="page__title">{t('yard:controlTower.title')}</h1>
        <span className="page__subtitle">
          {t('yard:controlTower.updatedAt', { time: format.time(map.data?.generated_at) })}
        </span>
      </div>

      {failure && <div className="alert">{failure}</div>}

      <div className="kpi-row">
        <KpiTile label={t('yard:kpi.vehiclesInYard')} value={format.number(kpi?.vehicles_in_yard ?? 0)} onClick={() => setMetric('vehiclesInYard')} />
        <KpiTile label={t('yard:kpi.atGateIn')} value={format.number(kpi?.at_gate_in ?? 0)} onClick={() => setMetric('atGateIn')} />
        <KpiTile label={t('yard:kpi.atDock')} value={format.number(kpi?.at_dock ?? 0)} onClick={() => setMetric('atDock')} />
        <KpiTile
          onClick={() => setMetric('slotOccupancy')}
          label={t('yard:kpi.slotOccupancy')}
          value={format.percent(kpi?.slot_occupancy_pct ?? 0)}
          footer={t('yard:kpi.footer.ofTotal', {
            used: format.number(kpi?.slots_occupied ?? 0),
            total: format.number(kpi?.slots_total ?? 0),
          })}
        />
        <KpiTile
          onClick={() => setMetric('dockOccupancy')}
          label={t('yard:kpi.dockOccupancy')}
          value={format.percent(kpi?.dock_occupancy_pct ?? 0)}
          footer={t('yard:kpi.footer.ofTotal', {
            used: format.number(kpi?.docks_occupied ?? 0),
            total: format.number(kpi?.docks_total ?? 0),
          })}
        />
        <KpiTile
          onClick={() => setMetric('p95Dwell')}
          label={t('yard:kpi.p95Dwell')}
          value={format.duration(kpi?.p95_dwell_seconds ?? 0)}
        />
        <KpiTile
          onClick={() => setMetric('overTargetDwell')}
          label={t('yard:kpi.overTargetDwell')}
          value={format.number(kpi?.over_target_dwell ?? 0)}
          severity={(kpi?.over_target_dwell ?? 0) > 0 ? 'alarm' : 'normal'}
        />
        <KpiTile
          onClick={() => setMetric('manualEventRate')}
          label={t('yard:kpi.manualEventRate')}
          value={format.percent(kpi?.manual_event_pct ?? 0)}
          severity={(kpi?.manual_event_pct ?? 0) > 15 ? 'warn' : 'normal'}
          footer={t('yard:kpi.footer.automaticShare', {
            value: format.percent(100 - (kpi?.manual_event_pct ?? 0)),
          })}
        />
      </div>

      <div className="tower">
        <section className="panel">
          <div className="panel__title">
            <span>{t('yard:controlTower.mapTitle')}</span>
            <Button variant="ghost" onClick={() => void map.refetch()}>
              {t('common:action.refresh')}
            </Button>
          </div>
          <div className="panel__body">
            <YardMap
              zones={(map.data?.zones ?? []).map((zone) => ({
                id: zone.id,
                code: zone.code,
                kind: zone.kind,
                x: zone.x,
                y: zone.y,
                width: zone.width,
                height: zone.height,
                colorToken: zone.color_token,
              }))}
              slots={slots}
              docks={(map.data?.docks ?? []).map((dock) => ({
                id: dock.id,
                code: dock.code,
                x: dock.x,
                y: dock.y,
                width: dock.width,
                height: dock.height,
                status: dock.status,
                plate: dock.plate,
                visitId: dock.visit_id,
              }))}
              gates={map.data?.gates ?? []}
              scales={map.data?.scales ?? []}
              selectedSlotId={selectedSlotId}
              onSelectSlot={(slot) => {
                setSelectedSlotId(slot.id)
                if (slot.visitId) setDetail({ visitId: slot.visitId, code: slot.code })
              }}
              onSelectDock={(dock) => {
                if (dock.visitId) setDetail({ visitId: dock.visitId, code: dock.code })
              }}
              onMoveVehicle={(from, to) => {
                if (!from.visitId) return
                moveVehicle.mutate({ visitId: from.visitId, slotCode: to.code })
              }}
              legend={{
                free: t('yard:map.legend.free'),
                occupied: t('yard:map.legend.occupied'),
                over: t('yard:map.legend.over'),
                blocked: t('yard:map.legend.blocked'),
              }}
              labels={{
                fit: t('yard:map.fit'),
                zoomIn: t('yard:map.zoomIn'),
                zoomOut: t('yard:map.zoomOut'),
              }}
            />
          </div>
        </section>

        <section className="panel">
          <div className="panel__title">
            <span>{t('yard:controlTower.queueTitle')}</span>
            <span>{format.number(visits.data?.length ?? 0)}</span>
          </div>
          <div className="panel__body">
            <DataTable
              columns={columns}
              rows={visits.data ?? []}
              rowKey={(visit) => visit.id}
              selectedKey={
                slots.find((slot) => slot.id === selectedSlotId)?.visitId ?? null
              }
              onRowClick={(visit) =>
                setDetail({ visitId: visit.id, code: visit.slot_code ?? visit.plate })
              }
              emptyLabel={t('yard:visit.empty')}
            />
          </div>
        </section>
      </div>

      <KpiDetailModal
        metric={metric}
        overview={overview.data}
        visits={visits.data ?? []}
        map={map.data}
        onClose={() => setMetric(null)}
        onOpenVisit={(visit) => {
          setMetric(null)
          setDetail({ visitId: visit.id, code: visit.slot_code ?? visit.dock_code ?? visit.plate })
        }}
      />

      <VisitDetailModal
        visitId={detail?.visitId ?? null}
        originCode={detail?.code}
        onClose={() => setDetail(null)}
      />
    </div>
  )
}
