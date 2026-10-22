/** Cliente da API. O backend devolve código + parâmetros; a tradução acontece aqui.
 *
 * Toda escrita vai assinada pela identidade da sessão (`lib/auth`) — nenhuma tela
 * inventa mais um `actor` no corpo da requisição.
 */

import type { AuthMode, SessionUser } from './auth'
import { authHeaders, currentActor, useAuth } from './auth'

export class ApiError extends Error {
  constructor(
    readonly code: string,
    readonly params: Record<string, unknown>,
    readonly status: number,
  ) {
    super(code)
  }
}

const BASE = '/api/v1'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...init?.headers },
  })
  if (!response.ok) {
    let code = 'ERR_UNKNOWN'
    let params: Record<string, unknown> = {}
    try {
      const body = await response.json()
      code = body?.error?.code ?? body?.detail?.[0]?.type ?? 'ERR_UNKNOWN'
      params = body?.error?.params ?? {}
    } catch {
      /* resposta sem corpo JSON: fica ERR_UNKNOWN */
    }
    // Token vencido ou usuário desativado: a sessão acaba aqui e a tela volta ao login.
    if (response.status === 401 && !path.startsWith('/auth/') && useAuth.getState().mode !== 'open') {
      useAuth.getState().signOut()
    }
    throw new ApiError(code, params, response.status)
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}

export type VisitState =
  | 'expected'
  | 'at_gate_in'
  | 'in_yard'
  | 'at_dock'
  | 'at_gate_out'
  | 'departed'
  | 'rejected'

export interface Visit {
  id: string
  reference: string
  state: VisitState
  plate: string
  trailer_plate: string | null
  driver_name: string
  carrier_name: string | null
  product_name: string | null
  operation_type_code: string
  operation_direction: string
  slot_code: string | null
  dock_code: string | null
  arrived_at: string
  gate_in_at: string | null
  gate_out_at: string | null
  dwell_seconds: number
  target_dwell_minutes: number
  blocked_reason_code: string | null
  document_number: string | null
}

export interface VisitEvent {
  occurred_at: string
  event_type: string
  source: string
  actor: string | null
  from_state: string | null
  to_state: string | null
  payload: Record<string, unknown>
}

export interface VisitDetail extends Visit {
  events: VisitEvent[]
}

export interface YardMapData {
  plant_code: string
  timezone: string
  generated_at: string
  zones: {
    id: string
    code: string
    kind: string
    x: number
    y: number
    width: number
    height: number
    color_token: string | null
  }[]
  slots: {
    id: string
    code: string
    zone_id: string
    kind: string
    status: string
    x: number
    y: number
    width: number
    height: number
    occupied: boolean
    visit_id: string | null
    visit_reference: string | null
    plate: string | null
    since: string | null
    dwell_seconds: number | null
  }[]
  docks: {
    id: string
    code: string
    x: number
    y: number
    width: number
    height: number
    direction: string
    status: string
    visit_id: string | null
    plate: string | null
  }[]
  gates: { id: string; code: string; x: number; y: number; direction: string | null }[]
  scales: { id: string; code: string; x: number; y: number }[]
}

export interface YardOverview {
  vehicles_in_yard: number
  at_gate_in: number
  at_dock: number
  slots_total: number
  slots_occupied: number
  slot_occupancy_pct: number
  docks_total: number
  docks_occupied: number
  dock_occupancy_pct: number
  gate_in_today: number
  gate_out_today: number
  avg_dwell_seconds: number
  p95_dwell_seconds: number
  over_target_dwell: number
  manual_event_pct: number
}

export interface OperationType {
  id: string
  code: string
  direction: string
  requires_weighing: boolean
  requires_dock: boolean
  target_dwell_minutes: number
}

export interface Product {
  id: string
  sku: string
  name: string
  hazardous: boolean
}

export interface Appointment {
  id: string
  reference: string
  state: string
  version: number
  dock_code: string
  plate: string
  carrier_name: string | null
  product_name: string | null
  operation_type_code: string
  resource_code: string | null
  slot_code: string | null
  starts_at: string
  ends_at: string
  priority_code: string | null
  priority_rank: number
  channel: string
  visit_id: string | null
}

