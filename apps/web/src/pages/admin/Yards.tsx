import { Button, Input, Modal, Select, StatusPill } from '@gplansis/ds'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import { useErrorMessage } from '@/components/VisitStatus'
import type { LayoutTemplate, PlantSegment, PlantSummary } from '@/lib/api'
import { yardConfigApi } from '@/lib/api'
import { useUiStore } from '@/lib/uiStore'

const SEGMENTS: PlantSegment[] = [
  'food',
  'beverage',
  'general',
  'logistics',
  'chemical',
  'steel',
  'automotive',
  'agro',
]

interface PlantDraft {
  id: string | null
  code: string
  name: string
  segment: PlantSegment
  city: string
  timezone: string
  description: string
  active: boolean
  useTemplate: boolean
  template: LayoutTemplate
}

const NEW_PLANT: PlantDraft = {
  id: null,
  code: '',
  name: '',
  segment: 'food',
  city: '',
  timezone: 'America/Sao_Paulo',
  description: '',
  active: true,
  useTemplate: true,
  template: { zones: 3, slots_per_zone: 12, docks: 8, gates: 2, scales: 1, cold_chain_zone: true },
}

export function Yards() {
  const { t } = useTranslation(['admin', 'common'])
  const errorMessage = useErrorMessage()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const setPlantCode = useUiStore((state) => state.setPlantCode)
  const [draft, setDraft] = useState<PlantDraft | null>(null)

  const plants = useQuery({ queryKey: ['plants'], queryFn: yardConfigApi.plants })

  const save = useMutation({
    mutationFn: (value: PlantDraft) => {
      const body = {
        code: value.code,
        name: value.name,
        segment: value.segment,
        city: value.city || null,
        timezone: value.timezone,
        description: value.description || null,
        active: value.active,
      }
      return value.id
        ? yardConfigApi.updatePlant(value.id, body)
        : yardConfigApi.createPlant({
            ...body,
            template: value.useTemplate ? value.template : null,
          })
    },
    onSuccess: (plant, value) => {
      setDraft(null)
      void queryClient.invalidateQueries({ queryKey: ['plants'] })
      if (!value.id) navigate(`/admin/yards/${plant.id}`)
    },
  })

  const editPlant = (plant: PlantSummary) =>
    setDraft({
      ...NEW_PLANT,
      id: plant.id,
      code: plant.code,
      name: plant.name,
      segment: plant.segment,
      city: plant.city ?? '',
      timezone: plant.timezone,
      description: plant.description ?? '',
      active: plant.active,
      useTemplate: false,
    })

  const templateField = (key: keyof Omit<LayoutTemplate, 'cold_chain_zone'>, label: string) =>
    draft && (
      <Input
        label={label}
        type="number"
        min={0}
        value={draft.template[key]}
        onChange={(event) =>
          setDraft({
            ...draft,
            template: { ...draft.template, [key]: Number(event.target.value) },
          })
        }
      />
    )

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1 className="page__title">{t('admin:yards.title')}</h1>
          <span className="page__subtitle">{t('admin:yards.subtitle')}</span>
        </div>
        <Button variant="primary" onClick={() => setDraft({ ...NEW_PLANT })}>
          {t('admin:yards.new')}
        </Button>
      </div>

      {plants.data?.length === 0 && <p className="page__subtitle">{t('admin:yards.empty')}</p>}

      <div className="yard-cards">
        {(plants.data ?? []).map((plant) => (
          <article key={plant.id} className="panel yard-card">
            <div className="panel__title">
              <span className="row-actions">
                <span className="yard-card__code">{plant.code}</span>
                <StatusPill tone={plant.active ? 'running' : 'stopped'}>
                  {plant.active ? t('admin:yards.active') : t('admin:yards.inactive')}
                </StatusPill>
              </span>
              <span className="page__subtitle">{t(`admin:segment.${plant.segment}`)}</span>
            </div>
            <div className="panel__body panel__body--padded stack">
              <div className="yard-card__name">{plant.name}</div>
              {plant.city && <div className="page__subtitle">{plant.city}</div>}
              {plant.description && <p className="yard-card__desc">{plant.description}</p>}
              <div className="page__subtitle">
                {t('admin:yards.counts', {
                  zones: plant.zones,
                  slots: plant.slots,
                  docks: plant.docks,
                  gates: plant.gates,
                  scales: plant.scales,
                })}
              </div>
              <div className="row-actions">
                <Button variant="primary" onClick={() => navigate(`/admin/yards/${plant.id}`)}>
                  {t('admin:yards.open')}
                </Button>
                <Button onClick={() => editPlant(plant)}>{t('admin:yards.edit')}</Button>
                <Button
                  variant="ghost"
                  onClick={() => {
                    setPlantCode(plant.code)
                    navigate('/')
                  }}
                >
                  {t('admin:yards.viewOnTower')}
                </Button>
              </div>
            </div>
          </article>
        ))}
      </div>

      <Modal
        open={draft !== null}
        onClose={() => setDraft(null)}
        title={draft?.id ? t('admin:yards.edit') : t('admin:yards.new')}
        subtitle={draft?.id ? draft.code : undefined}
        closeLabel={t('common:action.close')}
        size="wide"
        actions={
          <>
            <Button onClick={() => setDraft(null)}>{t('common:action.cancel')}</Button>
            <Button
              variant="primary"
              disabled={!draft?.code || !draft?.name || save.isPending}
              onClick={() => draft && save.mutate(draft)}
            >
              {t('common:action.save')}
            </Button>
          </>
        }
      >
        {draft && (
          <div className="stack">
            <div className="form-grid form-grid--bare">
              <Input
                label={t('admin:yards.code')}
                operational
                disabled={Boolean(draft.id)}
                hint={draft.id ? undefined : t('admin:yards.codeHint')}
                value={draft.code}
                onChange={(event) =>
                  setDraft({ ...draft, code: event.target.value.toUpperCase().replace(/\s/g, '') })
                }
              />
              <Input
                label={t('admin:yards.name')}
                value={draft.name}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              />
              <Select
                label={t('admin:yards.segment')}
                value={draft.segment}
                options={SEGMENTS.map((segment) => ({
                  value: segment,
                  label: t(`admin:segment.${segment}`),
                }))}
                onChange={(event) =>
                  setDraft({ ...draft, segment: event.target.value as PlantSegment })
                }
              />
              <Input
                label={t('admin:yards.city')}
                value={draft.city}
                onChange={(event) => setDraft({ ...draft, city: event.target.value })}
              />
              <Input
                label={t('admin:yards.timezone')}
                value={draft.timezone}
                onChange={(event) => setDraft({ ...draft, timezone: event.target.value })}
              />
              <Input
                label={t('admin:yards.description')}
                value={draft.description}
                onChange={(event) => setDraft({ ...draft, description: event.target.value })}
              />
            </div>

            {draft.id && (
              <label className="check-list__item">
                <input
                  type="checkbox"
                  checked={draft.active}
                  onChange={(event) => setDraft({ ...draft, active: event.target.checked })}
                />
                <span>{t('admin:yards.active')}</span>
              </label>
            )}

            {!draft.id && (
              <fieldset className="check-list">
                <label className="check-list__item">
                  <input
                    type="checkbox"
                    checked={draft.useTemplate}
                    onChange={(event) => setDraft({ ...draft, useTemplate: event.target.checked })}
                  />
                  <span>{t('admin:yards.template')}</span>
                </label>
                <span className="page__subtitle">{t('admin:yards.templateHint')}</span>
                {draft.useTemplate && (
                  <>
                    <div className="form-grid form-grid--bare">
                      {templateField('zones', t('admin:yards.zones'))}
                      {templateField('slots_per_zone', t('admin:yards.slotsPerZone'))}
                      {templateField('docks', t('admin:yards.docks'))}
                      {templateField('gates', t('admin:yards.gates'))}
                      {templateField('scales', t('admin:yards.scales'))}
                    </div>
                    <label className="check-list__item">
                      <input
                        type="checkbox"
                        checked={draft.template.cold_chain_zone}
                        onChange={(event) =>
                          setDraft({
                            ...draft,
                            template: { ...draft.template, cold_chain_zone: event.target.checked },
                          })
                        }
                      />
                      <span>{t('admin:yards.coldChainZone')}</span>
                    </label>
                  </>
                )}
              </fieldset>
            )}

            {save.error && (
              <div className="alert" role="alert">
                {errorMessage(save.error)}
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}
