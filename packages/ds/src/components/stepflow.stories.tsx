import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'
import { StepFlow } from './StepFlow'
import { Input } from './Input'

const meta: Meta = { title: 'Blocos industriais/StepFlow' }
export default meta

export const Guarita: StoryObj = {
  render: function Render() {
    const [index, setIndex] = useState(0)
    return (
      <div style={{ height: 460, border: '1px solid var(--color-border)' }}>
        <StepFlow
          currentIndex={index}
          onChange={setIndex}
          labels={{ back: 'Voltar', next: 'Avançar', finish: 'Liberar', step: 'Passo', of: 'de' }}
          steps={[
            {
              id: 'plate',
              title: 'Identificar veículo',
              hint: 'Leitura de placa, QR do agendamento ou digitação',
              content: <Input label="Placa" operational defaultValue="RQP4X21" />,
            },
            {
              id: 'checklist',
              title: 'Checklist de entrada',
              content: <span>EPI, extintor, amarração, lacre</span>,
              blocked: true,
              blockedReason: 'Item reprovado: EPI incompleto',
            },
            {
              id: 'release',
              title: 'Liberar cancela',
              hint: 'O botão só habilita com permissivo do CLP',
              content: <span>Destino: vaga A-12</span>,
            },
          ]}
        />
      </div>
    )
  },
}
