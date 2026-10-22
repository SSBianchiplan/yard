import type { PointerEvent as ReactPointerEvent } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'

export interface TimelineDock {
  id: string
  code: string
  status: string
}

export interface TimelineBooking {
  id: string
  dockId: string
  /** Rótulo curto já pronto pela tela (placa, referência). */
  label: string
  startsAt: Date
  endsAt: Date
  state: string
  priorityRank?: number
  conflicting?: boolean
}

/** Abaixo disto o ponteiro não andou: é clique, não arraste. */
const DRAG_THRESHOLD_PX = 5

export interface DockTimelineProps {
  docks: TimelineDock[]
  bookings: TimelineBooking[]
  from: Date
  to: Date
  /** Granularidade de encaixe ao arrastar, em minutos. */
  stepMinutes?: number
  selectedId?: string | null
  onSelect?: (booking: TimelineBooking) => void
  /** Solta a janela em outra doca/horário — a tela decide se confirma. */
  onMove?: (booking: TimelineBooking, dockId: string, startsAt: Date) => void
  /**
   * Clique num vão livre da faixa. É o gesto que o programador já tenta fazer por
   * instinto: "quero uma janela aqui". Sem isso, ele vai procurar um botão noutro canto.
   */
  onEmptyClick?: (dockId: string, startsAt: Date) => void
  /** Rótulos já traduzidos. */
  labels: { hour: string; empty: string; blocked: string; now?: string }
  locale?: string
  /** Fuso de exibição — o da planta, não o do navegador (regra do projeto). */
  timeZone?: string
}

/**
 * Gantt de janelas de doca. Arrastar reagenda; colisão aparece ANTES do drop, porque
 * descobrir o conflito depois de soltar é descobrir tarde.
 *
 * Cor só em anormalidade (ISA-101): janela normal é neutra, conflito e bloqueio têm cor.
 */