export interface AppointmentChange {
  occurred_at: string
  actor: string | null
  reason_code: string | null
  from_state: string | null
  to_state: string | null
  from_starts_at: string | null
  to_starts_at: string | null
  impact_json: Record<string, number | string | null>
}

export interface AvailabilityWindow {
  dock_code: string
  starts_at: string
  ends_at: string
  available: boolean
  reason_code: string | null
}

export interface WeighingCapture {
  occurred_at: string
  kind: string
  weight_kg: number
  stable: boolean
  vehicle_positioned: boolean
  source: string
  image_ref: string | null
}

export interface WeighingTicket {
  id: string
  reference: string
  state: string
  visit_reference: string | null
  plate: string | null
  scale_code: string | null
  mode: string
  gross_kg: number | null
  tare_kg: number | null
  net_kg: number | null
  tare_source: string | null
  document_number: string | null
  document_net_kg: number | null
  divergence_kg: number | null
  divergence_pct: string | null
  tolerance_pct: string
  within_tolerance: boolean | null
  tare_drift_pct: string | null
  source: string
  operator: string | null
  integrity_hash: string | null
  reprint_count: number
  closed_at: string | null
  captures: WeighingCapture[]
}

export interface ScaleReadingLive {
  scale_code: string
  weight_kg: number
  stable: boolean
  quality: string
  occurred_at: string
}

export interface ScreeningResult {
  decision: 'admit' | 'queue' | 'reject'
  reason_code: string | null
  plate: string | null
  appointment_reference: string | null
  dock_id: string | null
  requires_human: boolean
}

export interface ChecklistItem {
  id: string
  code: string
  position: number
  severity: 'blocking' | 'warning' | 'info'
  requires_photo: boolean
}

export interface GateDevice {
  id: string
  code: string
  kind: string
  protocol: string
  status: string
  last_seen_at: string | null
}

export interface AccessCommandResult {
  id: string
  requested_at: string
  action: string
  state: string
  origin: string
  plc_permissive: boolean | null
  permissive_quality: string | null
  authorized_by: string | null
  approved_by: string | null
  failure_code: string | null
  acknowledged_at: string | null
}

export interface IdentificationRow {
  occurred_at: string
  method: string
  value: string | null
  confidence: string | null
  state: string
  image_ref: string | null
}

export interface MoveTask {
  id: string
  reference: string
  state: string
  plate: string | null
  visit_id: string
  visit_reference: string | null
  from_slot_code: string | null
  to_slot_code: string | null
  to_dock_code: string | null
  spotter_code: string | null
  priority_rank: number
  cost_score: string
  distance_m: string | null
  sla_deadline: string | null
  queued_at: string | null
  accepted_at: string | null
  confirmed_at: string | null
  confirmation_kind: string | null
}

export interface Spotter {
  code: string
  full_name: string
  shift_code: string | null
}

export interface MoveDeviation {
  detected_at: string
  vehicle_id: string
  expected_slot_id: string | null
  actual_slot_id: string | null
  state: string
}

export interface DockVisit {
  id: string
  dock_id: string
  visit_id: string
  state: string
  arrived_at: string
  docked_at: string | null
  started_at: string | null
  finished_at: string | null
  released_at: string | null
  paused_seconds: number
  pause_reason_code: string | null
}

export interface VisitHold {
  id: string
  kind: string
  reason_code: string
  opened_at: string
  opened_by: string
  released_at: string | null
  released_by: string | null
}

export interface AiProposal {
  id: string
  reference: string
  kind: string
  state: string
  created_at: string
  expires_at: string
  rationale: string
  impact_json: Record<string, string | number | boolean | null>
  payload_json: Record<string, unknown>
  confidence: string | null
  model_version: string | null
  approved_by: string | null
  approved_at: string | null
  rejected_reason_code: string | null
  executed_at: string | null
  execution_result: string | null
}

