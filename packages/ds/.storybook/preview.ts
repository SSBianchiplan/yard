import type { Preview } from '@storybook/react'
import '../src/tokens/tokens.css'
import '../src/ds.css'

/** Tema e densidade são atributos no <html>: trocar token, nunca forkar componente. */
const preview: Preview = {
  globalTypes: {
    theme: {
      description: 'Tema',
      defaultValue: 'light',
      toolbar: { icon: 'paintbrush', items: ['light', 'dark', 'hmi'] },
    },
    density: {
      description: 'Densidade',
      defaultValue: 'default',
      toolbar: { icon: 'component', items: ['compact', 'default', 'touch'] },
    },
  },
  decorators: [
    (story, context) => {
      document.documentElement.dataset.theme = context.globals.theme as string
      document.documentElement.dataset.density = context.globals.density as string
      return story()
    },
  ],
  parameters: { layout: 'padded', controls: { expanded: true } },
}

export default preview
