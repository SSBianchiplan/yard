import type { Meta, StoryObj } from '@storybook/react'
import { DockTimeline } from './DockTimeline'
import type { TimelineBooking, TimelineDock } from './DockTimeline'

const meta: Meta = { title: 'Blocos industriais/DockTimeline' }
export default meta

const from = new Date()
from.setHours(6, 0, 0, 0)
const to = new Date(from)
to.setHours(18, 0, 0, 0)

const docks: TimelineDock[] = Array.from({ length: 12 }, (_, i) => ({
  id: `d${i}`,
  code: `DOCK-${String(i + 1).padStart(2, '0')}`,
  status: i === 4 ? 'blocked' : 'available',
}))

const states = ['confirmed', 'requested', 'checked_in', 'in_progress', 'cancelled']
const bookings: TimelineBooking[] = docks.flatMap((dock, d) =>
  Array.from({ length: 3 }, (_, k) => {
    const startsAt = new Date(from.getTime() + (d * 37 + k * 210) * 60000)
    return {
      id: `${dock.id}-${k}`,
      dockId: dock.id,
      label: `ABC${d}D${k}0`,
      startsAt,
      endsAt: new Date(startsAt.getTime() + 90 * 60000),
      state: states[(d + k) % states.length] as string,
      conflicting: d === 2 && k === 1,
    }
  }),
)

export const Gantt: StoryObj = {
  render: () => (
    <div style={{ height: 420, border: '1px solid var(--color-border)' }}>
      <DockTimeline
        docks={docks}
        bookings={bookings}
        from={from}
        to={to}
        labels={{ hour: 'Doca', empty: 'Sem docas', blocked: 'Bloqueada' }}
      />
    </div>
  ),
}
