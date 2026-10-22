import { Button, DataTable, Input, Modal, Select, YardMap } from '@gplansis/ds'
import type { Column } from '@gplansis/ds'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'

import { useErrorMessage } from '@/components/VisitStatus'
import type { CfgZone, LayoutEntity, PlantLayout } from '@/lib/api'
import { AREA_KINDS, yardConfigApi } from '@/lib/api'

type Row = Record<string, unknown> & { id: string; code: string }
type FieldType = 'text' | 'number' | 'select' | 'checkbox'
interface FieldSpec {
  name: string
  label: string
  type: FieldType
  options?: { value: string; label: string }[]
}

const ENTITIES: LayoutEntity[] = ['zone', 'slot', 'dock', 'gate', 'scale']

const DEFAULTS: Record<LayoutEntity, Record<string, unknown>> = {
  zone: { code: '', kind: 'parking', x: 0, y: 0, width: 200, height: 150, color_token: null },
  slot: {
    code: '',
    kind: 'parking',
    status: 'available',
    x: 0,
    y: 0,
    width: 38,
    height: 24,
    length_m: 18,
    notes: '',
  },
  dock: { code: '', zone_id: '', direction: 'inbound', status: 'available', x: 0, y: 0, width: 66, height: 34 },
  gate: { code: '', direction: 'both', x: -55, y: 0, active: true },
  scale: { code: '', capacity_kg: 80000, division_kg: 20, x: 0, y: 0, active: true },
}

const EDITABLE: Record<LayoutEntity, string[]> = {
  zone: ['code', 'kind', 'x', 'y', 'width', 'height'],
  slot: ['code', 'zone_id', 'kind', 'status', 'x', 'y', 'width', 'height', 'length_m', 'notes'],
  dock: ['code', 'zone_id', 'direction', 'status', 'x', 'y', 'width', 'height'],
  gate: ['code', 'direction', 'x', 'y', 'active'],
  scale: ['code', 'capacity_kg', 'division_kg', 'x', 'y', 'active'],
}

function rowsOf(layout: PlantLayout | undefined, entity: LayoutEntity): Row[] {
  if (!layout) return []
  const map = {
    zone: layout.zones,
    slot: layout.slots,
    dock: layout.docks,
    gate: layout.gates,
    scale: layout.scales,
  }
  return map[entity] as unknown as Row[]
}

