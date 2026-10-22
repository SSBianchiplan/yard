import { Button, DataTable, Input, Modal, StatusPill } from '@gplansis/ds'
import type { Column } from '@gplansis/ds'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useErrorMessage } from '@/components/VisitStatus'
import type { UserWithPassword } from '@/lib/api'
import { authApi } from '@/lib/api'
import type { SessionUser } from '@/lib/auth'
import { ROLES, useAuth } from '@/lib/auth'
import { useFormat } from '@/lib/format'

const ROLE_ORDER = [
  ROLES.admin,
  ROLES.supervisor,
  ROLES.controller,
  ROLES.scheduler,
  ROLES.gate,
  ROLES.scale,
  ROLES.spotter,
  ROLES.dock,
  ROLES.device,
]

interface Draft {
  id: string | null
  email: string
  name: string
  roles: string[]
  password: string
  active: boolean
  is_master: boolean
}

const EMPTY: Draft = {
  id: null,
  email: '',
  name: '',
  roles: [ROLES.controller],
  password: '',
  active: true,
  is_master: false,
}

export function Users() {
  const { t } = useTranslation(['admin', 'common'])
  const format = useFormat()
  const errorMessage = useErrorMessage()
  const queryClient = useQueryClient()
  const { isMaster, subject } = useAuth()
  const [search, setSearch] = useState('')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [issued, setIssued] = useState<UserWithPassword | null>(null)
  const [copied, setCopied] = useState(false)

  const users = useQuery({ queryKey: ['users'], queryFn: authApi.users })
  const audit = useQuery({ queryKey: ['users', 'audit'], queryFn: authApi.audit })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['users'] })
  }

  const save = useMutation({
    mutationFn: async (value: Draft) => {
      if (value.id) {
        await authApi.updateUser(value.id, {
          name: value.name,
          roles: value.roles,
          active: value.active,
        })
        return null
      }
      return authApi.createUser({
        email: value.email,
        name: value.name,
        roles: value.roles,
        password: value.password || undefined,
      })
    },
    onSuccess: (result) => {
      setDraft(null)
      if (result?.temporary_password) setIssued(result)
      refresh()
    },
  })

  const reset = useMutation({
    mutationFn: (id: string) => authApi.resetPassword(id),
    onSuccess: (result) => {
      setDraft(null)
      setIssued(result)
      refresh()
    },
  })

  const rows = useMemo(() => {
    const term = search.trim().toLowerCase()
    return (users.data ?? []).filter(
      (user) =>
        !term || user.name.toLowerCase().includes(term) || user.email.toLowerCase().includes(term),
    )
  }, [users.data, search])

  const columns: Column<SessionUser>[] = [
    {
      key: 'name',
      header: t('admin:users.name'),
      width: 200,
      pinned: true,
      sortable: true,
      value: (user) => user.name,
    },
    {
      key: 'email',
      priority: 'secondary',
      header: t('admin:users.email'),
      width: 240,
      sortable: true,
      value: (user) => user.email,
    },
    {
      key: 'roles',
      priority: 'secondary',
      header: t('admin:users.roles'),
      width: 260,
      value: (user) => user.roles.join(','),
      render: (user) => (
        <span className="row-actions">
          {user.is_master && <StatusPill tone="moving">{t('admin:users.master')}</StatusPill>}
          {user.roles.map((role) => t(`admin:role.${role}`)).join(', ')}
        </span>
      ),
    },
    {
      key: 'status',
      header: t('admin:users.status'),
      width: 100,
      value: (user) => (user.active ? 1 : 0),
      render: (user) => (
        <StatusPill tone={user.active ? 'running' : 'stopped'}>
          {user.active ? t('admin:users.active') : t('admin:users.inactive')}
        </StatusPill>
      ),
    },
    {
      key: 'last',
      priority: 'detail',
      header: t('admin:users.lastLogin'),
      width: 150,
      sortable: true,
      value: (user) => user.last_login_at ?? '',
      render: (user) =>
        user.last_login_at ? format.dateTime(user.last_login_at) : t('admin:users.never'),
    },
  ]

  const editing = draft?.id != null
  const toggleRole = (role: string) =>
    setDraft((value) =>
      value
        ? {
            ...value,
            roles: value.roles.includes(role)
              ? value.roles.filter((r) => r !== role)
              : [...value.roles, role],
          }
        : value,
    )

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1 className="page__title">{t('admin:users.title')}</h1>
          <span className="page__subtitle">
            {t('admin:users.subtitle', { count: users.data?.length ?? 0 })}
          </span>
        </div>
        <Button variant="primary" onClick={() => setDraft({ ...EMPTY })}>
          {t('admin:users.new')}
        </Button>
      </div>

      <div className="tower">
        <section className="panel">
          <div className="panel__body">
            <DataTable
              columns={columns}
              rows={rows}
              rowKey={(user) => user.id}
              onRowClick={(user) =>
                setDraft({
                  id: user.id,
                  email: user.email,
                  name: user.name,
                  roles: user.roles,
                  password: '',
                  active: user.active,
                  is_master: user.is_master,
                })
              }
              emptyLabel={t('admin:users.empty')}
              toolbar={
                <Input
                  label={t('common:action.search')}
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              }
              footer={t('admin:users.subtitle', { count: rows.length })}
            />
          </div>
        </section>

        <section className="panel">
          <div className="panel__title">
            <span>{t('admin:users.audit')}</span>
          </div>
          <div className="panel__body panel__body--padded">
            <ul className="timeline-list">
              {(audit.data ?? []).map((row) => (
                <li key={`${row.occurred_at}-${row.event_type}-${row.target_email}`}>
                  <span className="timeline-list__time">{format.dateTime(row.occurred_at)}</span>
                  <span className="row-actions">
                    <StatusPill
                      tone={row.event_type.startsWith('login_') ? 'waiting' : 'running'}
                    >
                      {t(`admin:users.event.${row.event_type}`, { defaultValue: row.event_type })}
                    </StatusPill>
                    <span>{row.target_email}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </div>

      <Modal
        open={draft !== null}
        onClose={() => setDraft(null)}
        title={editing ? t('admin:users.edit') : t('admin:users.new')}
        subtitle={editing ? draft?.email : undefined}
        closeLabel={t('common:action.close')}
        actions={
          <>
            {editing && draft && (
              <Button
                variant="danger"
                disabled={reset.isPending}
                onClick={() => {
                  if (window.confirm(t('admin:users.confirmReset', { email: draft.email }))) {
                    reset.mutate(draft.id as string)
                  }
                }}
              >
                {t('admin:users.resetPassword')}
              </Button>
            )}
            <Button onClick={() => setDraft(null)}>{t('common:action.cancel')}</Button>
            <Button
              variant="primary"
              disabled={!draft?.name || (!editing && !draft?.email) || save.isPending}
              onClick={() => draft && save.mutate(draft)}
            >
              {t('common:action.save')}
            </Button>
          </>
        }
      >
        {draft && (
          <div className="stack">
            {!editing && (
              <Input
                label={t('admin:users.email')}
                type="email"
                autoComplete="off"
                value={draft.email}
                onChange={(event) => setDraft({ ...draft, email: event.target.value })}
              />
            )}
            <Input
              label={t('admin:users.name')}
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            />
            <fieldset className="check-list">
              <legend className="ds-field__label">{t('admin:users.roles')}</legend>
              {ROLE_ORDER.map((role) => {
                const locked =
                  (role === ROLES.admin && !isMaster) ||
                  (draft.is_master && role === ROLES.admin) ||
                  (draft.email === subject && role === ROLES.admin)
                return (
                  <label key={role} className="check-list__item">
                    <input
                      type="checkbox"
                      checked={draft.roles.includes(role)}
                      disabled={locked}
                      onChange={() => toggleRole(role)}
                    />
                    <span>{t(`admin:role.${role}`)}</span>
                  </label>
                )
              })}
            </fieldset>
            {!editing && (
              <Input
                label={t('admin:users.passwordOptional')}
                type="password"
                autoComplete="new-password"
                hint={t('admin:users.passwordHint')}
                value={draft.password}
                onChange={(event) => setDraft({ ...draft, password: event.target.value })}
              />
            )}
            {editing && !draft.is_master && draft.email !== subject && (
              <label className="check-list__item">
                <input
                  type="checkbox"
                  checked={draft.active}
                  onChange={(event) => setDraft({ ...draft, active: event.target.checked })}
                />
                <span>{t('admin:users.active')}</span>
              </label>
            )}
            {(save.error || reset.error) && (
              <div className="alert" role="alert">
                {errorMessage(save.error ?? reset.error)}
              </div>
            )}
          </div>
        )}
      </Modal>

      <Modal
        open={issued !== null}
        onClose={() => {
          setIssued(null)
          setCopied(false)
        }}
        title={t('admin:users.temporaryTitle')}
        closeLabel={t('common:action.close')}
        actions={
          <Button
            variant="primary"
            onClick={() => {
              void navigator.clipboard?.writeText(issued?.temporary_password ?? '')
              setCopied(true)
            }}
          >
            {copied ? t('admin:users.copied') : t('admin:users.copy')}
          </Button>
        }
      >
        {issued && (
          <div className="stack">
            <p>{t('admin:users.temporaryText', { email: issued.user.email })}</p>
            <code className="secret">{issued.temporary_password}</code>
          </div>
        )}
      </Modal>
    </div>
  )
}
