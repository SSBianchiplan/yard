import type { PointerEvent as ReactPointerEvent, WheelEvent as ReactWheelEvent } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'

export interface MapBox {
  id: string
  code: string
  x: number
  y: number
  width: number
  height: number
}

export interface MapZone extends MapBox {
  kind: string
  colorToken?: string | null
}

export interface MapSlot extends MapBox {
  status: string
  occupied: boolean
  plate?: string | null
  visitId?: string | null
  /** Dwell em segundos: acima do alvo a vaga vira exceção e ganha cor. */
  dwellSeconds?: number | null
}

export interface MapDock extends MapBox {
  status: string
  plate?: string | null
  visitId?: string | null
}

export interface MapPoint {
  id: string
  code: string
  x: number
  y: number
}

export interface YardMapProps {
  zones: MapZone[]
  slots: MapSlot[]
  docks: MapDock[]
  gates?: MapPoint[]
  scales?: MapPoint[]
  selectedSlotId?: string | null
  onSelectSlot?: (slot: MapSlot) => void
  onSelectDock?: (dock: MapDock) => void
  /** Arrastar veículo de uma vaga para outra: a tela decide se confirma. */
  onMoveVehicle?: (fromSlot: MapSlot, toSlot: MapSlot) => void
  /** Limite de dwell (s) acima do qual a vaga é pintada como exceção. */
  dwellAlarmSeconds?: number
  /** Legenda e rótulos já traduzidos pela tela. */
  legend?: { free: string; occupied: string; over: string; blocked: string }
  labels?: { fit: string; zoomIn: string; zoomOut: string }
}

const PADDING = 30

/** Fonte que faz a placa caber na vaga — no maior eixo dela. */
function plateFontSize(slot: MapSlot): number {
  const along = Math.max(slot.width, slot.height)
  const across = Math.min(slot.width, slot.height)
  // ~0.62em por caractere em fonte monoespaçada, com folga de 2px nas bordas.
  return Math.max(3, Math.min(across * 0.6, ((along - 2) / 7.2) * 1.6))
}

/**
 * Mapa de pátio em SVG: zonas, vagas, docas, guaritas e balanças.
 *
 * Paleta ISA-101: vaga livre e vaga ocupada são neutras; só dwell estourado e posição
 * bloqueada recebem cor. Se o mapa está colorido, o pátio está ruim — de propósito.
 *
 * O enquadramento sai do conteúdo, não de números fixos: mudou o layout da planta,
 * o mapa continua cabendo na tela. E a placa é desenhada **na vertical, recortada pela
 * própria vaga** — vaga de pátio é estreita e comprida, texto horizontal ali invade a
 * vizinha e o operador lê a placa errada.
 */
