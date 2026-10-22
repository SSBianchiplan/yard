#!/usr/bin/env node
/**
 * Verificação de responsividade: abre cada tela em cada dispositivo real do pátio e
 * reprova o que quebraria na mão do operador.
 *
 * O que é checado, e por quê:
 *   1. **scroll horizontal** — tela que rola de lado no celular perde botão de ação;
 *   2. **alvo de toque < 44px** em ponteiro grosso — dedo com luva não acerta;
 *   3. **texto cortado** (`scrollWidth > clientWidth`) — rótulo em en-US expande ~30%;
 *   4. **erro de console** — inclui chave de i18n faltando, que o gate estático não pega
 *      quando a chave é montada em tempo de execução (`t(\`yard:operation.${code}\`)`).
 *
 *   node scripts/responsive-check.mjs [baseUrl]
 */

import { chromium, devices } from 'playwright'

const BASE = process.argv[2] ?? 'http://127.0.0.1:5173'

const VIEWPORTS = [
  { name: 'celular do manobrista', width: 390, height: 844, touch: true },
  { name: 'tablet da guarita', width: 820, height: 1180, touch: true },
  { name: 'desktop', width: 1440, height: 900, touch: false },
  { name: 'painel de parede', width: 1920, height: 1080, touch: false },
]

const ROUTES = ['/', '/gate', '/kiosk', '/scheduling', '/weighing', '/moves', '/tower', '/visits']

const MIN_TOUCH_TARGET = 44

const failures = []
const notes = []

const browser = await chromium.launch()

for (const viewport of VIEWPORTS) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    hasTouch: viewport.touch,
    isMobile: viewport.touch,
    locale: 'pt-BR',
    ...(viewport.touch ? devices['iPhone 13'].userAgent : {}),
  })

  for (const route of ROUTES) {
    const page = await context.newPage()
    const consoleErrors = []
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 140))
    })
    page.on('pageerror', (error) => consoleErrors.push(`pageerror: ${error.message.slice(0, 140)}`))

    await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle' })
    // Espera o primeiro dado chegar: layout vazio esconde problema de overflow.
    await page.waitForTimeout(900)

    const report = await page.evaluate((minTarget) => {
      const doc = document.documentElement
      const overflow = doc.scrollWidth - doc.clientWidth

      // Elementos que passam da largura da janela (empurram a página de lado).
      const wide = [...document.querySelectorAll('body *')]
        .filter((el) => el.getBoundingClientRect().width > doc.clientWidth + 1)
        .slice(0, 3)
        .map((el) => `${el.tagName.toLowerCase()}.${(el.className || '').toString().slice(0, 40)}`)

      // Alvos de toque pequenos demais, só os visíveis.
      const small = [...document.querySelectorAll('button, a, select, input')]
        .filter((el) => {
          const rect = el.getBoundingClientRect()
          return rect.width > 0 && rect.height > 0 && rect.height < minTarget
        })
        .slice(0, 5)
        .map((el) => `${el.tagName.toLowerCase()}:${Math.round(el.getBoundingClientRect().height)}px`)

      // Texto cortado dentro do próprio elemento.
      const clipped = [...document.querySelectorAll('.ds-btn, .ds-kpi__label, .shell__nav a')]
        .filter((el) => el.scrollWidth > el.clientWidth + 2)
        .slice(0, 3)
        .map((el) => (el.textContent || '').trim().slice(0, 30))

      return {
        overflow,
        wide,
        small,
        clipped,
        density: doc.dataset.density,
        visibleColumns: document.querySelectorAll('.ds-table__head th').length,
      }
    }, MIN_TOUCH_TARGET)

    const where = `${viewport.name} ${viewport.width}px ${route}`

    if (report.overflow > 1) {
      failures.push(`${where}: rola ${report.overflow}px na horizontal (${report.wide.join(', ')})`)
    }
    if (viewport.touch && report.small.length) {
      failures.push(`${where}: alvo de toque menor que ${MIN_TOUCH_TARGET}px (${report.small.join(', ')})`)
    }
    if (report.clipped.length) {
      failures.push(`${where}: texto cortado (${report.clipped.join(' | ')})`)
    }
    if (consoleErrors.length) {
      failures.push(`${where}: erro de console — ${consoleErrors[0]}`)
    }
    notes.push(
      `${where}: densidade=${report.density} colunas=${report.visibleColumns}`,
    )
    await page.close()
  }
  await context.close()
}

await browser.close()

console.log(notes.join('\n'))
if (failures.length) {
  console.error(`\n✗ ${failures.length} problema(s) de responsividade:`)
  for (const failure of failures) console.error(`  - ${failure}`)
  process.exit(1)
}
console.log(`\n✓ ${VIEWPORTS.length} dispositivos × ${ROUTES.length} telas sem problema.`)
