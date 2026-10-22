import type { InputHTMLAttributes } from 'react'
import { useId } from 'react'

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  hint?: string
  /** Código de erro já traduzido pela tela — o DS nunca traduz nada. */
  error?: string
  /** Campo de dado operacional (placa, lacre, documento): monoespaçado e caixa alta. */
  operational?: boolean
}

export function Input({
  label,
  hint,
  error,
  operational = false,
  className = '',
  id,
  ...rest
}: InputProps) {
  const generated = useId()
  const inputId = id ?? generated

  return (
    <div className={`ds-field ${error ? 'ds-field--invalid' : ''} ${className}`}>
      <label className="ds-field__label" htmlFor={inputId}>
        {label}
      </label>
      <input
        id={inputId}
        className={`ds-field__control ${operational ? 'ds-field__control--mono' : ''}`}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || hint ? `${inputId}-desc` : undefined}
        style={operational ? { textTransform: 'uppercase' } : undefined}
        {...rest}
      />
      {(error || hint) && (
        <span id={`${inputId}-desc`} className={error ? 'ds-field__error' : 'ds-field__hint'}>
          {error ?? hint}
        </span>
      )}
    </div>
  )
}
