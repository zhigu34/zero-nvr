# ADR 0013 — Frontend design language: port shadcn tokens without framework change

Status: Accepted

Date: 2026-10-01

## Context

The V1 frontend baseline (`TECH_STACK.md`) is Vue 3 + TypeScript + Vite with a
hand-written CSS layer (`styles.css`, ~5.3k lines, two token families at the
top: a generic `--surface-*`/`--text-*`/`--accent` family and a
UniFi-Protect-inspired `--uf-*` family). Element Plus was recorded as
"initially unless a later UI-system decision replaces it" and was in fact never
adopted; every UI primitive is hand-rolled.

A component-library port was requested against
[shadcn-admin](https://github.com/satnaing/shadcn-admin). That template is
React 19 + TanStack Router/Query + Tailwind CSS v4 + shadcn/ui; its components
cannot execute inside a Vue app. Adopting its *framework* would be a full
frontend rewrite (~59k LOC including the playback master-clock, live preview
wall, hls.js integration, i18n and 270+ passing tests), contradicting the
frozen V1 baseline (ADR 0012 change-control) and discarding the already
landed componentization waves (`docs/frontend-refactor-audit.md`,
`docs/refactor-status.md`).

What is genuinely portable from shadcn-admin is its **design language**: the
default "neutral" palette expressed as oklch CSS custom properties
(`src/styles/theme.css`), the radius scale (`--radius: 0.625rem`), the
monochrome primary action color, and the sidebar + header app-shell layout.

## Decision

1. **Keep the Vue 3 baseline and the hand-written CSS layer.** No Tailwind, no
   shadcn-vue in this pass.
2. **Port the shadcn default-theme tokens verbatim** (oklch values, light and
   dark) into `styles.css` as the primary token source: `--background`,
   `--foreground`, `--card`, `--popover`, `--primary`, `--primary-foreground`,
   `--secondary(-foreground)`, `--muted(-foreground)`, `--destructive`,
   `--border`, `--input`, `--ring`, `--radius: 0.625rem`.
   shadcn's `--accent`/`--accent-foreground` are **deliberately not defined**
   because zero-nvr's legacy `--accent` token already means "primary action
   color"; defining shadcn's hover-tint under the same name would silently
   rebind 23 action-color call sites.
3. **Keep every legacy token name; remap only its value.** The two existing
   families continue to exist and now *derive from* the shadcn set
   (`--surface-base: var(--background)`, `--accent: var(--primary)`,
   `--uf-border: var(--border)`, status colors anchored to Tailwind green-600 /
   amber-600 / red-600 with shadcn dark-mode counterparts). All ~750 existing
   rules inherit the new palette without selector changes; dark mode continues
   to key off `<html data-theme="dark">`.
4. **Rebuild `AppShell` in the shadcn-admin sidebar pattern**: a 264 px
   labelled sidebar (brand row, grouped nav with labels, footer with theme /
   language / user row), collapsible to a 60 px icon rail with the previous
   dock behaviour preserved (tooltips, immersive routes), with the collapsed
   state persisted in localStorage.
5. Typography keeps the system-ui stack; Inter is **not** added because the
   deployment must not depend on external font delivery.

## Consequences

- The palette, radius scale, and shell layout visually align with shadcn-admin
  while every view keeps working through the unchanged legacy token names.
- Blue is no longer the action color; the action color is the shadcn
  near-black/near-white primary. Status semantics (success/warning/danger)
  keep their hues.
- Shared hand-rolled primitives (`DrawerDialog`, `NoticeBanner`, `StatusPill`,
  `ConfirmDialog`, …) stay; adopting shadcn-vue for individual primitives
  later is a per-component decision, not a baseline change.
- Modern-browser requirement rises slightly: token values use `oklch()` and
  `color-mix()`, already required by the WebRTC/HLS media stack.
- The dead global `.sidebar` / `.primary-nav` block in `styles.css` is left
  untouched here (only auth views' `.brand*` rules are shared and unaffected);
  its removal belongs to the Wave-4 CSS cleanup.
