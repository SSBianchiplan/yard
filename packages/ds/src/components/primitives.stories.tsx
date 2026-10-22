import type { Meta, StoryObj } from '@storybook/react'
import { Button } from './Button'
import { Input } from './Input'
import { Select } from './Select'
import { StatusPill } from './StatusPill'

const meta: Meta = { title: 'Primitivos' }
export default meta

export const Botoes: StoryObj = {
  render: () => (
    <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
      <Button>Registrar</Button>
      <Button variant="primary">Liberar entrada</Button>
      <Button variant="danger">Recusar</Button>
      <Button variant="ghost">Cancelar</Button>
      <Button disabled>Sem permissivo</Button>
      {/* en-US expande ~30%: o botão cresce, o layout não quebra */}
      <Button variant="primary">Release vehicle to yard</Button>
    </div>
  ),
}

export const Campos: StoryObj = {
  render: () => (
    <div style={{ display: 'grid', gap: 'var(--space-4)', maxWidth: 360 }}>
      <Input label="Placa" operational placeholder="ABC1D23" defaultValue="RQP4X21" />
      <Input label="Documento do motorista" hint="CPF sem pontuação" defaultValue="10000013700" />
      <Input label="Lacre" error="Lacre obrigatório para produto perigoso" />
      <Select
        label="Tipo de operação"
        placeholder="Selecione"
        options={[
          { value: 'RECEBIMENTO_GRANEL', label: 'Recebimento a granel' },
          { value: 'EXPEDICAO_PALETIZADA', label: 'Expedição paletizada' },
          { value: 'DEVOLUCAO', label: 'Devolução' },
        ]}
      />
    </div>
  ),
}

export const EstadoDoDado: StoryObj = {
  name: 'StatusPill · estado de processo e do dado',
  render: () => (
    <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
      <StatusPill tone="running">Em pátio</StatusPill>
      <StatusPill tone="waiting">Na guarita</StatusPill>
      <StatusPill tone="moving">Em doca</StatusPill>
      <StatusPill tone="stopped">Saiu</StatusPill>
      <StatusPill tone="critical" solid>
        Bloqueado
      </StatusPill>
      <StatusPill tone="running" quality="stale" qualityLabel="obsoleto">
        Balança 01
      </StatusPill>
      <StatusPill tone="idle" quality="no_comm" qualityLabel="sem comunicação">
        Cancela 03
      </StatusPill>
      <StatusPill tone="critical" quality="invalid" qualityLabel="inválido">
        Sensor moega
      </StatusPill>
    </div>
  ),
}
