import type { ReactNode } from 'react'

export interface KpiTileProps {
  /** Rótulo já traduzido. */
  label: string
  /** Valor já formatado no locale da tela (Intl), não número cru. */
  value: string
  unit?: string
  /** `warn` e `alarm` são exceção: cor na tela significa anormalidade (ISA-101). */
  severity?: 'normal' | 'warn' | 'alarm'
  footer?: ReactNode
  /** Abre o detalhe do número. Número sem o que há atrás dele não sustenta decisão. */
  onClick?: () => void
}

export function KpiTile({
  label,
  value,
  unit,
  severity = 'normal',
  footer,
  onClick,
}: KpiTileProps) {
  const valueClass = [
    'ds-kpi__value',
    severity === 'alarm' ? 'ds-kpi__value--alarm' : '',
    severity === 'warn' ? 'ds-kpi__value--warn' : '',
  ]
    .filter(Boolean)
    .join(' ')

  const content = (
    <>
      <span className="ds-kpi__label">{label}</span>
      <span className={valueClass}>
        {value}
        {unit && <span className="ds-kpi__unit">{unit}</span>}
      </span>
      {footer && <span className="ds-kpi__foot">{footer}</span>}
    </>
  )

  if (!onClick) return <div className="ds-kpi">{content}</div>

  // Botão de verdade, não div com onClick: teclado e leitor de tela também abrem.
  return (
    <button type="button" className="ds-kpi ds-kpi--action" onClick={onClick}>
      {content}
    </button>
  )
}
