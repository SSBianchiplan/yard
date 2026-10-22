import type { ReactNode } from 'react'

/** Semântica de processo — a cor sai do token, nunca de literal na tela. */
export type StatusTone =
  | 'running'
  | 'idle'
  | 'waiting'
  | 'stopped'
  | 'moving'
  | 'critical'
  | 'high'
  | 'medium'

/**
 * Estado do dado, não do processo. Em sala de controle, número sem frescor é mentira:
 * um valor obsoleto precisa parecer obsoleto antes de alguém agir sobre ele.
 */
export type DataQuality = 'fresh' | 'stale' | 'invalid' | 'no_comm'

const TONE_TOKEN: Record<StatusTone, string> = {
  running: 'var(--color-status-running)',
  idle: 'var(--color-status-idle)',
  waiting: 'var(--color-status-waiting)',
  stopped: 'var(--color-status-stopped)',
  moving: 'var(--color-status-moving)',
  critical: 'var(--color-alarm-critical)',
  high: 'var(--color-alarm-high)',
  medium: 'var(--color-alarm-medium)',
}

export interface StatusPillProps {
  /** Texto já traduzido pela tela. */
  children: ReactNode
  tone?: StatusTone
  quality?: DataQuality
  solid?: boolean
  /** Rótulo curto de qualidade, já traduzido (ex.: "obsoleto", "stale"). */
  qualityLabel?: string
  title?: string
}

export function StatusPill({
  children,
  tone = 'idle',
  quality = 'fresh',
  solid = false,
  qualityLabel,
  title,
}: StatusPillProps) {
  const classes = [
    'ds-pill',
    solid ? 'ds-pill--solid' : '',
    quality !== 'fresh' ? `ds-pill--${quality}` : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <span
      className={classes}
      title={title}
      data-quality={quality}
      style={{ ['--pill-color' as string]: TONE_TOKEN[tone] }}
    >
      <span className="ds-pill__dot" aria-hidden="true" />
      {children}
      {quality !== 'fresh' && qualityLabel && (
        <span className="ds-pill__quality">{qualityLabel}</span>
      )}
    </span>
  )
}
