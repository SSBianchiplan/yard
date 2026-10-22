import type { ButtonHTMLAttributes, ReactNode } from 'react'

export type ButtonVariant = 'default' | 'primary' | 'danger' | 'ghost'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  block?: boolean
  icon?: ReactNode
}

/**
 * Botão do DS. Sem largura fixa: o rótulo em en-US expande ~30% e não pode quebrar o layout.
 * Altura e alvo de toque vêm da densidade ativa (compact 32px / touch 44px).
 */
export function Button({
  variant = 'default',
  block = false,
  icon,
  children,
  className = '',
  type = 'button',
  ...rest
}: ButtonProps) {
  const classes = [
    'ds-btn',
    variant !== 'default' ? `ds-btn--${variant}` : '',
    block ? 'ds-btn--block' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <button type={type} className={classes} {...rest}>
      {icon}
      {children}
    </button>
  )
}
