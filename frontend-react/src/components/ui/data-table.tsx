import { useState } from "react"
import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table"
import { AlertCircle, Inbox, RefreshCw } from "lucide-react"
import { Button, Table, TBody, TD, TH, THead, TR } from "./primitives"
import { cn } from "../../lib/utils"

/**
 * The TanStack Table + shadcn pattern from shadcn-admin, which is the main
 * thing worth importing from that repo: sorting, selection and empty/error
 * handling in one place instead of every list page re-deriving it.
 *
 * Rows are supplied already filtered and paginated by the caller — this
 * component owns presentation, sorting and selection only, so it stays
 * correct for both offset pages and the events screen's keyset cursor.
 */
export function DataTable<TData>({
  columns,
  data,
  isLoading,
  error,
  emptyTitle = "没有数据",
  emptyDescription,
  onRetry,
  onRowClick,
  selectedKey,
  rowKey = (row: TData) => String((row as { id?: unknown }).id ?? ""),
  toolbar,
  initialSorting = [],
  className,
}: {
  columns: ColumnDef<TData, unknown>[]
  data: TData[]
  isLoading?: boolean
  error?: Error | null
  emptyTitle?: string
  emptyDescription?: string
  onRetry?: () => void
  onRowClick?: (row: TData) => void
  /** Highlights one row (detail panels). Mutually exclusive with selection. */
  selectedKey?: string | null
  rowKey?: (row: TData) => string
  toolbar?: React.ReactNode
  initialSorting?: SortingState
  className?: string
}) {
  const [sorting, setSorting] = useState<SortingState>(initialSorting)

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  const rows = table.getRowModel().rows

  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border border-border bg-card",
        className,
      )}
    >
      {toolbar && (
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2.5">
          {toolbar}
        </div>
      )}

      {error ? (
        <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
          <AlertCircle className="size-6 text-destructive" />
          <p className="text-sm font-medium">加载失败</p>
          <p className="max-w-md text-xs text-muted-foreground">
            {error.message}
          </p>
          {onRetry && (
            <Button variant="outline" size="sm" className="mt-1" onClick={onRetry}>
              <RefreshCw /> 重试
            </Button>
          )}
        </div>
      ) : isLoading ? (
        <Table>
          <SkeletonHeader columns={columns.length} />
          <TBody>
            {Array.from({ length: 6 }).map((_, i) => (
              <TR key={i}>
                {columns.map((_, c) => (
                  <TD key={c}>
                    <div className="h-3.5 w-full max-w-28 animate-pulse rounded bg-muted" />
                  </TD>
                ))}
              </TR>
            ))}
          </TBody>
        </Table>
      ) : rows.length === 0 ? (
        <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
          <Inbox className="size-6 text-muted-foreground" />
          <p className="text-sm font-medium">{emptyTitle}</p>
          {emptyDescription && (
            <p className="max-w-md text-xs text-muted-foreground">
              {emptyDescription}
            </p>
          )}
        </div>
      ) : (
        <Table>
          <THead>
            {table.getHeaderGroups().map((hg) => (
              <TR key={hg.id}>
                {hg.headers.map((h) => (
                  <TH
                    key={h.id}
                    className={cn(
                      h.column.getCanSort() && "cursor-pointer select-none",
                    )}
                    onClick={h.column.getToggleSortingHandler()}
                    aria-sort={
                      h.column.getIsSorted() === "asc"
                        ? "ascending"
                        : h.column.getIsSorted() === "desc"
                          ? "descending"
                          : "none"
                    }
                  >
                    <span className="inline-flex items-center gap-1">
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      <SortIndicator dir={h.column.getIsSorted()} />
                    </span>
                  </TH>
                ))}
              </TR>
            ))}
          </THead>
          <TBody>
            {rows.map((row) => {
              const key = rowKey(row.original)
              return (
                <TR
                  key={row.id}
                  onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                  className={cn(
                    onRowClick && "cursor-pointer",
                    selectedKey === key && "bg-accent/60",
                  )}
                  aria-selected={selectedKey === key || undefined}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TD key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TD>
                  ))}
                </TR>
              )
            })}
          </TBody>
        </Table>
      )}
    </div>
  )
}

function SortIndicator({ dir }: { dir: false | "asc" | "desc" }) {
  if (!dir) {
    return <span className="text-border">↕</span>
  }
  return (
    <span className="text-foreground">{dir === "asc" ? "↑" : "↓"}</span>
  )
}

function SkeletonHeader({ columns }: { columns: number }) {
  return (
    <THead>
      <TR>
        {Array.from({ length: Math.max(columns, 1) }).map((_, i) => (
          <TH key={i}>
            <div className="h-3 w-16 animate-pulse rounded bg-muted" />
          </TH>
        ))}
      </TR>
    </THead>
  )
}
