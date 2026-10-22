import js from '@eslint/js'
import react from 'eslint-plugin-react'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: { react },
    languageOptions: { parserOptions: { ecmaFeatures: { jsx: true } } },
    rules: {
      // Nenhuma string literal em componente: tudo via t('...').
      // `ignoreProps`: className/variant são identificadores, não texto — o texto de
      // atributo humano (label, title, placeholder) é barrado pelo i18n-check.
      'react/jsx-no-literals': [
        'error',
        { noStrings: true, ignoreProps: true, allowedStrings: ['·', '—', '%', '(', ')', ':', '→', ' → '] },
      ],
    },
  },
)
