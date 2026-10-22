import type { Meta, StoryObj } from '@storybook/react'
import { AlarmBanner, AlarmList } from './AlarmList'

const meta: Meta = { title: 'Blocos industriais/Alarmes' }
export default meta

export const Lista: StoryObj = {
  render: () => (
    <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
      <AlarmBanner priority="critical" action={<button className="ds-btn">Tratar</button>}>
        Risco de demurrage em 3 veículos
      </AlarmBanner>
      <AlarmList
        labels={{
          acknowledge: 'Reconhecer',
          shelve: 'Suprimir',
          empty: 'Sem alarmes',
          acknowledgedBy: 'reconhecido por',
        }}
        alarms={[
          {
            id: '1',
            priority: 'critical',
            label: 'Fila de portaria acima do limite',
            detail: '12 veículos · limite 8',
            at: '14:32:10',
          },
          {
            id: '2',
            priority: 'high',
            label: 'Agendamentos atrasados na doca 04',
            at: '14:28:02',
            acknowledged: true,
            acknowledgedBy: 'torre.01',
          },
          {
            id: '3',
            priority: 'medium',
            label: 'Dwell acima da meta',
            detail: '6 veículos',
            at: '14:10:44',
            shelved: true,
          },
        ]}
      />
    </div>
  ),
}
