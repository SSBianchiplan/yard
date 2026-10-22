import { Button, Input, Modal } from '@gplansis/ds'
import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useErrorMessage } from '@/components/VisitStatus'
import { authApi } from '@/lib/api'
import { useAuth } from '@/lib/auth'

interface Props {
  open: boolean
  /** Senha provisória: não dá para fechar sem trocar. */
  forced?: boolean
  onClose: () => void
}

export function ChangePasswordModal({ open, forced = false, onClose }: Props) {
  const { t } = useTranslation(['admin', 'common'])
  const errorMessage = useErrorMessage()
  const updateUser = useAuth((state) => state.updateUser)
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)

  const change = useMutation({
    mutationFn: () => authApi.changePassword(current, next),
    onSuccess: (user) => {
      updateUser(user)
      setCurrent('')
      setNext('')
      setConfirm('')
      onClose()
    },
  })

  const submit = () => {
    setLocalError(null)
    if (next !== confirm) {
      setLocalError(t('admin:auth.mismatch'))
      return
    }
    change.mutate()
  }

  return (
    <Modal
      open={open}
      onClose={forced ? () => undefined : onClose}
      title={t('admin:auth.changeTitle')}
      subtitle={forced ? t('admin:auth.changeForced') : undefined}
      closeLabel={t('common:action.close')}
      actions={
        <>
          {!forced && <Button onClick={onClose}>{t('common:action.cancel')}</Button>}
          <Button
            variant="primary"
            disabled={!current || !next || !confirm || change.isPending}
            onClick={submit}
          >
            {t('common:action.save')}
          </Button>
        </>
      }
    >
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <Input
          label={t('admin:auth.current')}
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
        />
        <Input
          label={t('admin:auth.new')}
          type="password"
          autoComplete="new-password"
          hint={t('admin:auth.rule')}
          value={next}
          onChange={(event) => setNext(event.target.value)}
        />
        <Input
          label={t('admin:auth.confirm')}
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
        />
        {(localError || change.error) && (
          <div className="alert" role="alert">
            {localError ?? errorMessage(change.error)}
          </div>
        )}
        <button type="submit" hidden aria-hidden />
      </form>
    </Modal>
  )
}
