#!/usr/bin/env node
/** Captura as telas para conferência visual. `node scripts/screenshot.mjs [saída]` */
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

const BASE = process.env.YARD_URL ?? 'http://127.0.0.1:5173'
const OUT = process.argv[2] ?? 'screenshots'
mkdirSync(OUT, { recursive: true })

const SHOTS = [
  { route: '/', name: 'torre', width: 1600, height: 900 },
  { route: '/kiosk', name: 'totem', width: 1400, height: 900 },
  { route: '/scheduling', name: 'agendamento', width: 1600, height: 900 },
  { route: '/weighing', name: 'balanca', width: 1400, height: 900 },
  { route: '/moves', name: 'manobra', width: 1400, height: 900 },
  { route: '/', name: 'torre-celular', width: 390, height: 844 },
  { route: '/kiosk', name: 'totem-tablet', width: 820, height: 1180 },
]

const browser = await chromium.launch()
for (const shot of SHOTS) {
  const context = await browser.newContext({
    viewport: { width: shot.width, height: shot.height },
    locale: 'pt-BR',
    hasTouch: shot.width < 1024,
  })
  const page = await context.newPage()
  await page.goto(`${BASE}${shot.route}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1400)
  await page.screenshot({ path: `${OUT}/${shot.name}.png` })
  await context.close()
  console.log(`${OUT}/${shot.name}.png`)
}
await browser.close()
