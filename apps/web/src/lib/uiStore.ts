import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Theme = 'light' | 'dark' | 'hmi'
export type Density = 'compact' | 'default' | 'touch'

interface UiState {
  theme: Theme
  density: Density
  /** Densidade escolhida pelo operador vence a automática — e não volta atrás sozinha. */
  densityPinned: boolean
  /** Pátio que a torre mostra. `null` = o padrão da instância. */
  plantCode: string | null
  setTheme: (theme: Theme) => void
  setDensity: (density: Density) => void
  setPlantCode: (code: string | null) => void
}

/**
 * Densidade automática pelo dispositivo, não pela largura da janela.
 *
 * Quem abre no celular ou num totem tem ponteiro grosso e precisa de alvo de 44px;
 * quem abre no painel de parede da torre quer ver o pátio inteiro sem rolar. Decidir
 * isso por `innerWidth` erra nos dois lados: um desktop com janela estreita não vira
 * touch, e um tablet em paisagem não vira wallboard.
 */
function detectDensity(): Density {
  if (typeof window === 'undefined') return 'default'
  if (window.matchMedia('(pointer: coarse)').matches) return 'touch'
  if (window.matchMedia('(min-width: 1800px)').matches) return 'compact'
  return 'default'
}

function apply(theme: Theme, density: Density) {
  document.documentElement.dataset.theme = theme
  document.documentElement.dataset.density = density
}

export const useUiStore = create<UiState>()(
  persist(
    (set, get) => ({
      theme: 'light',
      density: detectDensity(),
      densityPinned: false,
      plantCode: null,
      setPlantCode: (plantCode) => set({ plantCode }),
      setTheme: (theme) => {
        apply(theme, get().density)
        set({ theme })
      },
      setDensity: (density) => {
        apply(get().theme, density)
        set({ density, densityPinned: true })
      },
    }),
    {
      name: 'yard.ui',
      onRehydrateStorage: () => (state) => {
        if (!state) return
        // Sem escolha explícita guardada, o dispositivo decide a cada abertura:
        // o mesmo login abre touch no tablet da guarita e compacto na parede da torre.
        const density = state.densityPinned ? state.density : detectDensity()
        state.density = density
        apply(state.theme, density)
      },
    },
  ),
)
