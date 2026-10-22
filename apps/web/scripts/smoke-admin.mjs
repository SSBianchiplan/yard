#!/usr/bin/env node
/**
 * Smoke do fluxo administrativo, no navegador de verdade:
 * página inicial → CTA → login → torre → usuários (cria operador, recebe senha provisória) → novo pátio com
 * layout gerado → editor (gera vagas em grade, edita uma vaga) → sair.
 *
 *   YARD_URL=http://localhost:5173 YARD_EMAIL=... YARD_PASSWORD=... node scripts/smoke-admin.mjs [pasta-de-capturas]
 */
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

const base = process.env.YARD_URL ?? 'http://localhost:5173'
const email = process.env.YARD_EMAIL
const password = process.env.YARD_PASSWORD
const shots = process.argv[2]
if (!email || !password) {
  console.error('defina YARD_EMAIL e YARD_PASSWORD')
  process.exit(2)
}
if (shots) mkdirSync(shots, { recursive: true })

const stamp = Date.now().toString(36).toUpperCase().slice(-4)
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('pageerror', (error) => errors.push(error.message))
const snap = async (name) => shots && page.screenshot({ path: `${shots}/${name}.png` })
const step = (label) => console.log(`✓ ${label}`)

// visitante sem sessão vê a página inicial; o CTA leva ao login
await page.goto(base)
await page.locator('.lp-hero__title').waitFor()
await page.locator('.lp-hero__ctas a[href="/login"]').first().click()
await page.waitForURL('**/login')
await snap('01-login')
await page.getByLabel(/e-mail/i).fill(email)
await page.getByLabel(/senha|password/i).fill(password)
await page.getByRole('button', { name: /entrar|sign in/i }).click()
await page.waitForURL((url) => !url.pathname.startsWith('/login'))
await page.locator('.ds-kpi, .kpi-row').first().waitFor({ timeout: 15000 })
await snap('02-torre')
step('login e torre')

await page.getByRole('link', { name: /usuários|users/i }).click()
await page.getByRole('button', { name: /novo usuário|new user/i }).click()
const dialog = page.locator('dialog[open]')
await dialog.getByLabel(/e-mail/i).fill(`guarda.${stamp.toLowerCase()}@demo.local`)
await dialog.getByLabel(/^nome|^name/i).fill(`Guarda ${stamp}`)
await dialog.getByLabel(/guarita|gate/i).check()
await dialog.getByRole('button', { name: /salvar|save/i }).click()
await page.locator('.secret').waitFor()
await snap('03-senha-provisoria')
await page.locator('dialog[open]').getByRole('button', { name: /fechar|close/i }).first().click()
step('usuário criado com senha provisória')

await page.getByRole('link', { name: /pátios|yards/i }).click()
await page.getByRole('button', { name: /novo pátio|new yard/i }).click()
const plant = page.locator('dialog[open]')
await plant.getByLabel(/código|code/i).fill(`CD${stamp}`)
await plant.getByLabel(/^nome|^name/i).fill(`Centro de distribuição ${stamp}`)
await plant.getByLabel(/cidade|city/i).fill('Jundiaí - SP')
await plant.getByRole('button', { name: /salvar|save/i }).click()
await page.waitForURL('**/admin/yards/*')
await page.locator('.editor svg').first().waitFor()
await snap('04-editor')
step('pátio criado com layout gerado')

await page.getByRole('tab', { name: /zonas|zones/i }).click()
await page.locator('tbody tr').filter({ hasText: `CD${stamp}-ZA` }).first().click()
await page.locator('dialog[open]').getByRole('button', { name: /gerar vagas|generate slot/i }).click()
const grid = page.locator('dialog[open]').last()
await grid.getByLabel(/prefixo|prefix/i).fill(`CD${stamp}-EXTRA`)
await grid.getByLabel(/fileiras|rows/i).fill('1')
await grid.getByLabel(/colunas|columns/i).fill('4')
await grid.getByRole('button', { name: /gerar vagas|generate slot/i }).click()
await page.getByText(/4 vagas criadas|4 slots created/i).waitFor()
step('grade de vagas gerada')

await page.locator('tbody tr').filter({ hasText: `CD${stamp}-EXTRA-01` }).first().click()
const slot = page.locator('dialog[open]')
await slot.getByLabel(/situação|status/i).selectOption('maintenance')
await slot.getByRole('button', { name: /salvar|save/i }).click()
await page.getByText(/^salvo$|^saved$/i).waitFor()
await snap('05-editor-editado')
step('vaga editada')

await page.locator('.user-menu summary').click()
await page.getByRole('button', { name: /sair|sign out/i }).click()
await page.waitForURL('**/login')
step('logout')

await browser.close()
if (errors.length) {
  console.error('erros de página:', errors)
  process.exit(1)
}
console.log('smoke-admin ok')
