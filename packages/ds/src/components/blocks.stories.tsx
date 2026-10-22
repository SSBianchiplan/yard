import type { Meta, StoryObj } from '@storybook/react'
import { DataTable } from './DataTable'
import type { Column } from './DataTable'
import { KpiTile } from './KpiTile'
import { StatusPill } from './StatusPill'
import { YardMap } from './YardMap'
import type { MapDock, MapSlot, MapZone } from './YardMap'

const meta: Meta = { title: 'Blocos industriais' }
export default meta

type Row = { id: string; reference: string; plate: string; state: string; dwell: number }

const rows: Row[] = Array.from({ length: 5000 }, (_, i) => ({
  id: String(i),
  reference: `YRD-2026-${String(i + 1).padStart(6, '0')}`,
  plate: `ABC${String(i % 10)}D${String(i % 90).padStart(2, '0')}`,
  state: ['in_yard', 'at_dock', 'at_gate_in', 'departed'][i % 4],
  dwell: 600 + (i % 90) * 120,
}))

const columns: Column<Row>[] = [
  { key: 'plate', header: 'Placa', width: 120, pinned: true, sortable: true, value: (r) => r.plate },
  { key: 'reference', header: 'Visita', width: 170, sortable: true, value: (r) => r.reference },
  {
    key: 'state',
    header: 'Estado',
    width: 140,
    render: (r) => (
      <StatusPill tone={r.state === 'at_dock' ? 'moving' : 'running'}>{r.state}</StatusPill>
    ),
  },
  {
    key: 'dwell',
    header: 'Dwell (min)',
    width: 110,
    align: 'right',
    sortable: true,
    value: (r) => Math.round(r.dwell / 60),
  },
]

export const TabelaDensa: StoryObj = {
  name: 'DataTable · 5.000 linhas',
  render: () => (
    <div style={{ height: 420 }}>
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        emptyLabel="Sem veículos"
        footer={`${rows.length} linhas`}
      />
    </div>
  ),
}

export const Kpis: StoryObj = {
  render: () => (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 'var(--space-3)' }}>
      <KpiTile label="Veículos em pátio" value="38" footer="pico do turno: 54" />
      <KpiTile label="Ocupação de vaga" value="32,8" unit="%" />
      <KpiTile label="Dwell p95" value="2h 14min" severity="warn" footer="meta 1h 30min" />
      <KpiTile label="Dwell estourado" value="6" severity="alarm" footer="ação da torre" />
    </div>
  ),
}

const zones: MapZone[] = [
  { id: 'a', code: 'Z-A', kind: 'parking', x: 0, y: 0, width: 220, height: 160, colorToken: '--color-zone-a' },
  { id: 'b', code: 'Z-B', kind: 'parking', x: 240, y: 0, width: 220, height: 160, colorToken: '--color-zone-b' },
]

const slots: MapSlot[] = zones.flatMap((zone, z) =>
  Array.from({ length: 30 }, (_, n) => {
    const [row, col] = [Math.floor(n / 10), n % 10]
    const occupied = (n + z) % 3 === 0
    return {
      id: `${zone.id}-${n}`,
      code: `${zone.code.slice(2)}-${String(n + 1).padStart(2, '0')}`,
      x: zone.x + 8 + col * 20,
      y: zone.y + 12 + row * 48,
      width: 16,
      height: 40,
      status: n === 29 ? 'maintenance' : 'available',
      occupied,
      plate: occupied ? `AB${n}C${z}` : null,
      dwellSeconds: occupied ? 1200 + n * 400 : null,
    }
  }),
)

const docks: MapDock[] = Array.from({ length: 12 }, (_, i) => ({
  id: `d${i}`,
  code: `DOCK-${String(i + 1).padStart(2, '0')}`,
  x: 500,
  y: 10 + i * 26,
  width: 40,
  height: 20,
  status: i % 4 === 0 ? 'occupied' : 'available',
  plate: i % 4 === 0 ? `XY${i}Z00` : null,
}))

export const Mapa: StoryObj = {
  name: 'YardMap · zonas, vagas e docas',
  render: () => (
    <div style={{ height: 420, border: '1px solid var(--color-border)' }}>
      <YardMap
        zones={zones}
        slots={slots}
        docks={docks}
        gates={[{ id: 'g1', code: 'GATE-01', x: -40, y: 60 }]}
        scales={[{ id: 's1', code: 'SCALE-01', x: 470, y: 330 }]}
        legend={{ free: 'Livre', occupied: 'Ocupada', over: 'Dwell estourado', blocked: 'Bloqueada' }}
      />
    </div>
  ),
}
