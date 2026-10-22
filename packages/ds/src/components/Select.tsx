import type { SelectHTMLAttributes } from 'react'
import { useId } from 'react'

export interface SelectOption {
  value: string
  /** Rótulo já traduzido pela tela. O DS recebe texto pronto, nunca chama i18n. */
  label: string
  disabled?: boolean
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string
  options: SelectOption[]
  hint?: string
  error?: string
  placeholder?: string
}

export function Select({
  label,
  options,
  hint,
  error,
  placeholder,
  className = '',
  id,
  ...rest
}: SelectProps) {
  const generated = useId()
  const selectId = id ?? generated

  return (
    <div className={`ds-field ${error ? 'ds-field--invalid' : ''} ${className}`}>
      <label className="ds-field__label" htmlFor={selectId}>
        {label}
      </label>
      <select
        id={selectId}
        className="ds-field__control"
        aria-invalid={error ? true : undefined}
        {...rest}
      >
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((option) => (
          <option key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
      {(error || hint) && (
        <span className={error ? 'ds-field__error' : 'ds-field__hint'}>{error ?? hint}</span>
      )}
    </div>
  )
}