export function YardMap({
  zones,
  slots,
  docks,
  gates = [],
  scales = [],
  selectedSlotId,
  onSelectSlot,
  onSelectDock,
  onMoveVehicle,
  dwellAlarmSeconds = 7200,
  legend,
  labels,
}: YardMapProps) {
  const [drag, setDrag] = useState<MapSlot | null>(null)
  const panRef = useRef<{ x: number; y: number } | null>(null)
  const movedRef = useRef(false)

  // Caixa que contém tudo que existe no mapa, com folga para rótulo de guarita.
  const content = useMemo(() => {
    const boxes = [...zones, ...docks, ...slots]
    const points = [...gates, ...scales]
    if (!boxes.length && !points.length) {
      return { x: 0, y: 0, width: 900, height: 420 }
    }
    const xs = [
      ...boxes.map((b) => b.x),
      ...boxes.map((b) => b.x + b.width),
      ...points.map((p) => p.x),
    ]
    const ys = [
      ...boxes.map((b) => b.y),
      ...boxes.map((b) => b.y + b.height),
      ...points.map((p) => p.y),
    ]
    const minX = Math.min(...xs) - PADDING
    const minY = Math.min(...ys) - PADDING
    return {
      x: minX,
      y: minY,
      width: Math.max(...xs) - minX + PADDING,
      height: Math.max(...ys) - minY + PADDING,
    }
  }, [zones, docks, slots, gates, scales])

  const [view, setView] = useState(content)

  // Layout mudou (ou os dados chegaram): reenquadra uma vez.
  const contentKey = `${content.x}:${content.y}:${content.width}:${content.height}`
  useEffect(() => {
    setView(content)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contentKey])

  const zoom = (factor: number, originX?: number, originY?: number) => {
    setView((v) => {
      const width = Math.min(content.width * 4, Math.max(content.width / 12, v.width * factor))
      const height = width * (v.height / v.width)
      // Mantém o ponto sob o cursor parado — zoom que "foge" do dedo é zoom irritante.
      const cx = originX ?? v.x + v.width / 2
      const cy = originY ?? v.y + v.height / 2
      return {
        x: cx - ((cx - v.x) * width) / v.width,
        y: cy - ((cy - v.y) * height) / v.height,
        width,
        height,
      }
    })
  }

  const toSvgPoint = (event: { clientX: number; clientY: number }, element: SVGSVGElement) => {
    const rect = element.getBoundingClientRect()
    return {
      x: view.x + ((event.clientX - rect.left) / rect.width) * view.width,
      y: view.y + ((event.clientY - rect.top) / rect.height) * view.height,
    }
  }

  const onWheel = (event: ReactWheelEvent<SVGSVGElement>) => {
    const point = toSvgPoint(event, event.currentTarget)
    zoom(event.deltaY > 0 ? 1.15 : 0.87, point.x, point.y)
  }

  const onPointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    panRef.current = { x: event.clientX, y: event.clientY }
    movedRef.current = false
  }

  const onPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!panRef.current) return
    const rect = event.currentTarget.getBoundingClientRect()
    const dx = ((event.clientX - panRef.current.x) / rect.width) * view.width
    const dy = ((event.clientY - panRef.current.y) / rect.height) * view.height
    if (Math.abs(dx) > 1 || Math.abs(dy) > 1) movedRef.current = true
    panRef.current = { x: event.clientX, y: event.clientY }
    setView((v) => ({ ...v, x: v.x - dx, y: v.y - dy }))
  }

  const endPan = () => {
    panRef.current = null
  }

  const slotClass = (slot: MapSlot) => {
    if (slot.status !== 'available') return 'ds-map__slot ds-map__slot--blocked'
    if (slot.occupied && (slot.dwellSeconds ?? 0) > dwellAlarmSeconds)
      return 'ds-map__slot ds-map__slot--over'
    if (slot.occupied) return 'ds-map__slot ds-map__slot--occupied'
    return 'ds-map__slot ds-map__slot--free'
  }

  return (
    <div className="ds-map">
      <svg
        className="ds-map__canvas"
        viewBox={`${view.x} ${view.y} ${view.width} ${view.height}`}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endPan}
        onPointerLeave={endPan}
        role="img"
      >
        <defs>
          {/* Cada vaga recorta o próprio rótulo: placa não invade a vaga vizinha. */}
          {slots.map((slot) => (
            <clipPath id={`clip-${slot.id}`} key={`clip-${slot.id}`}>
              <rect x={slot.x} y={slot.y} width={slot.width} height={slot.height} />
            </clipPath>
          ))}
        </defs>

        {zones.map((zone) => (
          <g key={zone.id}>
            <rect
              className="ds-map__zone"
              x={zone.x}
              y={zone.y}
              width={zone.width}
              height={zone.height}
              rx={3}
              fill={zone.colorToken ? `var(${zone.colorToken})` : 'var(--color-surface-sunken)'}
            />
            <text className="ds-map__zone-label" x={zone.x + 8} y={zone.y + 16}>
              {zone.code}
            </text>
          </g>
        ))}

        {slots.map((slot) => {
          const cx = slot.x + slot.width / 2
          const cy = slot.y + slot.height / 2
          return (
            <g
              key={slot.id}
              onPointerDown={() => slot.occupied && setDrag(slot)}
              onPointerUp={() => {
                if (drag && drag.id !== slot.id && !slot.occupied) {
                  onMoveVehicle?.(drag, slot)
                } else if (!movedRef.current) {
                  onSelectSlot?.(slot)
                }
                setDrag(null)
              }}
            >
              <rect
                className={`${slotClass(slot)}${
                  selectedSlotId === slot.id ? ' ds-map__slot--selected' : ''
                }`}
                x={slot.x}
                y={slot.y}
                width={slot.width}
                height={slot.height}
                rx={1.5}
              >
                <title>{slot.plate ? `${slot.code} · ${slot.plate}` : slot.code}</title>
              </rect>
              {slot.plate && (
                <text
                  className="ds-map__slot-plate"
                  x={cx}
                  y={cy}
                  textAnchor="middle"
                  dominantBaseline="central"
                  clipPath={`url(#clip-${slot.id})`}
                  /* A fonte acompanha a vaga: placa de 7 caracteres tem de caber na
                     largura sem invadir a vizinha. Vaga estreita usa texto vertical. */
                  fontSize={plateFontSize(slot)}
                  transform={
                    slot.width >= slot.height ? undefined : `rotate(-90 ${cx} ${cy})`
                  }
                >
                  {slot.plate}
                </text>
              )}
              {!slot.plate && (
                <text
                  className="ds-map__slot-code"
                  x={cx}
                  y={slot.y + slot.height - 3}
                  textAnchor="middle"
                >
                  {slot.code}
                </text>
              )}
            </g>
          )
        })}

        {docks.map((dock) => (
          <g key={dock.id} onPointerUp={() => !movedRef.current && onSelectDock?.(dock)}>
            <rect
              className={`ds-map__dock${
                dock.status === 'occupied'
                  ? ' ds-map__dock--occupied'
                  : dock.status === 'blocked'
                    ? ' ds-map__dock--blocked'
                    : ''
              }`}
              x={dock.x}
              y={dock.y}
              width={dock.width}
              height={dock.height}
              rx={1.5}
            >
              <title>{dock.plate ? `${dock.code} · ${dock.plate}` : dock.code}</title>
            </rect>
            <text
              className="ds-map__dock-label"
              x={dock.x + dock.width / 2}
              y={dock.y + dock.height / 2}
              textAnchor="middle"
              dominantBaseline="central"
            >
              {dock.code}
            </text>
          </g>
        ))}

        {scales.map((scale) => (
          <g key={scale.id}>
            <rect
              className="ds-map__scale"
              x={scale.x}
              y={scale.y}
              width={54}
              height={18}
              rx={2}
            />
            <text
              className="ds-map__point-label"
              x={scale.x + 27}
              y={scale.y + 9}
              textAnchor="middle"
              dominantBaseline="central"
            >
              {scale.code}
            </text>
          </g>
        ))}

        {gates.map((gate) => (
          <g key={gate.id}>
            <circle className="ds-map__point" cx={gate.x} cy={gate.y} r={9} />
            <text
              className="ds-map__point-label"
              x={gate.x}
              y={gate.y + 22}
              textAnchor="middle"
            >
              {gate.code}
            </text>
          </g>
        ))}
      </svg>

      {labels && (
        <div className="ds-map__toolbar">
          <button type="button" className="ds-btn" onClick={() => zoom(0.8)}>
            {labels.zoomIn}
          </button>
          <button type="button" className="ds-btn" onClick={() => zoom(1.25)}>
            {labels.zoomOut}
          </button>
          <button type="button" className="ds-btn" onClick={() => setView(content)}>
            {labels.fit}
          </button>
        </div>
      )}

      {legend && (
        <div className="ds-map__legend">
          <LegendItem color="var(--color-surface-raised)" label={legend.free} />
          <LegendItem color="var(--color-surface-sunken)" label={legend.occupied} />
          <LegendItem color="var(--color-alarm-high)" label={legend.over} />
          <LegendItem color="var(--color-alarm-low)" label={legend.blocked} />
        </div>
      )}
    </div>
  )
}

function LegendItem({ color, label }: { color: string; label: string }) {
  return (
    <span className="ds-map__legend-item">
      <span className="ds-map__legend-swatch" style={{ background: color }} />
      {label}
    </span>
  )
}
