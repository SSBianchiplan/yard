/**
 * Identidade do operador.
 *
 * Antes disso, cada tela mandava `actor: 'guarda.01'` no corpo da requisição — ou seja,
 * a trilha de auditoria registrava o que o cliente dizia ser, não quem era. Agora o
 * `actor` sai daqui, e com a API em modo `local` ou `oidc` daqui sai o que o token diz.
 */

import { create } from 'zustand'

export type AuthMode = 'open' | 'local' | 'oidc'

export interface SessionUser {
  id: string
  email: string
  name: string
  roles: string[]
  active: boolean
  is_master: boolean
  must_change_password: boolean
  last_login_at?: string | null
  created_at?: string | null
}

export interface Session {
  subject: string
  name: string
  roles: string[]
  token: string | null
  mode: AuthMode
}

export const ROLES = {
  scheduler: 'yard.scheduler',
  gate: 'yard.gate',
  scale: 'yard.scale',
  spotter: 'yard.spotter',
  dock: 'yard.dock',
  supervisor: 'yard.supervisor',
  controller: 'yard.controller',
  admin: 'yard.admin',
  device: 'yard.device',
} as const

const STORAGE_KEY = 'yard.session'

interface Stored {
  token: string
  expiresAt: string
  user: SessionUser
}

function readStored(): Stored | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const stored = JSON.parse(raw) as Stored
    return new Date(stored.expiresAt) > new Date() ? stored : null
  } catch {
    return null
  }
}

function writeStored(stored: Stored | null) {
  try {
    if (stored) localStorage.setItem(STORAGE_KEY, JSON.stringify(stored))
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* navegador sem storage: a sessão vive só em memória */
  }
}

interface AuthState extends Session {
  /** `null` até a API dizer como autentica. */
  ready: boolean
  user: SessionUser | null
  isMaster: boolean
  setSession: (session: Partial<Session>) => void
  setMode: (mode: AuthMode) => void
  signIn: (token: string, expiresAt: string, user: SessionUser) => void
  updateUser: (user: SessionUser) => void
  signOut: () => void
  can: (...roles: string[]) => boolean
}

const stored = readStored()

export const useAuth = create<AuthState>((set, get) => ({
  ready: false,
  mode: 'open',
  token: stored?.token ?? null,
  user: stored?.user ?? null,
  subject: stored?.user.email ?? localStorage.getItem('yard.actor') ?? 'operador.dev',
  name: stored?.user.name ?? localStorage.getItem('yard.actor') ?? 'Operador',
  roles: stored?.user.roles ?? [ROLES.admin],
  isMaster: stored?.user.is_master ?? false,
  setSession: (session) => {
    if (session.subject && get().mode === 'open') {
      try {
        localStorage.setItem('yard.actor', session.subject)
      } catch {
        /* sem storage */
      }
    }
    set(session)
  },
  setMode: (mode) => {
    if (mode === 'open') {
      // Desenvolvimento: a API aceita qualquer um como admin, a tela também.
      set({ mode, ready: true, roles: [ROLES.admin], isMaster: true })
    } else {
      set({ mode, ready: true })
    }
  },
  signIn: (token, expiresAt, user) => {
    writeStored({ token, expiresAt, user })
    set({
      token,
      user,
      subject: user.email,
      name: user.name,
      roles: user.roles,
      isMaster: user.is_master,
    })
  },
  updateUser: (user) => {
    const current = readStored()
    if (current) writeStored({ ...current, user })
    set({ user, name: user.name, roles: user.roles, isMaster: user.is_master })
  },
  signOut: () => {
    writeStored(null)
    set({ token: null, user: null, roles: [], isMaster: false })
  },
  can: (...roles: string[]) => {
    const current = get().roles
    return current.includes(ROLES.admin) || roles.some((role) => current.includes(role))
  },
}))

/** Cabeçalhos de identidade para o cliente HTTP. */
export function authHeaders(): Record<string, string> {
  const { token, subject, mode } = useAuth.getState()
  if (mode !== 'open' && token) return { Authorization: `Bearer ${token}` }
  // Modo aberto: a API registra este cabeçalho como ator, e diz que é desenvolvimento.
  return { 'X-Dev-Actor': subject }
}

/** Quem está agindo agora — é isto que vai para a trilha. */
export function currentActor(): string {
  return useAuth.getState().subject
}