export interface BottleneckSignal {
  id: string
  detected_at: string
  scope: string
  scope_ref: string | null
  severity: string
  metric: string
  value: string
  threshold: string
  state: string
  acknowledged_by: string | null
  acknowledged_at: string | null
}

export interface TowerOverview {
  gate_queue: number
  in_yard: number
  over_dwell: number
  demurrage_risk: number
  docks_busy: number
  docks_total: number
  late_appointments: number
  open_moves: number
  open_holds: number
  alarms: number
  pending_proposals: number
}

export interface UserWithPassword {
  user: SessionUser
  temporary_password: string | null
}

export interface AuthAuditRow {
  occurred_at: string
  event_type: string
  actor: string | null
  target_email: string | null
  ip: string | null
  payload: Record<string, unknown>
}

export type PlantSegment =
  | 'general'
  | 'food'
  | 'beverage'
  | 'chemical'
  | 'steel'
  | 'automotive'
  | 'logistics'
  | 'agro'

export const AREA_KINDS = [
  'parking',
  'staging',
  'quarantine',
  'scale_queue',
  'dock_approach',
  'cold_chain',
] as const
export type AreaKind = (typeof AREA_KINDS)[number]

export interface PlantSummary {
  id: string
  code: string
  name: string
  timezone: string
  segment: PlantSegment
  city: string | null
  description: string | null
  active: boolean
  zones: number
  slots: number
  docks: number
  gates: number
  scales: number
}

export interface LayoutTemplate {
  zones: number
  slots_per_zone: number
  docks: number
  gates: number
  scales: number
  cold_chain_zone: boolean
}

export interface CfgZone {
  id: string
  plant_id: string
  code: string
  kind: AreaKind
  x: number
  y: number
  width: number
  height: number
  color_token: string | null
}
export interface CfgSlot {
  id: string
  plant_id: string
  zone_id: string
  code: string
  kind: AreaKind
  status: 'available' | 'blocked' | 'maintenance'
  length_m: number
  x: number
  y: number
  width: number
  height: number
  notes: string | null
}
export interface CfgDock {
  id: string
  plant_id: string
  zone_id: string | null
  code: string
  direction: 'inbound' | 'outbound' | 'both'
  status: 'available' | 'occupied' | 'blocked'
  x: number
  y: number
  width: number
  height: number
}
export interface CfgGate {
  id: string
  plant_id: string
  code: string
  direction: 'in' | 'out' | 'both'
  x: number
  y: number
  active: boolean
}
export interface CfgScale {
  id: string
  plant_id: string
  code: string
  capacity_kg: number
  division_kg: number
  protocol: string
  x: number
  y: number
  active: boolean
}
export interface PlantLayout {
  plant: PlantSummary
  zones: CfgZone[]
  slots: CfgSlot[]
  docks: CfgDock[]
  gates: CfgGate[]
  scales: CfgScale[]
}
export type LayoutEntity = 'zone' | 'slot' | 'dock' | 'gate' | 'scale'
const PLURAL: Record<LayoutEntity, string> = {
  zone: 'zones',
  slot: 'slots',
  dock: 'docks',
  gate: 'gates',
  scale: 'scales',
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  body: JSON.stringify(body),
})

export const authApi = {
  config: () => request<{ mode: AuthMode }>('/auth/config'),
  login: (email: string, password: string) =>
    request<{ token: string; expires_at: string; user: SessionUser }>(
      '/auth/login',
      json('POST', { email, password }),
    ),
  me: () => request<SessionUser>('/auth/me'),
  changePassword: (current_password: string, new_password: string) =>
    request<SessionUser>('/auth/change-password', json('POST', { current_password, new_password })),
  users: () => request<SessionUser[]>('/users'),
  createUser: (body: { email: string; name: string; roles: string[]; password?: string }) =>
    request<UserWithPassword>('/users', json('POST', body)),
  updateUser: (id: string, body: { name?: string; roles?: string[]; active?: boolean }) =>
    request<SessionUser>(`/users/${id}`, json('PATCH', body)),
  resetPassword: (id: string) =>
    request<UserWithPassword>(`/users/${id}/reset-password`, { method: 'POST' }),
  audit: () => request<AuthAuditRow[]>('/users/audit?limit=200'),
}

