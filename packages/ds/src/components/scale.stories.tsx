import type { Meta, StoryObj } from '@storybook/react'
import { ScaleDisplay } from './ScaleDisplay'

const meta: Meta = { title: 'Blocos industriais/ScaleDisplay' }
export default meta

const labels = {
  stable: 'Estável',
  unstable: 'Instável',
  quality: 'Sem comunicação',
  scale: 'Balança',
}

export const Estados: StoryObj = {
  render: () => (
    <div style={{ display: 'grid', gap: 'var(--space-4)', maxWidth: 420 }}>
      <ScaleDisplay
        scaleCode="SCALE-01"
        weightKg={42180}
        formattedWeight="42.180 kg"
        stable
        quality="fresh"
        labels={labels}
        reference={{ label: 'Tara cadastral', value: '12.500 kg' }}
      />
      <ScaleDisplay
        scaleCode="SCALE-01"
        weightKg={41960}
        formattedWeight="41.960 kg"
        stable={false}
        quality="fresh"
        labels={labels}
      />
      <ScaleDisplay
        scaleCode="SCALE-02"
        weightKg={0}
        formattedWeight="0 kg"
        stable={false}
        quality="no_comm"
        labels={labels}
      />
    </div>
  ),
}
