import type { ReactNode } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'

/** Larguras onde a tabela troca de comportamento — as mesmas do app. */
const NARROW = 640
const MEDIUM = 1024

function useViewportWidth(): number {
  const [width, setWidth] = useState(() =>
    typeof window === 'undefined' ? 1440 : window.innerWidth,
  )
  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return width
}

export interface Column<T> {
  key: string
  /** Cabeçalho já traduzido pela tela. */
  header: string
  width?: number
  align?: 'left' | 'right'
  pinned?: boolean
  sortable?: boolean
  /**
   * O que a coluna vale quando a tela é estreita.
   *
   * `essential` sempre aparece (placa, estado); `secondary` some no celular;
   * `detail` some também no tablet. Espremer nove colunas num telefone não é
   * densidade, é ilegibilidade.
   */
  priority?: 'essential' | 'secondary' | 'detail'
  render?: (row: T) => ReactNode
  value?: (row: T) => string | number | null
}

export interface DataTableProps<T> {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  onRowClick?: (row: T) => void
  selectedKey?: string | null
  /** Texto já traduzido para lista vazia. */
  emptyLabel: string
  /** Rodapé já traduzido, ex.: "1.240 de 5.000 linhas". */
  footer?: ReactNode
  toolbar?: ReactNode
  rowHeight?: number
  maxHeight?: number
}

/**
 * Tabela densa de operação. Virtualiza por janela de scroll — 5.000 linhas rolam sem
 * engasgo porque só o que está na viewport (mais 12 linhas de folga) vai ao DOM.
 * Coluna fixa continua legível no scroll horizontal: em pátio, a placa nunca some.
 */
export function DataTable<T>({
  columns: allColumns,
  rows,
  rowKey,
  onRowClick,
  selectedKey,
  emptyLabel,
  footer,
  toolbar,
  rowHeight = 32,
  maxHeight,
}: DataTableProps<T>) {
  const viewportWidth = useViewportWidth()
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewport, setViewport] = useState(600)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Colunas visíveis conforme a largura: a essencial nunca sai.
  const columns = useMemo(() => {
    if (viewportWidth > MEDIUM) return allColumns
    const drop = viewportWidth <= NARROW ? ['secondary', 'detail'] : ['detail']
    const visible = allColumns.filter(
      (column) => !drop.includes(column.priority ?? 'essential'),
    )
    return visible.length ? visible : allColumns.slice(0, 2)
  }, [allColumns, viewportWidth])

  const sorted = useMemo(() => {
    if (!sort) return rows
    const column = columns.find((c) => c.key === sort.key)
    if (!column?.value) return rows
    const read = column.value
    return [...rows].sort((a, b) => {
      const va = read(a)
      const vb = read(b)
      if (va === vb) return 0
      if (va === null || va === undefined) return 1
      if (vb === null || vb === undefined) return -1
      return (va > vb ? 1 : -1) * sort.dir
    })
  }, [rows, sort, columns])

  const overscan = 12
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan)
  const visibleCount = Math.ceil(viewport / rowHeight) + overscan * 2
  const end = Math.min(sorted.length, start + visibleCount)
  const slice = sorted.slice(start, end)

  const toggleSort = (column: Column<T>) => {
    if (!column.sortable || !column.value) return
    setSort((current) =>
      current?.key === column.key
        ? { key: column.key, dir: current.dir === 1 ? -1 : 1 }
        : { key: column.key, dir: 1 },
    )
  }

  return (
    <div className="ds-table" style={maxHeight ? { maxHeight } : undefined}>
      {toolbar && <div className="ds-table__toolbar">{toolbar}</div>}
      <div
        className="ds-table__scroll"
        ref={scrollRef}
        onScroll={(event) => {
          const target = event.currentTarget
          setScrollTop(target.scrollTop)
          setViewport(target.clientHeight)
        }}
      >
        <table className="ds-table__grid">
          <thead className="ds-table__head">
            <tr>
              {columns.map((column) => (
                <th
                  key={column.key}
                  className={column.pinned ? 'ds-table__pin' : undefined}
                  style={{ width: column.width, textAlign: column.align ?? 'left' }}
                  onClick={() => toggleSort(column)}
                  aria-sort={
                    sort?.key === column.key
                      ? sort.dir === 1
                        ? 'ascending'
                        : 'descending'
                      : undefined
                  }
                >
                  {column.header}
                  {sort?.key === column.key ? (sort.dir === 1 ? ' ↑' : ' ↓') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {start > 0 && <tr style={{ height: start * rowHeight }} aria-hidden="true" />}
            {slice.map((row) => {
              const key = rowKey(row)
              return (
                <tr
                  key={key}
                  data-selected={selectedKey === key}
                  onClick={() => onRowClick?.(row)}
                  style={{ height: rowHeight }}
                >
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={[
                        column.pinned ? 'ds-table__pin' : '',
                        column.align === 'right' ? 'ds-table__num' : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      style={{ width: column.width }}
                    >
                      {column.render ? column.render(row) : String(column.value?.(row) ?? '')}
                    </td>
                  ))}
                </tr>
              )
            })}
            {end < sorted.length && (
              <tr style={{ height: (sorted.length - end) * rowHeight }} aria-hidden="true" />
            )}
          </tbody>
        </table>
        {sorted.length === 0 && <div className="ds-table__empty">{emptyLabel}</div>}
      </div>
      {footer && <div className="ds-table__footer">{footer}</div>}
    </div>
  )
}
