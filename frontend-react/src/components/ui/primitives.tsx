import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "../../lib/utils"

/* ---------------------------------------------------------------- Button */

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-lg text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        outline:
          "border border-border bg-background hover:bg-accent hover:text-accent-foreground",
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        destructive:
          "bg-destructive text-white hover:bg-destructive/90",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-10 rounded-lg px-6",
        icon: "size-9",
        "icon-sm": "size-7 rounded-md",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
)

export type ButtonProps = React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants>

export function Button({
  className,
  variant,
  size,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  )
}

/* ----------------------------------------------------------------- Badge */

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium leading-4",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary/10 text-primary",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "border-border text-muted-foreground",
        success: "border-transparent bg-status-online/12 text-status-online",
        warning: "border-transparent bg-status-degraded/15 text-status-degraded",
        danger: "border-transparent bg-status-offline/12 text-status-offline",
        muted: "border-transparent bg-muted text-muted-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  },
)

export type BadgeProps = React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants>

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

/* ------------------------------------------------------------------ Card */

export function Card({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-card text-card-foreground",
        className,
      )}
      {...props}
    />
  )
}

export function CardHeader({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 border-b border-border px-4 py-3",
        className,
      )}
      {...props}
    />
  )
}

export function CardTitle({
  className,
  ...props
}: React.ComponentProps<"h3">) {
  return (
    <h3 className={cn("text-sm font-semibold", className)} {...props} />
  )
}

export function CardContent({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return <div className={cn("p-4", className)} {...props} />
}

/* ----------------------------------------------------------------- Input */

export function Input({
  className,
  type = "text",
  ...props
}: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      className={cn(
        "h-8 w-full rounded-lg border border-input bg-background px-2.5 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  )
}

/* -------------------------------------------------------------- Textarea */

/**
 * Same border, focus ring and tokens as `Input` — deliberately the same class
 * string minus the fixed height, so a form that mixes the two does not show two
 * different borders.
 */
export function Textarea({
  className,
  ...props
}: React.ComponentProps<"textarea">) {
  return (
    <textarea
      className={cn(
        "w-full rounded-lg border border-input bg-background px-2.5 py-1.5 text-sm shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  )
}

/* ------------------------------------------------------- Select (native) */

export function Select({
  className,
  children,
  ...props
}: React.ComponentProps<"select">) {
  return (
    <select
      className={cn(
        "h-8 w-full appearance-none rounded-lg border border-input bg-background px-2.5 pr-7 text-sm shadow-xs transition-colors focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30",
        className,
      )}
      style={{
        backgroundImage:
          "url(\"data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")",
        backgroundRepeat: "no-repeat",
        backgroundPosition: "right 0.5rem center",
      }}
      {...props}
    >
      {children}
    </select>
  )
}

/* ---------------------------------------------------------------- Switch */

export function Switch({
  className,
  ...props
}: React.ComponentProps<"button">) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={props["aria-checked"]}
      className={cn(
        "inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
        props["aria-checked"] ? "bg-primary" : "bg-input",
        className,
      )}
      {...props}
    >
      <span
        className={cn(
          "pointer-events-none block size-4 rounded-full bg-background shadow transition-transform",
          props["aria-checked"] ? "translate-x-[18px]" : "translate-x-0.5",
        )}
      />
    </button>
  )
}

/* ----------------------------------------------------------------- Table */

export function Table({
  className,
  ...props
}: React.ComponentProps<"table">) {
  return (
    <div className="w-full overflow-x-auto">
      <table
        className={cn("w-full caption-bottom text-sm", className)}
        {...props}
      />
    </div>
  )
}

export function THead({
  className,
  ...props
}: React.ComponentProps<"thead">) {
  return (
    <thead
      className={cn("border-b border-border bg-muted/40", className)}
      {...props}
    />
  )
}

export function TBody({
  className,
  ...props
}: React.ComponentProps<"tbody">) {
  return (
    <tbody
      className={cn("divide-y divide-border [&_tr:last-child]:border-0", className)}
      {...props}
    />
  )
}

export function TR({
  className,
  ...props
}: React.ComponentProps<"tr">) {
  return (
    <tr
      className={cn("transition-colors hover:bg-muted/40", className)}
      {...props}
    />
  )
}

export function TH({
  className,
  ...props
}: React.ComponentProps<"th">) {
  return (
    <th
      className={cn(
        "h-9 px-3 text-left align-middle text-xs font-medium text-muted-foreground whitespace-nowrap",
        className,
      )}
      {...props}
    />
  )
}

export function TD({
  className,
  ...props
}: React.ComponentProps<"td">) {
  return (
    <td
      className={cn("px-3 py-2.5 align-middle whitespace-nowrap", className)}
      {...props}
    />
  )
}

/* ------------------------------------------------------------- Separator */

export function Separator({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      role="separator"
      className={cn("h-px w-full bg-border", className)}
      {...props}
    />
  )
}
