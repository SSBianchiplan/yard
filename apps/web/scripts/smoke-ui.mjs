#!/usr/bin/env node
/**
 * Fumaça de interface: exercita o que o operador realmente faz e falha se algum
 * caminho quebrar. Não substitui teste de domínio (isso vive no pytest) — aqui é
 * "a tela responde ao clique e mostra o que prometeu".
 *
 *   node scripts/smoke-ui.mjs [baseUrl]
 */

import { chromium } from 'playwright'

const BASE = process.argv[2] ?? 'http://127.0.0.1:5173'
const results = []
const failures = []

const check = (name, ok, detail = '') => {
  results.push(`${ok ? '✓' : '✗'} ${name}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures.push(`${name}${detail ? `: ${detail}` : ''}`)
}

const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1600, height: 950 }, locale: 'pt-BR' })
const page = await context.newPage()

/** Caixa com altura limitada comprimia os itens e o texto sobrepunha. Isto não volta. */
async function overlapsIn(dialog) {
  return dialog.evaluate((el) => {
    var sel = '.ds-detail-row, .ds-field, .page__subtitle, .timeline-list li'
    var nodes = Array.prototype.slice.call(el.querySelectorAll(sel)).filter(function (n, _i, all) {
      return !all.some(function (o) { return o !== n && o.contains(n) })
    })
    var hits = 0
    for (var i = 0; i < nodes.length; i++) {
      for (var j = i + 1; j < nodes.length; j++) {
        var a = nodes[i].getBoundingClientRect(), b = nodes[j].getBoundingClientRect()
        if (a.bottom > b.top + 1 && b.bottom > a.top + 1 && a.right > b.left + 1 && b.right > a.left + 1) hits++
      }
    }
    return hits
  })
}

// ---------------------------------------------------------------- torre: modal
await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)

const occupied = page.locator('.ds-map__slot--occupied, .ds-map__slot--over').first()
await occupied.click()
const modal = page.locator('dialog.ds-modal[open]')
await modal.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {})
check('mapa: clicar em vaga ocupada abre o modal', await modal.isVisible())

if (await modal.isVisible()) {
  // Espera o dado da visita chegar: o título nasce com o código da posição.
  await modal.locator('.ds-detail-row').first().waitFor({ timeout: 5000 }).catch(() => {})
  const title = await modal.locator('.ds-modal__title').textContent()
  check('modal: traz placa e referência', /[A-Z]{3}\d/.test(title ?? ''), title ?? '')
  const rows = await modal.locator('.ds-detail-row').count()
  check('modal: mostra os dados da visita', rows >= 8, `${rows} campos`)
  const actions = await modal.locator('.ds-modal__actions .ds-btn').count()
  check('modal: oferece ações (manobra, balança, doca, saída)', actions >= 4, `${actions} ações`)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
  check('modal: fecha no Esc', !(await modal.isVisible()))
}

// Card da torre abre o detalhe do número: contagens, como a conta é feita e a lista.
await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)
const tile = page.locator('.ds-kpi--action').first()
check('torre: os cards são clicáveis', (await page.locator('.ds-kpi--action').count()) >= 8)
await tile.click()
const kpiModal = page.locator('dialog.ds-modal[open]')
await kpiModal.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {})
check('card: abre o modal do indicador', await kpiModal.isVisible())
if (await kpiModal.isVisible()) {
  const figures = await kpiModal.locator('.ds-detail-row').count()
  check('card: mostra as contagens por trás do número', figures >= 3, `${figures} contagens`)
  check('card: nenhum texto sobre texto', (await overlapsIn(kpiModal)) === 0)
  await page.keyboard.press('Escape')
}

// ---------------------------------------------------------------- totem
await page.goto(`${BASE}/kiosk`, { waitUntil: 'networkidle' })
await page.waitForTimeout(800)
const titleBox = await page.locator('.ds-flow__title').boundingBox()
check('totem: título cabe em até duas linhas', (titleBox?.height ?? 99) < 90,
  `${Math.round(titleBox?.height ?? 0)}px`)
const nextButton = page.locator('.ds-flow__actions .ds-btn--primary')
await nextButton.click() // passo 1 -> 2 (identificação é opcional para chegar ao checklist)
await page.waitForTimeout(600)
check(
  'totem: checklist sem visita escolhida não deixa avançar',
  await nextButton.isDisabled(),
)
const blockedReason = await page.locator('.ds-flow__blocked').textContent().catch(() => '')
check('totem: diz por que está bloqueado', Boolean(blockedReason), blockedReason ?? '')
await page.locator('.ds-flow__rail-button').first().click()
await page.waitForTimeout(300)
check(
  'totem: trilho volta para passo cumprido',
  (await page.locator('.ds-flow__counter').textContent())?.includes('1'),
)

// ---------------------------------------------------------------- agendamento
await page.goto(`${BASE}/scheduling`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)
await page.getByRole('button', { name: /nova janela/i }).click()
const apptModal = page.locator('dialog.ds-modal[open]')
await apptModal.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {})
check('agendamento: abre o formulário de nova janela', await apptModal.isVisible())
if (await apptModal.isVisible()) {
  const fields = await apptModal.locator('.ds-field').count()
  check('agendamento: formulário completo', fields >= 6, `${fields} campos`)
  await page.keyboard.press('Escape')
}

// O gráfico chegou a hachurar quase todas as docas como "bloqueada": ocupada agora não é
// bloqueada no dia, e doca ocupada às 9h continua agendável às 15h.
const lanes = await page.locator('.ds-timeline__lane').count()
const blockedLanes = await page.locator('.ds-timeline__lane--blocked').count()
check(
  'gráfico de janelas: hachura só a doca realmente bloqueada',
  lanes > 0 && blockedLanes < lanes / 2,
  `${blockedLanes} de ${lanes} faixas`,
)
// Janela que começa antes do gráfico é aparada na borda, não vaza para a doca de cima.
const overflowing = await page.locator('.ds-timeline__booking').evaluateAll((nodes) =>
  nodes.filter((node) => parseFloat(node.style.left) < 0).length,
)
check('gráfico de janelas: nenhuma faixa vaza para fora da doca', overflowing === 0)
// Clicar na faixa abre o modal da janela, com os dados e as ações dela.
const firstBooking = page.locator('.ds-timeline__booking').first()
if (await firstBooking.count()) {
  // Clique abria o detalhe E reprogramava a janela na coordenada do cursor: ela andava
  // para a frente a cada clique. A faixa tem de ficar exatamente onde estava.
  const before = await firstBooking.evaluate((el) => el.style.left)
  await firstBooking.click()
  await page.waitForTimeout(900)
  const after = await firstBooking.evaluate((el) => el.style.left)
  check('gráfico de janelas: clicar não move a janela', before === after, `${before} → ${after}`)
  const apptDetail = page.locator('dialog.ds-modal[open]')
  await apptDetail.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {})
  check('gráfico de janelas: clicar na faixa abre o modal', await apptDetail.isVisible())
  if (await apptDetail.isVisible()) {
    const rows = await apptDetail.locator('.ds-detail-row').count()
    check('modal da janela: traz os dados do agendamento', rows >= 6, `${rows} campos`)
    const acts = await apptDetail.locator('.ds-modal__actions .ds-btn').count()
    check('modal da janela: oferece ações (confirmar, cancelar)', acts >= 1, `${acts} ações`)
    check('modal da janela: nenhum texto sobre texto', (await overlapsIn(apptDetail)) === 0)
    await page.keyboard.press('Escape')
  }
}

const nowMarker = await page.locator('.ds-timeline__now-label').count()
check('gráfico de janelas: marca o agora', nowMarker === 1)

// ---------------------------------------------------------------- balança
await page.goto(`${BASE}/weighing`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1500)
const scaleValue = await page.locator('.ds-scale__value').textContent()
check('balança: display mostra leitura ao vivo', /\d/.test(scaleValue ?? ''), scaleValue ?? '')

// ---------------------------------------------------------------- manobra
await page.goto(`${BASE}/moves`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1000)
const spotterSelect = page.locator('.ds-table__toolbar select')
check('manobra: escolhe o manobrista do tablet', (await spotterSelect.count()) === 1)

await browser.close()

console.log(results.join('\n'))
if (failures.length) {
  console.error(`\n✗ ${failures.length} verificação(ões) falhou(aram)`)
  process.exit(1)
}
console.log(`\n✓ ${results.length} verificações de interface passaram.`)