export const yardConfigApi = {
  plants: () => request<PlantSummary[]>('/yard-config/plants'),
  createPlant: (
    body: Omit<PlantSummary, 'id' | 'zones' | 'slots' | 'docks' | 'gates' | 'scales'> & {
      template: LayoutTemplate | null
    },
  ) => request<PlantSummary>('/yard-config/plants', json('POST', body)),
  updatePlant: (id: string, body: Partial<PlantSummary>) =>
    request<PlantSummary>(`/yard-config/plants/${id}`, json('PATCH', body)),
  layout: (plantId: string) => request<PlantLayout>(`/yard-config/plants/${plantId}/layout`),
  createElement: (entity: LayoutEntity, plantId: string, body: Record<string, unknown>) =>
    request<unknown>(`/yard-config/plants/${plantId}/${PLURAL[entity]}`, json('POST', body)),
  updateElement: (entity: LayoutEntity, id: string, body: Record<string, unknown>) =>
    request<unknown>(`/yard-config/${PLURAL[entity]}/${id}`, json('PATCH', body)),
  deleteElement: (entity: LayoutEntity, id: string) =>
    request<void>(`/yard-config/${PLURAL[entity]}/${id}`, { method: 'DELETE' }),
  generateSlots: (zoneId: string, body: Record<string, unknown>) =>
    request<CfgSlot[]>(`/yard-config/zones/${zoneId}/slots/generate`, json('POST', body)),
}

