import type { ReactNode } from 'react'
import { useEffect, useRef } from 'react'

export interface ModalProps {
  open: boolean
  onClose: () => void
  /** Título já traduzido. */
  title: string
  subtitle?: string
  children: ReactNode
  /** Ações do rodapé — o que dá para fazer com o que está na tela. */
  actions?: ReactNode
  /** Rótulo do botão de fechar, já traduzido. */
  closeLabel: string
  size?: 'default' | 'wide'
}

/**
 * Modal do DS, sobre `<dialog>` nativo.
 *
 * Em pátio, o operador abre isto com luva e com o caminhão esperando: fecha no Esc,
 * fecha no clique fora, e o conteúdo rola sozinho sem empurrar a página atrás. No
 * celular vira folha de baixo para cima, porque caixa centralizada em tela pequena
 * desperdiça metade do espaço.
 */
export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  actions,
  closeLabel,
  size = 'default',
}: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    const onCancel = (event: Event) => {
      event.preventDefault()
      onClose()
    }
    dialog.addEventListener('cancel', onCancel)
    return () => dialog.removeEventListener('cancel', onCancel)
  }, [onClose])

  return (
    <dialog
      ref={ref}
      className={`ds-modal${size === 'wide' ? ' ds-modal--wide' : ''}`}
      onClick={(event) => {
        // Clique no backdrop fecha; clique no conteúdo, não.
        if (event.target === ref.current) onClose()
      }}
    >
      <div className="ds-modal__panel">
        <header className="ds-modal__head">
          <div>
            <h2 className="ds-modal__title">{title}</h2>
            {subtitle && <p className="ds-modal__subtitle">{subtitle}</p>}
          </div>
          <button type="button" className="ds-btn ds-btn--ghost" onClick={onClose}>
            {closeLabel}
          </button>
        </header>

        <div className="ds-modal__body">{children}</div>

        {actions && <footer className="ds-modal__actions">{actions}</footer>}
      </div>
    </dialog>
  )
}

export interface DetailRowProps {
  label: string
  children: ReactNode
}

/** Linha de dado do modal: rótulo à esquerda, valor alinhado à direita. */
export function DetailRow({ label, children }: DetailRowProps) {
  return (
    <div className="ds-detail-row">
      <span className="ds-detail-row__label">{label}</span>
      <span className="ds-detail-row__value">{children}</span>
    </div>
  )
}
