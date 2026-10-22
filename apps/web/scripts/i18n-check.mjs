#!/usr/bin/env node
/**
 * Gate de i18n: o build quebra se
 *   1. faltar chave em qualquer locale (comparação simétrica entre todos);
 *   2. existir string literal humana em JSX.
 *
 * Roda antes de `tsc -b && vite build` (ver package.json).
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const localesDir = join(root, 'src', 'locales')
const srcDir = join(root, 'src')

let failures = 0
const fail = (message) => {
  failures += 1
  console.error(`✗ ${message}`)
}

/* ---------------- 1. chaves ---------------- */
const flatten = (obj, prefix = '') =>
  Object.entries(obj).flatMap(([key, value]) =>
    value && typeof value === 'object' && !Array.isArray(value)
      ? flatten(value, `${prefix}${key}.`)
      : [`${prefix}${key}`],
  )

const locales = readdirSync(localesDir).filter((entry) =>
  statSync(join(localesDir, entry)).isDirectory(),
)
const namespaces = new Set(
  locales.flatMap((locale) =>
    readdirSync(join(localesDir, locale)).filter((file) => file.endsWith('.json')),
  ),
)

const keysByLocale = {}
for (const locale of locales) {
  keysByLocale[locale] = {}
  for (const namespace of namespaces) {
    const path = join(localesDir, locale, namespace)
    try {
      keysByLocale[locale][namespace] = new Set(flatten(JSON.parse(readFileSync(path, 'utf8'))))
    } catch {
      fail(`namespace ausente: ${locale}/${namespace}`)
      keysByLocale[locale][namespace] = new Set()
    }
  }
}

for (const namespace of namespaces) {
  const union = new Set(locales.flatMap((locale) => [...keysByLocale[locale][namespace]]))
  for (const locale of locales) {
    for (const key of union) {
      if (!keysByLocale[locale][namespace].has(key)) {
        fail(`chave ausente em ${locale}/${namespace}: ${key}`)
      }
    }
  }
}

/* ---------------- 2. literais em JSX ---------------- */
const IGNORED = /^[\s\d\p{P}\p{S}·—→↑↓%]*$/u
const walk = (dir) =>
  readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) return walk(path)
    return path.endsWith('.tsx') ? [path] : []
  })

for (const file of walk(srcDir)) {
  const source = readFileSync(file, 'utf8')
  source.split('\n').forEach((line, index) => {
    if (line.includes('i18n-allow-literal')) return
    // texto entre tags: <span>Veículos em pátio</span>
    for (const match of line.matchAll(/>([^<>{}\n]+)</g)) {
      const text = match[1].trim()
      if (text && !IGNORED.test(text)) {
        fail(
          `string literal em JSX — use t(): ${relative(root, file)}:${index + 1} → "${text}"`,
        )
      }
    }
    // atributos humanos: label="Placa", placeholder="…", title="…"
    for (const match of line.matchAll(
      /\b(label|placeholder|title|emptyLabel|aria-label)="([^"]+)"/g,
    )) {
      if (!IGNORED.test(match[2])) {
        fail(
          `atributo literal — use t(): ${relative(root, file)}:${index + 1} → ${match[1]}="${match[2]}"`,
        )
      }
    }
  })
}

if (failures > 0) {
  console.error(`\ni18n check falhou com ${failures} problema(s).`)
  process.exit(1)
}
console.log(`i18n check ok — ${locales.length} locales, ${namespaces.size} namespaces.`)
