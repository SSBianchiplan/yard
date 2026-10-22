import { useEffect, useState } from 'react'

/**
 * PWA: service worker e convite de instalação.
 *
 * O SW só entra em produção — em dev ele cachearia o bundle do Vite e a tela deixaria
 * de refletir o código salvo, que é a pior surpresa possível numa sessão de trabalho.
 */
export function registerServiceWorker() {
  if (!import.meta.env.PROD || !('serviceWorker' in navigator)) return
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/sw.js').catch(() => {
      /* sem SW o app funciona igual, só não instala offline */
    })
  })
}

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

let deferred: BeforeInstallPromptEvent | null = null
const listeners = new Set<() => void>()

if (typeof window !== 'undefined') {
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault()
    deferred = event as BeforeInstallPromptEvent
    listeners.forEach((notify) => notify())
  })
  window.addEventListener('appinstalled', () => {
    deferred = null
    listeners.forEach((notify) => notify())
  })
}

/** Botão "Instalar app" só aparece quando o navegador de fato oferece a instalação. */
export function useInstallPrompt() {
  const [available, setAvailable] = useState(Boolean(deferred))
  useEffect(() => {
    const notify = () => setAvailable(Boolean(deferred))
    listeners.add(notify)
    return () => {
      listeners.delete(notify)
    }
  }, [])
  return {
    available,
    prompt: async () => {
      if (!deferred) return
      await deferred.prompt()
      await deferred.userChoice
      deferred = null
      setAvailable(false)
    },
  }
}
