import type { ReactNode } from 'react'

import type { DataQuality } from './StatusPill'

export interface ScaleDisplayProps {
  /** Peso em kg — o dado trafega sempre em kg; a unidade de exibição é escolha da tela. */
  weightKg: number
  /** Valor já formatado no locale, com a unidade de exibição aplicada. */
  formattedWeight: string
  stable: boolean
  quality: DataQuality
  /** Rótulos já traduzidos. */
  labels: { stable: string; unstable: string; quality: string; scale: string }
  scaleCode: string
  /** Peso alvo ou de referência (tara cadastral, peso da NF-e), já formatado. */
  reference?: { label: string; value: string }
  children?: ReactNode
}

/**
 * Display de balança: número grande, legível do outro lado da cabine, com o estado da
 * leitura ao lado. Peso instável **parece** instável — quem captura peso oscilando
 * captura mentira, e o operador precisa ver isso sem ler texto pequeno.
 */
export function ScaleDisplay({
  weightKg,
  formattedWeight,
  stable,
  quality,
  labels,
  scaleCode,
  reference,
  children,
}: ScaleDisplayProps) {
  const unusable = quality !== 'fresh'
  return (
    <div
      className={[
        'ds-scale',
        stable && !unusable ? 'ds-scale--stable' : 'ds-scale--unstable',
        unusable ? 'ds-scale--nodata' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      data-quality={quality}
      aria-live="polite"
    >
      <div className="ds-scale__head">
        <span className="ds-scale__code">
          {labels.scale} {scaleCode}
        </span>
        <span className="ds-scale__state">
          <span className="ds-scale__dot" aria-hidden="true" />
          {unusable ? labels.quality : stable ? labels.stable : labels.unstable}
        </span>
      </div>

      <div className="ds-scale__value" title={String(weightKg)}>
        {unusable ? '— — —' : formattedWeight}
      </div>

      {reference && (
        <div className="ds-scale__reference">
          <span>{reference.label}</span>
          <strong>{reference.value}</strong>
        </div>
      )}

      {children && <div className="ds-scale__actions">{children}</div>}
    </div>
  )
}
