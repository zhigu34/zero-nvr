import * as React from "react"
import { cn } from "../../lib/utils"
import { Button, Card } from "./primitives"

/* ------------------------------------------------------- Status / domain */

export type HealthTone = "online" | "offline" | "degraded" | "unknown"

const TONE: Record<HealthTone, string> = {
  online: "bg-status-online",
  offline: "bg-status-offline",
  degraded: "bg-status-degraded",
  unknown: "bg-status-unknown",
}

const TONE_TEXT: Record<HealthTone, string> = {
  online: "text-status-online",
  offline: "text-status-offline",
  degraded: "text-status-degraded",
  unknown: "text-status-unknown",
}

export function StatusDot({
  tone,
  className,
  pulse,
}: {
  tone: HealthTone
  className?: string
  pulse?: boolean
}) {
  return (
    <span className={cn("relative inline-flex size-2 shrink-0", className)}>
      {pulse && (
        <span
          className={cn(
            "absolute inline-flex size-full animate-ping rounded-full opacity-60",
            TONE[tone],
          )}
        />
      )}
      <span className={cn("relative inline-flex size-2 rounded-full", TONE[tone])} />
    </span>
  )
}

export function StatusLabel({
  tone,
  children,
  className,
}: {
  tone: HealthTone
  children: React.ReactNode
  className?: string
}) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs", className)}>
      <StatusDot tone={tone} />
      <span className={TONE_TEXT[tone]}>{children}</span>
    </span>
  )
}

/* ------------------------------------------------------------ PageHeader */

export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: string
  description?: string
  actions?: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-start justify-between gap-3",
        className,
      )}
    >
      <div className="min-w-0">
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
        {description && (
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}

/* ---------------------------------------------------------------- Toolbar */

export function Toolbar({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2 rounded-xl border border-border bg-card px-3 py-2.5",
        className,
      )}
    >
      {children}
    </div>
  )
}

export function ToolbarSpacer() {
  return <div className="ml-auto" />
}

/* -------------------------------------------------------------- StatCard */

export function StatCard({
  label,
  value,
  unit,
  hint,
  tone,
  icon,
  className,
}: {
  label: string
  value: React.ReactNode
  unit?: string
  hint?: string
  tone?: HealthTone
  icon?: React.ReactNode
  className?: string
}) {
  return (
    <Card className={cn("p-4", className)}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs text-muted-foreground">{label}</p>
        {icon && <span className="text-muted-foreground">{icon}</span>}
      </div>
      <p className="mt-2 flex items-baseline gap-1">
        <span
          className={cn(
            "text-2xl font-semibold tabular-nums tracking-tight",
            tone && TONE_TEXT[tone],
          )}
        >
          {value}
        </span>
        {unit && <span className="text-xs text-muted-foreground">{unit}</span>}
      </p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </Card>
  )
}

/* ------------------------------------------------------------- ProgressBar */

export function ProgressBar({
  value,
  tone = "online",
  className,
  showLabel,
}: {
  /** 0–100 */
  value: number
  tone?: HealthTone
  className?: string
  showLabel?: boolean
}) {
  const clamped = Math.max(0, Math.min(100, value))
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full transition-all", TONE[tone])}
          style={{ width: `${clamped}%` }}
        />
      </div>
      {showLabel && (
        <span className="w-10 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
          {clamped.toFixed(0)}%
        </span>
      )}
    </div>
  )
}

/* ------------------------------------------------------------- EmptyState */

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode
  title: string
  description?: string
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border px-6 py-12 text-center",
        className,
      )}
    >
      {icon && <div className="text-muted-foreground [&_svg]:size-7">{icon}</div>}
      <p className="text-sm font-medium">{title}</p>
      {description && (
        <p className="max-w-md text-xs text-muted-foreground">{description}</p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

/* ------------------------------------------------------------- KeyValue */

export function KeyValue({
  label,
  children,
  className,
}: {
  label: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4 py-2", className)}>
      <span className="shrink-0 text-xs text-muted-foreground">{label}</span>
      <span className="min-w-0 text-right text-sm">{children}</span>
    </div>
  )
}

/* --------------------------------------------------------- PrototypeNote */

/**
 * Every page in this build is a static mock. This banner keeps that honest
 * instead of letting a filled-in screen read as a working feature.
 */
export function PrototypeNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-dashed border-border bg-muted/40 px-3 py-2">
      <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-status-degraded" />
      <p className="text-xs leading-relaxed text-muted-foreground">{children}</p>
    </div>
  )
}

/* ---------------------------------------------------------------- Sections */

export function Section({
  title,
  description,
  actions,
  children,
  className,
}: {
  title: string
  description?: string
  actions?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={cn("space-y-3", className)}>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">{title}</h3>
          {description && (
            <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
          )}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {children}
    </section>
  )
}

/* ------------------------------------------------------------------- Tabs */