export function DockTimeline({
  docks,
  bookings,
  from,
  to,
  stepMinutes = 15,
  selectedId,
  onSelect,
  onMove,
  onEmptyClick,
  labels,
  locale = 'pt-BR',
  timeZone,
}: DockTimelineProps) {
  const [drag, setDrag] = useState<{
    booking: TimelineBooking
    dockId: string
    startsAt: Date
  } | null>(null)
  /**
   * Clique não é arraste.
   *
   * O ponteiro descia na faixa e o `pointerup` já reposicionava a janela na coordenada do
   * cursor: clicar na placa para abrir o detalhe reprogramava o agendamento — e sempre um
   * pouco para a frente, porque o clique cai à direita do início da faixa. Agora o arraste
   * só começa depois de o ponteiro andar de verdade, e guarda **onde na faixa** foi pego,
   * para a janela seguir o cursor em vez de saltar o início para debaixo dele.
   */
  const pending = useRef<{
    booking: TimelineBooking
    originX: number
    grabMinutes: number
  } | null>(null)
  const dragged = useRef(false)
  const gridRef = useRef<HTMLDivElement>(null)

  const totalMinutes = Math.max(60, (to.getTime() - from.getTime()) / 60000)
  const hours = useMemo(() => {
    const marks: Date[] = []
    const cursor = new Date(from)
    cursor.setMinutes(0, 0, 0)
    while (cursor < to) {
      marks.push(new Date(cursor))
      cursor.setHours(cursor.getHours() + 1)
    }
    return marks
  }, [from, to])

  const pct = (date: Date) => ((date.getTime() - from.getTime()) / 60000 / totalMinutes) * 100

  // "Agora" na régua: sem isso o programador conta coluna para achar o presente.
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000)
    return () => window.clearInterval(timer)
  }, [])
  const nowVisible = now >= from && now <= to
  const nowLeft = pct(now)

  const collides = (booking: TimelineBooking, dockId: string, startsAt: Date) => {
    const duration = booking.endsAt.getTime() - booking.startsAt.getTime()
    const endsAt = new Date(startsAt.getTime() + duration)
    return bookings.some(
      (other) =>
        other.id !== booking.id &&
        other.dockId === dockId &&
        other.startsAt < endsAt &&
        other.endsAt > startsAt,
    )
  }

  const minutesFromPointer = (event: ReactPointerEvent) => {
    const rect = gridRef.current?.getBoundingClientRect()
    if (!rect) return null
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width))
    return ratio * totalMinutes
  }

  const positionFromPointer = (event: ReactPointerEvent, dockId: string, grabMinutes = 0) => {
    const minutes = minutesFromPointer(event)
    if (minutes === null) return null
    const snapped = Math.round(Math.max(0, minutes - grabMinutes) / stepMinutes) * stepMinutes
    return { dockId, startsAt: new Date(from.getTime() + snapped * 60000) }
  }

  const formatHour = (date: Date) =>
    new Intl.DateTimeFormat(locale, {
      hour: '2-digit',
      minute: '2-digit',
      timeZone,
    }).format(date)

  return (
    <div className="ds-timeline">
      <div className="ds-timeline__head">
        <div className="ds-timeline__gutter">{labels.hour}</div>
        <div className="ds-timeline__hours">
          {nowVisible && (
            <span className="ds-timeline__now-label" style={{ left: `${nowLeft}%` }}>
              {labels.now ?? ''}
            </span>
          )}
          {hours.map((hour) => (
            <span
              key={hour.toISOString()}
              className="ds-timeline__hour"
              style={{ left: `${pct(hour)}%` }}
            >
              {formatHour(hour)}
            </span>
          ))}
        </div>
      </div>

      <div className="ds-timeline__body">
        {docks.map((dock) => (
          <div className="ds-timeline__row" key={dock.id}>
            <div className="ds-timeline__gutter" title={dock.code}>
              {dock.code}
            </div>
            <div
              className={`ds-timeline__lane${
                dock.status !== 'available' ? ' ds-timeline__lane--blocked' : ''
              }`}
              ref={dock.id === docks[0]?.id ? gridRef : undefined}
              onPointerMove={(event) => {
                const held = pending.current
                if (!held) return
                // Abaixo do limiar ainda é clique: mão treme, luva escorrega.
                if (!dragged.current && Math.abs(event.clientX - held.originX) < DRAG_THRESHOLD_PX) {
                  return
                }
                dragged.current = true
                const next = positionFromPointer(event, dock.id, held.grabMinutes)
                if (next) setDrag({ booking: held.booking, ...next })
              }}
              onPointerUp={(event) => {
                const held = pending.current
                pending.current = null
                if (!drag) {
                  // Clique em faixa vazia: propõe janela nova ali.
                  const target = event.target as HTMLElement
                  if (!held && target.classList.contains('ds-timeline__lane')) {
                    const spot = positionFromPointer(event, dock.id)
                    if (spot) onEmptyClick?.(dock.id, spot.startsAt)
                  }
                  return
                }
                const next = positionFromPointer(event, dock.id, held?.grabMinutes ?? 0)
                if (next && !collides(drag.booking, next.dockId, next.startsAt)) {
                  onMove?.(drag.booking, next.dockId, next.startsAt)
                }
                setDrag(null)
              }}
            >
              {hours.map((hour) => (
                <span
                  key={`grid-${hour.toISOString()}`}
                  className="ds-timeline__gridline"
                  style={{ left: `${pct(hour)}%` }}
                />
              ))}

              {bookings
                .filter((booking) => booking.dockId === dock.id)
                .map((booking) => {
                  const rawLeft = pct(booking.startsAt)
                  const rawRight = pct(booking.endsAt)
                  // Janela que começa antes (ou termina depois) do período visível é
                  // recortada na borda. Sem isso ela vaza por cima da coluna de docas.
                  const left = Math.max(0, rawLeft)
                  const width = Math.min(100, rawRight) - left
                  const clippedStart = rawLeft < 0
                  const clippedEnd = rawRight > 100
                  if (width <= 0) return null
                  return (
                    <button
                      type="button"
                      key={booking.id}
                      className={[
                        'ds-timeline__booking',
                        `ds-timeline__booking--${booking.state}`,
                        booking.conflicting ? 'ds-timeline__booking--conflict' : '',
                        clippedStart ? 'ds-timeline__booking--from-before' : '',
                        clippedEnd ? 'ds-timeline__booking--into-after' : '',
                        selectedId === booking.id ? 'ds-timeline__booking--selected' : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      style={{ left: `${left}%`, width: `${Math.max(width, 1.5)}%` }}
                      title={booking.label}
                      onClick={() => {
                        // Arrastou: já reprogramou no `pointerup`, não abre o detalhe.
                        if (dragged.current) {
                          dragged.current = false
                          return
                        }
                        onSelect?.(booking)
                      }}
                      onPointerDown={(event) => {
                        dragged.current = false
                        const minutes = minutesFromPointer(event)
                        pending.current = {
                          booking,
                          originX: event.clientX,
                          grabMinutes:
                            minutes === null
                              ? 0
                              : Math.max(0, minutes - pct(booking.startsAt) * totalMinutes / 100),
                        }
                      }}
                    >
                      {booking.label}
                    </button>
                  )
                })}

              {nowVisible && (
                <span className="ds-timeline__now" style={{ left: `${nowLeft}%` }} />
              )}

              {drag?.dockId === dock.id && (
                <span
                  className={`ds-timeline__ghost${
                    collides(drag.booking, dock.id, drag.startsAt)
                      ? ' ds-timeline__ghost--conflict'
                      : ''
                  }`}
                  style={{
                    left: `${pct(drag.startsAt)}%`,
                    width: `${
                      ((drag.booking.endsAt.getTime() - drag.booking.startsAt.getTime()) /
                        60000 /
                        totalMinutes) *
                      100
                    }%`,
                  }}
                />
              )}

              {dock.status !== 'available' && (
                <span className="ds-timeline__blocked">{labels.blocked}</span>
              )}
            </div>
          </div>
        ))}
        {docks.length === 0 && <div className="ds-timeline__empty">{labels.empty}</div>}
      </div>
    </div>
  )
}
