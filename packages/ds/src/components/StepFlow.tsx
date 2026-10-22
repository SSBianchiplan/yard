import type { ReactNode } from 'react'

export interface FlowStep {
  id: string
  /** Título já traduzido. */
  title: string
  hint?: string
  /** Conteúdo do passo — um passo por tela, nunca dois. */
  content: ReactNode
  /** Impede avançar (item reprovado, permissivo negado, peso instável). */
  blocked?: boolean
  blockedReason?: string
}

export interface StepFlowProps {
  steps: FlowStep[]
  currentIndex: number
  onChange: (index: number) => void
  onFinish?: () => void
  /** Rótulos já traduzidos. */
  labels: { back: string; next: string; finish: string; step: string; of: string }
}

/**
 * Fluxo guiado de operador (padrão Tulip): um passo por tela, alvo de toque grande,
 * usável com luva e sem treinamento. Quem opera guarita não lê manual — segue o passo.
 *
 * Passo bloqueado não deixa avançar e diz por quê, ali mesmo. Esconder o motivo e só
 * desabilitar o botão é o jeito rápido de fazer o operador chamar o supervisor.
 */
export function StepFlow({ steps, currentIndex, onChange, onFinish, labels }: StepFlowProps) {
  const step = steps[currentIndex]
  if (!step) return null
  const isLast = currentIndex === steps.length - 1

  return (
    <div className="ds-flow">
      <ol className="ds-flow__rail">
        {steps.map((item, index) => {
          // Voltar a um passo já cumprido é útil; pular para a frente, não —
          // o trilho parecia clicável e não era, o que é pior que não parecer.
          const reachable = index < currentIndex
          return (
            <li
              key={item.id}
              className={[
                'ds-flow__rail-item',
                index === currentIndex ? 'ds-flow__rail-item--current' : '',
                reachable ? 'ds-flow__rail-item--done' : '',
                reachable ? 'ds-flow__rail-item--clickable' : '',
              ]
                .filter(Boolean)
                .join(' ')}
            >
              <span className="ds-flow__rail-dot" aria-hidden="true" />
              {reachable ? (
                <button
                  type="button"
                  className="ds-flow__rail-button"
                  onClick={() => onChange(index)}
                >
                  {item.title}
                </button>
              ) : (
                <span className="ds-flow__rail-label">{item.title}</span>
              )}
            </li>
          )
        })}
      </ol>

      <div className="ds-flow__panel">
        <header className="ds-flow__header">
          <span className="ds-flow__counter">
            {labels.step} {currentIndex + 1} {labels.of} {steps.length}
          </span>
          <h2 className="ds-flow__title">{step.title}</h2>
          {step.hint && <p className="ds-flow__hint">{step.hint}</p>}
        </header>

        <div className="ds-flow__content">{step.content}</div>

        {step.blocked && step.blockedReason && (
          <div className="ds-flow__blocked" role="alert">
            {step.blockedReason}
          </div>
        )}

        <footer className="ds-flow__actions">
          <button
            type="button"
            className="ds-btn ds-flow__button"
            disabled={currentIndex === 0}
            onClick={() => onChange(currentIndex - 1)}
          >
            {labels.back}
          </button>
          <button
            type="button"
            className="ds-btn ds-btn--primary ds-flow__button"
            disabled={step.blocked}
            onClick={() => (isLast ? onFinish?.() : onChange(currentIndex + 1))}
          >
            {isLast ? labels.finish : labels.next}
          </button>
        </footer>
      </div>
    </div>
  )
}