export function Tabs({
  tabs,
  active,
  onChange,
  className,
}: {
  // `readonly` so a caller can declare its tab list `as const` — the keys
  // are used for comparison, never mutated.
  tabs: readonly { key: string; label: string; count?: number }[]
  active: string
  onChange: (key: string) => void
  className?: string
}) {
  return (
    <div
      role="tablist"
      className={cn(
        "flex items-center gap-1 overflow-x-auto border-b border-border",
        className,
      )}
    >
      {tabs.map((t) => (
        <button
          key={t.key}
          role="tab"
          type="button"
          aria-selected={active === t.key}
          onClick={() => onChange(t.key)}
          className={cn(
            "-mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors",
            active === t.key
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          {t.label}
          {t.count !== undefined && (
            <span className="rounded bg-muted px-1 text-[10px] tabular-nums text-muted-foreground">
              {t.count}
            </span>
          )}
        </button>
      ))}
    </div>
  )
}

/* -------------------------------------------------------------- Segmented */

export function Segmented({
  options,
  value,
  onChange,
  className,
  ariaLabel,
}: {
  options: { value: string; label: React.ReactNode }[]
  value: string
  onChange: (value: string) => void
  className?: string
  /**
   * Names the group. A row of mutually exclusive buttons is one control, and
   * without a name a screen reader announces three unrelated buttons — which
   * matters most where two of them share labels, as the notification secret
   * fields do.
   */
  ariaLabel?: string
}) {
  return (
    <div
      role={ariaLabel ? "group" : undefined}
      aria-label={ariaLabel}
      className={cn(
        "inline-flex items-center gap-0.5 rounded-lg border border-border bg-background p-0.5",
        className,
      )}
    >
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={cn(
            "inline-flex h-7 items-center gap-1 rounded-md px-2.5 text-xs font-medium transition-colors [&_svg]:size-3.5",
            value === o.value
              ? "bg-secondary text-secondary-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

/* -------------------------------------------------------------- Checkbox */

export function Checkbox({
  className,
  ...props
}: React.ComponentProps<"input">) {
  return (
    <input
      type="checkbox"
      className={cn(
        "size-3.5 shrink-0 cursor-pointer rounded border-input accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30",
        className,
      )}
      {...props}
    />
  )
}

/* -------------------------------------------------------------- Callout */

export function Callout({
  tone = "degraded",
  title,
  children,
  className,
}: {
  tone?: HealthTone
  title?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex items-start gap-2.5 rounded-lg border px-3 py-2.5",
        tone === "degraded" && "border-status-degraded/30 bg-status-degraded/8",
        tone === "offline" && "border-status-offline/30 bg-status-offline/8",
        tone === "online" && "border-status-online/30 bg-status-online/8",
        className,
      )}
    >
      <StatusDot tone={tone} className="mt-1.5" />
      <div className="min-w-0 text-xs leading-relaxed">
        {title && <p className="font-medium">{title}</p>}
        <div className={cn(title && "mt-0.5", "text-muted-foreground")}>
          {children}
        </div>
      </div>
    </div>
  )
}

/* ----------------------------------------------------------- RowActions */

export function RowActions({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-end gap-1">
      {children}
      <Button variant="ghost" size="icon-sm" title="更多操作">
        <span aria-hidden>···</span>
      </Button>
    </div>
  )
}

/* ------------------------------------------------------------------- Form */

export function Field({
  label,
  hint,
  htmlFor,
  children,
  className,
}: {
  label: string
  hint?: string
  htmlFor?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 border-b border-border py-3 last:border-0",
        className,
      )}
    >
      <div className="min-w-0 max-w-md">
        <label htmlFor={htmlFor} className="text-sm font-medium leading-tight">
          {label}
        </label>
        {hint && (
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {hint}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">{children}</div>
    </div>
  )
}

export function FormActions({
  dirty,
  onReset,
  className,
}: {
  dirty?: boolean
  onReset?: () => void
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-end gap-2 border-t border-border px-4 py-3",
        className,
      )}
    >
      {dirty && (
        <span className="mr-auto text-xs text-status-degraded">有未保存的修改</span>
      )}
      <Button variant="ghost" size="sm" onClick={onReset}>
        重置
      </Button>
      <Button size="sm" disabled={!dirty}>
        保存
      </Button>
    </div>
  )
}

/* ------------------------------------------------------------------ Misc */

export function Mono({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-mono text-xs tabular-nums text-muted-foreground">
      {children}
    </span>
  )
}

export function Swatch() {
  return (
    <div className="flex items-center gap-0.5">
      {["#3f3f46", "#71717a", "#a1a1aa", "#d4d4d8", "#e4e4e7", "#f4f4f5"].map(
        (c) => (
          <span
            key={c}
            className="size-4 rounded border border-border"
            style={{ backgroundColor: c }}
          />
        ),
      )}
    </div>
  )
}
