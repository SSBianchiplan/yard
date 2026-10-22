import i18n from 'i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import { initReactI18next } from 'react-i18next'

import adminEn from '../locales/en-US/admin.json'
import commonEn from '../locales/en-US/common.json'
import errorsEn from '../locales/en-US/errors.json'
import gateEn from '../locales/en-US/gate.json'
import landingEn from '../locales/en-US/landing.json'
import movesEn from '../locales/en-US/moves.json'
import schedulingEn from '../locales/en-US/scheduling.json'
import towerEn from '../locales/en-US/tower.json'
import weighingEn from '../locales/en-US/weighing.json'
import yardEn from '../locales/en-US/yard.json'
import adminPt from '../locales/pt-BR/admin.json'
import commonPt from '../locales/pt-BR/common.json'
import errorsPt from '../locales/pt-BR/errors.json'
import gatePt from '../locales/pt-BR/gate.json'
import landingPt from '../locales/pt-BR/landing.json'
import movesPt from '../locales/pt-BR/moves.json'
import schedulingPt from '../locales/pt-BR/scheduling.json'
import towerPt from '../locales/pt-BR/tower.json'
import weighingPt from '../locales/pt-BR/weighing.json'
import yardPt from '../locales/pt-BR/yard.json'

/**
 * pt-BR é o default; en-US é par de primeira classe; es-MX entra sem refatoração —
 * basta adicionar a pasta de locale e registrar aqui.
 *
 * Namespace por módulo. Chave em inglês, hierárquica: <módulo>.<contexto>.<elemento>.
 */
export const SUPPORTED_LOCALES = ['pt-BR', 'en-US'] as const
export type Locale = (typeof SUPPORTED_LOCALES)[number]

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      'pt-BR': {
        common: commonPt,
        admin: adminPt,
        landing: landingPt,
        yard: yardPt,
        gate: gatePt,
        moves: movesPt,
        scheduling: schedulingPt,
        tower: towerPt,
        weighing: weighingPt,
        errors: errorsPt,
      },
      'en-US': {
        common: commonEn,
        admin: adminEn,
        landing: landingEn,
        yard: yardEn,
        gate: gateEn,
        moves: movesEn,
        scheduling: schedulingEn,
        tower: towerEn,
        weighing: weighingEn,
        errors: errorsEn,
      },
    },
    fallbackLng: 'pt-BR',
    supportedLngs: SUPPORTED_LOCALES,
    ns: ['common', 'admin', 'landing', 'yard', 'gate', 'scheduling', 'weighing', 'moves', 'tower', 'errors'],
    defaultNS: 'common',
    interpolation: { escapeValue: false },
    detection: { order: ['localStorage', 'navigator'], caches: ['localStorage'] },
    // Chave faltando estoura no dev: build de produção é barrado pelo i18n:check.
    saveMissing: import.meta.env.DEV,
    missingKeyHandler: (_lngs, ns, key) => {
      if (import.meta.env.DEV) console.error(`[i18n] chave ausente: ${ns}:${key}`)
    },
  })

export default i18n
