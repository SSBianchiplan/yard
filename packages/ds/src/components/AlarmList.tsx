import type { ReactNode } from 'react'

export type AlarmPriority = 'critical' | 'high' | 'medium' | 'low'

export interface AlarmItem {
  id: string
  priority: AlarmPriority
  /** Texto já traduzido. */
  label: string
  detail?: string
  /** Hora já formatada no locale e no fuso da planta. */
  at: string
  acknowledged?: boolean
  acknowledgedBy?: string | null
  shelved?: boolean
}

export interface AlarmListProps {
  alarms: AlarmItem[]
  onAcknowledge?: (alarm: AlarmItem) => void
  onShelve?: (alarm: AlarmItem) => void
  /** Rótulos já traduzidos. */
  labels: { acknowledge: string; shelve: string; empty: string; acknowledgedBy: string }
}

/**
 * Lista de alarmes no padrão ISA-18.2: prioridade explícita, reconhecimento com dono e
 * hora, e supressão (shelving) visível em vez de escondida.
 *
 * Alarme reconhecido perde a cor mas não some: sumir é como o operador perde o fio do
 * que ainda está aberto.
 */
export function AlarmList({ alarms, onAcknowledge, onShelve, labels }: AlarmListProps) {
  if (alarms.length === 0) {
    return <div className="ds-alarms__empty">{labels.empty}</div>
  }

  return (
    <ul className="ds-alarms">
      {alarms.map((alarm) => (
        <li
          key={alarm.id}
          className={[
            'ds-alarms__item',
            `ds-alarms__item--${alarm.priority}`,
            alarm.acknowledged ? 'ds-alarms__item--ack' : '',
            alarm.shelved ? 'ds-alarms__item--shelved' : '',
          ]
            .filter(Boolean)
            .join(' ')}
        >
          <span className="ds-alarms__bar" aria-hidden="true" />
          <div className="ds-alarms__body">
            <span className="ds-alarms__label">{alarm.label}</span>
            {alarm.detail && <span className="ds-alarms__detail">{alarm.detail}</span>}
            {alarm.acknowledged && alarm.acknowledgedBy && (
              <span className="ds-alarms__ack">
                {labels.acknowledgedBy} {alarm.acknowledgedBy}
              </span>
            )}
          </div>
          <span className="ds-alarms__time">{alarm.at}</span>
          <span className="ds-alarms__actions">
            {!alarm.acknowledged && onAcknowledge && (
              <button
                type="button"
                className="ds-btn"
                onClick={() => onAcknowledge(alarm)}
              >
                {labels.acknowledge}
              </button>
            )}
            {onShelve && !alarm.shelved && (
              <button type="button" className="ds-btn ds-btn--ghost" onClick={() => onShelve(alarm)}>
                {labels.shelve}
              </button>
            )}
          </span>
        </li>
      ))}
    </ul>
  )
}

export interface AlarmBannerProps {
  priority: AlarmPriority
  children: ReactNode
  action?: ReactNode
}

/** Banner de anormalidade: ocupa espaço, não desaparece sozinho como um toast. */
export function AlarmBanner({ priority, children, action }: AlarmBannerProps) {
  return (
    <div className={`ds-alarm-banner ds-alarm-banner--${priority}`} role="alert">
      <span>{children}</span>
      {action}
    </div>
  )
}
