import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { useAuth } from './auth'

/**
 * WebSocket do pátio. Toda mensagem invalida as consultas de mapa/fila: o mapa e a
 * fila de portaria são ao vivo, não "atualize a página".
 *
 * Queda de conexão não trava a tela — reconecta com recuo e o indicador mostra o estado
 * real da comunicação, porque número sem frescor é mentira em sala de controle.
 */
export function useYardLive() {
  const queryClient = useQueryClient()
  const [connected, setConnected] = useState(false)
  const [lastMessageAt, setLastMessageAt] = useState<string | null>(null)
  const token = useAuth((state) => state.token)

  useEffect(() => {
    let socket: WebSocket | null = null
    let retry = 0
    let timer: number | undefined
    let disposed = false

    const connect = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      // Navegador não manda Authorization em WebSocket: o token vai no subprotocolo,
      // que é cabeçalho — na query string ele pararia no log de acesso do proxy.
      const url = `${protocol}://${window.location.host}/ws/yard`
      socket = token ? new WebSocket(url, ['yard.bearer', token]) : new WebSocket(url)

      socket.onopen = () => {
        retry = 0
        setConnected(true)
      }
      socket.onmessage = () => {
        setLastMessageAt(new Date().toISOString())
        void queryClient.invalidateQueries({ queryKey: ['yard'] })
        void queryClient.invalidateQueries({ queryKey: ['visits'] })
        void queryClient.invalidateQueries({ queryKey: ['overview'] })
      }
      socket.onclose = () => {
        setConnected(false)
        if (disposed) return
        retry = Math.min(retry + 1, 6)
        timer = window.setTimeout(connect, 500 * 2 ** retry)
      }
      socket.onerror = () => socket?.close()
    }

    connect()
    return () => {
      disposed = true
      window.clearTimeout(timer)
      socket?.close()
    }
  }, [queryClient, token])

  return { connected, lastMessageAt }
}