export function YardEditor() {
  const { plantId = '' } = useParams()
  const { t } = useTranslation(['admin', 'common', 'yard'])
  const errorMessage = useErrorMessage()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [tab, setTab] = useState<LayoutEntity>('slot')
  const [editing, setEditing] = useState<{ entity: LayoutEntity; draft: Row | null } | null>(null)
  const [grid, setGrid] = useState<{ zone: CfgZone; values: Record<string, number | string> } | null>(
    null,
  )
  const [notice, setNotice] = useState<string | null>(null)

  const layout = useQuery({
    queryKey: ['yard-config', 'layout', plantId],
    queryFn: () => yardConfigApi.layout(plantId),
    enabled: Boolean(plantId),
  })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['yard-config', 'layout', plantId] })
    void queryClient.invalidateQueries({ queryKey: ['plants'] })
    void queryClient.invalidateQueries({ queryKey: ['yard'] })
  }

  const zoneOptions = useMemo(
    () => (layout.data?.zones ?? []).map((zone) => ({ value: zone.id, label: zone.code })),
    [layout.data],
  )
  const zoneCode = (id: unknown) => layout.data?.zones.find((zone) => zone.id === id)?.code ?? ''

  const option = (group: string, values: readonly string[]) =>
    values.map((value) => ({ value, label: t(`admin:${group}.${value}`) }))

  const fields: Record<string, FieldSpec> = {
    code: { name: 'code', label: t('admin:editor.code'), type: 'text' },
    kind: { name: 'kind', label: t('admin:editor.kind'), type: 'select', options: option('kind', AREA_KINDS) },
    status: {
      name: 'status',
      label: t('admin:editor.status'),
      type: 'select',
      options:
        editing?.entity === 'dock'
          ? option('dockStatus', ['available', 'occupied', 'blocked'])
          : option('slotStatus', ['available', 'blocked', 'maintenance']),
    },
    zone_id: {
      name: 'zone_id',
      label: t('admin:editor.zone'),
      type: 'select',
      options:
        editing?.entity === 'dock'
          ? [{ value: '', label: t('admin:editor.noZone') }, ...zoneOptions]
          : zoneOptions,
    },
    direction: {
      name: 'direction',
      label: t('admin:editor.direction'),
      type: 'select',
      options:
        editing?.entity === 'gate'
          ? option('gateDirection', ['in', 'out', 'both'])
          : option('dockDirection', ['inbound', 'outbound', 'both']),
    },
    x: { name: 'x', label: t('admin:editor.x'), type: 'number' },
    y: { name: 'y', label: t('admin:editor.y'), type: 'number' },
    width: { name: 'width', label: t('admin:editor.width'), type: 'number' },
    height: { name: 'height', label: t('admin:editor.height'), type: 'number' },
    length_m: { name: 'length_m', label: t('admin:editor.length'), type: 'number' },
    capacity_kg: { name: 'capacity_kg', label: t('admin:editor.capacity'), type: 'number' },
    division_kg: { name: 'division_kg', label: t('admin:editor.division'), type: 'number' },
    notes: { name: 'notes', label: t('admin:editor.notes'), type: 'text' },
    active: { name: 'active', label: t('admin:editor.active'), type: 'checkbox' },
  }

  const save = useMutation({
    mutationFn: async ({ entity, draft }: { entity: LayoutEntity; draft: Row }) => {
      const body: Record<string, unknown> = {}
      for (const key of EDITABLE[entity]) {
        let value = draft[key]
        if (key === 'zone_id' && value === '') value = null
        if (key === 'notes' && value === '') value = null
        body[key] = value
      }
      if (draft.id) return yardConfigApi.updateElement(entity, draft.id, body)
      return yardConfigApi.createElement(entity, plantId, body)
    },
    onSuccess: () => {
      setEditing(null)
      setNotice(t('admin:editor.saved'))
      refresh()
    },
  })

  const remove = useMutation({
    mutationFn: ({ entity, id }: { entity: LayoutEntity; id: string }) =>
      yardConfigApi.deleteElement(entity, id),
    onSuccess: () => {
      setEditing(null)
      setNotice(t('admin:editor.deleted'))
      refresh()
    },
  })

  const generate = useMutation({
    mutationFn: () => {
      if (!grid) throw new Error('grid')
      const { prefix, ...numbers } = grid.values
      return yardConfigApi.generateSlots(grid.zone.id, {
        prefix,
        ...Object.fromEntries(Object.entries(numbers).map(([key, value]) => [key, Number(value)])),
      })
    },
    onSuccess: (slots) => {
      setGrid(null)
      setEditing(null)
      setTab('slot')
      setNotice(t('admin:editor.generated', { count: slots.length }))
      refresh()
    },
  })

  const openNew = (entity: LayoutEntity) => {
    const base = { ...DEFAULTS[entity], id: '', code: '' } as Row
    if (entity === 'slot') base.zone_id = layout.data?.zones[0]?.id ?? ''
    save.reset()
    remove.reset()
    setEditing({ entity, draft: base })
  }
  const openRow = (entity: LayoutEntity, row: Row) => {
    save.reset()
    remove.reset()
    setEditing({
      entity,
      draft: { ...row, zone_id: row.zone_id ?? '', notes: row.notes ?? '' } as Row,
    })
  }

  const columns: Column<Row>[] = [
    { key: 'code', header: t('admin:editor.code'), width: 140, pinned: true, sortable: true, value: (r) => r.code },
    ...(tab === 'zone' || tab === 'slot'
      ? [{ key: 'kind', header: t('admin:editor.kind'), width: 150, render: (r: Row) => t(`admin:kind.${String(r.kind)}`) }]
      : []),
    ...(tab === 'slot' || tab === 'dock'
      ? [
          { key: 'zone', priority: 'secondary' as const, header: t('admin:editor.zone'), width: 110, value: (r: Row) => zoneCode(r.zone_id) },
          {
            key: 'status',
            header: t('admin:editor.status'),
            width: 120,
            render: (r: Row) => t(`admin:${tab === 'dock' ? 'dockStatus' : 'slotStatus'}.${String(r.status)}`),
          },
        ]
      : []),
    ...(tab === 'dock' || tab === 'gate'
      ? [
          {
            key: 'direction',
            header: t('admin:editor.direction'),
            width: 130,
            render: (r: Row) => t(`admin:${tab === 'gate' ? 'gateDirection' : 'dockDirection'}.${String(r.direction)}`),
          },
        ]
      : []),
    ...(tab === 'scale'
      ? [{ key: 'capacity', header: t('admin:editor.capacity'), width: 130, align: 'right' as const, value: (r: Row) => Number(r.capacity_kg) }]
      : []),
    {
      key: 'pos',
      priority: 'detail',
      header: `${t('admin:editor.x')} · ${t('admin:editor.y')}`,
      width: 120,
      value: (r) => `${Number(r.x).toFixed(0)} · ${Number(r.y).toFixed(0)}`,
    },
  ]

  const data = layout.data
  const draft = editing?.draft

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1 className="page__title">
            {t('admin:editor.title')} · {data?.plant.code}
          </h1>
          <span className="page__subtitle">
            {data?.plant.name} ·{' '}
            {data &&
              t('admin:yards.counts', {
                zones: data.zones.length,
                slots: data.slots.length,
                docks: data.docks.length,
                gates: data.gates.length,
                scales: data.scales.length,
              })}
          </span>
        </div>
        <Button onClick={() => navigate('/admin/yards')}>{t('admin:yards.back')}</Button>
      </div>

      {notice && (
        <div className="alert alert--ok" role="status" onClick={() => setNotice(null)}>
          {notice}
        </div>
      )}

      <div className="editor">
        <section className="panel">
          <div className="panel__title">
            <span>{t('admin:editor.preview')}</span>
            <span className="page__subtitle">{t('admin:editor.hint')}</span>
          </div>
          <div className="panel__body editor__map">
            {data && (
              <YardMap
                zones={data.zones.map((zone) => ({ ...zone, colorToken: zone.color_token }))}
                slots={data.slots.map((slot) => ({ ...slot, occupied: false }))}
                docks={data.docks.map((dock) => ({ ...dock }))}
                gates={data.gates}
                scales={data.scales}
                onSelectSlot={(slot) => {
                  const row = rowsOf(data, 'slot').find((r) => r.id === slot.id)
                  if (row) openRow('slot', row)
                }}
                onSelectDock={(dock) => {
                  const row = rowsOf(data, 'dock').find((r) => r.id === dock.id)
                  if (row) openRow('dock', row)
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
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel__title">
            <div className="tabs" role="tablist">
              {ENTITIES.map((entity) => (
                <button
                  key={entity}
                  type="button"
                  role="tab"
                  aria-selected={tab === entity}
                  className={`tabs__tab${tab === entity ? ' tabs__tab--active' : ''}`}
                  onClick={() => setTab(entity)}
                >
                  {t(`admin:editor.tabs.${entity}`)} ({rowsOf(data, entity).length})
                </button>
              ))}
            </div>
            <Button variant="primary" onClick={() => openNew(tab)}>
              {t('admin:editor.add')}
            </Button>
          </div>
          <div className="panel__body">
            <DataTable
              columns={columns}
              rows={rowsOf(data, tab)}
              rowKey={(row) => row.id}
              onRowClick={(row) => openRow(tab, row)}
              emptyLabel={t('common:state.empty')}
              footer={t('admin:editor.count', { count: rowsOf(data, tab).length })}
            />
          </div>
        </section>
      </div>

      <Modal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={
          draft?.id ? t('admin:editor.editItem', { code: draft.code }) : t('admin:editor.newItem')
        }
        subtitle={editing ? t(`admin:editor.tabs.${editing.entity}`) : undefined}
        closeLabel={t('common:action.close')}
        size="wide"
        actions={
          editing &&
          draft && (
            <>
              {draft.id && (
                <Button
                  variant="danger"
                  disabled={remove.isPending}
                  onClick={() => {
                    if (window.confirm(t('admin:editor.confirmDelete', { code: draft.code }))) {
                      remove.mutate({ entity: editing.entity, id: draft.id })
                    }
                  }}
                >
                  {t('admin:editor.delete')}
                </Button>
              )}
              {editing.entity === 'zone' && draft.id && (
                <Button
                  onClick={() =>
                    setGrid({
                      zone: draft as unknown as CfgZone,
                      values: {
                        prefix: draft.code,
                        rows: 3,
                        cols: 6,
                        start_number: 1,
                        slot_width: 38,
                        slot_height: 24,
                        gap_x: 7,
                        gap_y: 9,
                      },
                    })
                  }
                >
                  {t('admin:editor.generate')}
                </Button>
              )}
              <Button onClick={() => setEditing(null)}>{t('common:action.cancel')}</Button>
              <Button
                variant="primary"
                disabled={!draft.code || save.isPending}
                onClick={() => save.mutate({ entity: editing.entity, draft })}
              >
                {t('common:action.save')}
              </Button>
            </>
          )
        }
      >
        {editing && draft && (
          <div className="stack">
            <div className="form-grid form-grid--bare">
              {EDITABLE[editing.entity].map((key) => {
                const spec = fields[key]
                if (!spec) return null
                const value = draft[key]
                const set = (next: unknown) =>
                  setEditing({ entity: editing.entity, draft: { ...draft, [key]: next } })
                if (spec.type === 'select') {
                  return (
                    <Select
                      key={key}
                      label={spec.label}
                      value={String(value ?? '')}
                      options={spec.options ?? []}
                      onChange={(event) => set(event.target.value)}
                    />
                  )
                }
                if (spec.type === 'checkbox') {
                  return (
                    <label key={key} className="check-list__item">
                      <input
                        type="checkbox"
                        checked={Boolean(value)}
                        onChange={(event) => set(event.target.checked)}
                      />
                      <span>{spec.label}</span>
                    </label>
                  )
                }
                return (
                  <Input
                    key={key}
                    label={spec.label}
                    type={spec.type === 'number' ? 'number' : 'text'}
                    step={spec.type === 'number' ? 'any' : undefined}
                    operational={key === 'code'}
                    value={value == null ? '' : String(value)}
                    onChange={(event) =>
                      set(spec.type === 'number' ? Number(event.target.value) : event.target.value)
                    }
                  />
                )
              })}
            </div>
            {(save.error || remove.error) && (
              <div className="alert" role="alert">
                {errorMessage(save.error ?? remove.error)}
              </div>
            )}
          </div>
        )}
      </Modal>

      <Modal
        open={grid !== null}
        onClose={() => setGrid(null)}
        title={t('admin:editor.generateTitle', { zone: grid?.zone.code ?? '' })}
        closeLabel={t('common:action.close')}
        actions={
          <>
            <Button onClick={() => setGrid(null)}>{t('common:action.cancel')}</Button>
            <Button
              variant="primary"
              disabled={generate.isPending}
              onClick={() => generate.mutate()}
            >
              {t('admin:editor.generate')}
            </Button>
          </>
        }
      >
        {grid && (
          <div className="stack">
            <div className="form-grid form-grid--bare">
              {(
                [
                  ['prefix', 'admin:editor.prefix'],
                  ['rows', 'admin:editor.rows'],
                  ['cols', 'admin:editor.cols'],
                  ['start_number', 'admin:editor.start'],
                  ['slot_width', 'admin:editor.slotWidth'],
                  ['slot_height', 'admin:editor.slotHeight'],
                  ['gap_x', 'admin:editor.gapX'],
                  ['gap_y', 'admin:editor.gapY'],
                ] as const
              ).map(([key, label]) => (
                <Input
                  key={key}
                  label={t(label)}
                  type={key === 'prefix' ? 'text' : 'number'}
                  operational={key === 'prefix'}
                  value={String(grid.values[key])}
                  onChange={(event) =>
                    setGrid({ ...grid, values: { ...grid.values, [key]: event.target.value } })
                  }
                />
              ))}
            </div>
            {generate.error && (
              <div className="alert" role="alert">
                {errorMessage(generate.error)}
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}