export const api = {
  yardMap: (plant?: string | null) =>
    request<YardMapData>(`/yard/map${plant ? `?plant=${encodeURIComponent(plant)}` : ''}`),
  overview: () => request<YardOverview>('/kpi/yard-overview'),
  visits: (params: { onlyOpen?: boolean; search?: string; state?: VisitState[] } = {}) => {
    const query = new URLSearchParams()
    if (params.onlyOpen) query.set('only_open', 'true')
    if (params.search) query.set('search', params.search)
    params.state?.forEach((s) => query.append('state', s))
    return request<Visit[]>(`/visits?${query.toString()}`)
  },
  visit: (id: string) => request<VisitDetail>(`/visits/${id}`),
  gateIn: (body: {
    plate: string
    driver_document: string
    operation_type_code: string
    product_sku?: string
    gate_code?: string
    document_number?: string
    seal_number?: string
    actor?: string
  }) => request<Visit>('/visits/gate-in', { method: 'POST', body: JSON.stringify(body) }),
  assignSlot: (id: string, slotCode?: string) =>
    request<Visit>(`/visits/${id}/slot`, {
      method: 'POST',
      body: JSON.stringify({ slot_code: slotCode ?? null, actor: currentActor() }),
    }),
  assignDock: (id: string, dockCode: string) =>
    request<Visit>(`/visits/${id}/dock`, {
      method: 'POST',
      body: JSON.stringify({ dock_code: dockCode, actor: currentActor() }),
    }),
  gateOut: (id: string, gateCode?: string) =>
    request<Visit>(`/visits/${id}/gate-out`, {
      method: 'POST',
      body: JSON.stringify({ gate_code: gateCode ?? null, actor: currentActor() }),
    }),
  appointments: (params: { dateFrom?: string; dateTo?: string; dockCode?: string } = {}) => {
    const query = new URLSearchParams()
    if (params.dateFrom) query.set('date_from', params.dateFrom)
    if (params.dateTo) query.set('date_to', params.dateTo)
    if (params.dockCode) query.set('dock_code', params.dockCode)
    return request<Appointment[]>(`/scheduling/appointments?${query.toString()}`)
  },
  availability: (dateFrom?: string) =>
    request<AvailabilityWindow[]>(
      `/scheduling/availability${dateFrom ? `?date_from=${encodeURIComponent(dateFrom)}` : ''}`,
    ),
  createAppointment: (body: Record<string, unknown>) =>
    request<Appointment>('/scheduling/appointments', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  confirmAppointment: (id: string, version: number, slotCode?: string) =>
    request<Appointment>(`/scheduling/appointments/${id}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ version, slot_code: slotCode ?? null, actor: currentActor() }),
    }),
  rescheduleAppointment: (
    id: string,
    body: {
      starts_at: string
      ends_at: string
      dock_code?: string
      reason_code: string
      version: number
    },
  ) =>
    request<Appointment>(`/scheduling/appointments/${id}/reschedule`, {
      method: 'POST',
      body: JSON.stringify({ ...body, actor: currentActor() }),
    }),
  cancelAppointment: (id: string, body: { reason_code: string; version: number }) =>
    request<Appointment>(`/scheduling/appointments/${id}/cancel`, {
      method: 'POST',
      body: JSON.stringify({ ...body, actor: currentActor() }),
    }),
  noShowAppointment: (id: string, actor: string) =>
    request<Appointment>(`/scheduling/appointments/${id}/no-show`, {
      method: 'POST',
      body: JSON.stringify({ actor }),
    }),
  appointmentImpact: (id: string, startsAt: string, endsAt: string, dockCode?: string) => {
    const query = new URLSearchParams({ starts_at: startsAt, ends_at: endsAt })
    if (dockCode) query.set('dock_code', dockCode)
    return request<{
      displaced_appointments: number
      delayed_minutes: number
      conflicting_references: string[]
    }>(`/scheduling/appointments/${id}/impact?${query.toString()}`)
  },
  appointmentHistory: (id: string) =>
    request<AppointmentChange[]>(`/scheduling/appointments/${id}/history`),
  scaleLive: (scaleCode: string) =>
    request<ScaleReadingLive>(`/weighing/scales/${scaleCode}/live`),
  weighingTickets: (visitReference?: string) =>
    request<WeighingTicket[]>(
      `/weighing/tickets${visitReference ? `?visit_reference=${visitReference}` : ''}`,
    ),
  weighingTicket: (id: string) => request<WeighingTicket>(`/weighing/tickets/${id}`),
  openWeighing: (body: {
    visit_reference: string
    scale_code: string
    document_net_kg?: number
    document_number?: string
    operator?: string
    reentry_justified?: boolean
  }) => request<WeighingTicket>('/weighing/tickets', { method: 'POST', body: JSON.stringify(body) }),
  captureWeighing: (
    id: string,
    body: {
      kind: 'gross' | 'tare' | 'axle'
      vehicle_positioned?: boolean
      image_ref?: string
      operator?: string
      manual_weight_kg?: number
      reason_code?: string
      second_factor_user?: string
    },
  ) =>
    request<WeighingTicket>(`/weighing/tickets/${id}/capture`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  closeWeighing: (id: string, body: { document_net_kg?: number; image_ref?: string }) =>
    request<WeighingTicket>(`/weighing/tickets/${id}/close`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  reprintWeighing: (id: string, body: { actor: string; reason_code: string }) =>
    request<WeighingTicket>(`/weighing/tickets/${id}/reprint`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  identify: (body: {
    gate_code: string
    method: string
    value: string
    confidence?: number
    image_ref?: string
    actor?: string
  }) => request<ScreeningResult>('/gate/identify', { method: 'POST', body: JSON.stringify(body) }),
  devices: (kind?: string) =>
    request<GateDevice[]>(`/gate/devices${kind ? `?kind=${kind}` : ''}`),
  checklist: (visitId: string) => request<ChecklistItem[]>(`/gate/visits/${visitId}/checklist`),
  answerChecklist: (
    visitId: string,
    body: {
      actor: string
      answers: { item_id: string; passed: boolean; note?: string; photo_ref?: string }[]
    },
  ) =>
    request<string[]>(`/gate/visits/${visitId}/checklist`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  gateCommand: (body: {
    device_code: string
    action: string
    visit_id?: string
    origin?: string
    authorized_by?: string
    approved_by?: string
    ai_proposal_id?: string
    reason_code?: string
  }) => request<AccessCommandResult>('/gate/command', { method: 'POST', body: JSON.stringify(body) }),
  identifications: (gateCode?: string) =>
    request<IdentificationRow[]>(
      `/gate/identifications${gateCode ? `?gate_code=${gateCode}` : ''}`,
    ),
  spotters: () => request<Spotter[]>('/moves/spotters'),
  moveQueue: (spotterCode?: string) =>
    request<MoveTask[]>(`/moves/queue${spotterCode ? `?spotter_code=${spotterCode}` : ''}`),
  createMove: (body: {
    visit_reference: string
    to_slot_code?: string
    to_dock_code?: string
    priority_rank?: number
    sla_minutes?: number
    client_event_id?: string
  }) => request<MoveTask>('/moves/tasks', { method: 'POST', body: JSON.stringify(body) }),
  acceptMove: (id: string, spotterCode: string) =>
    request<MoveTask>(`/moves/tasks/${id}/accept`, {
      method: 'POST',
      body: JSON.stringify({ spotter_code: spotterCode }),
    }),
  startMove: (id: string) => request<MoveTask>(`/moves/tasks/${id}/start`, { method: 'POST' }),
  confirmMove: (
    id: string,
    body: { kind: 'qr' | 'rtls' | 'photo' | 'manual'; value?: string; reason_code?: string },
  ) =>
    request<MoveTask>(`/moves/tasks/${id}/confirm`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  moveDeviations: () => request<MoveDeviation[]>('/moves/deviations'),
  dockStage: (
    visitId: string,
    body: { stage: string; dock_code?: string; reason_code?: string },
  ) =>
    request<DockVisit>(`/docks/visits/${visitId}/stage`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  dockVisits: (visitId: string) => request<DockVisit[]>(`/docks/visits/${visitId}`),
  holds: (visitId: string) => request<VisitHold[]>(`/docks/visits/${visitId}/holds`),
  openHold: (
    visitId: string,
    body: { kind: string; reason_code: string; opened_by: string; note?: string },
  ) =>
    request<VisitHold>(`/docks/visits/${visitId}/holds`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  releaseHold: (holdId: string, releasedBy: string) =>
    request<VisitHold>(`/docks/holds/${holdId}/release`, {
      method: 'POST',
      body: JSON.stringify({ released_by: releasedBy }),
    }),
  towerOverview: () => request<TowerOverview>('/control-tower/overview'),
  proposals: (state = 'proposed') =>
    request<AiProposal[]>(`/control-tower/proposals?state=${state}`),
  generateProposals: () =>
    request<AiProposal[]>('/control-tower/proposals/generate', { method: 'POST' }),
  approveProposal: (id: string, approvedBy: string, note?: string) =>
    request<AiProposal>(`/control-tower/proposals/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approved_by: approvedBy, note }),
    }),
  rejectProposal: (id: string, rejectedBy: string, reasonCode: string) =>
    request<AiProposal>(`/control-tower/proposals/${id}/reject`, {
      method: 'POST',
      body: JSON.stringify({ rejected_by: rejectedBy, reason_code: reasonCode }),
    }),
  executeProposal: (id: string, actor: string) =>
    request<AiProposal>(`/control-tower/proposals/${id}/execute`, {
      method: 'POST',
      body: JSON.stringify({ actor }),
    }),
  bottlenecks: () => request<BottleneckSignal[]>('/control-tower/bottlenecks'),
  acknowledgeBottleneck: (id: string, actor: string) =>
    request<BottleneckSignal>(`/control-tower/bottlenecks/${id}/acknowledge`, {
      method: 'POST',
      body: JSON.stringify({ actor }),
    }),
  operationTypes: () => request<OperationType[]>('/catalog/operation-types'),
  products: () => request<Product[]>('/catalog/products'),
}
