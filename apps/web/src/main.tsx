import '@gplansis/ds'
import './styles.css'
import './i18n'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import { registerServiceWorker } from './lib/pwa'

registerServiceWorker()

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
