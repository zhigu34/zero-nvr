/**
 * Formatters shared by the system view and its per-tab child components.
 *
 * These read the active locale and the `system.main.*` message catalogue, so
 * they cannot live in a plain utility module — but they were used by most of the
 * tabs. Without this they would either be prop-drilled from `SystemView` into
 * every tab, or copied into each one.
 */

import { useI18n } from "vue-i18n"

import { type StatusVariant } from "../components/ui/StatusPill.vue"
import { DATE_TIME_SECONDS, formatDateTime } from "../utils/format"

export function useSystemFormatters(): {
  stateLabel: (value: string) => string
  pretty: (value?: string | null) => string
  formatTime: (value: string | null) => string
  statusVariant: (value: string) => StatusVariant
} {
  const { locale, t, te } = useI18n({ useScope: "global" })

  /** Human label for a backend state token, falling back to the raw token. */
  function stateLabel(value: string): string {
    const key = `system.main.state_${value.toLowerCase()}`
    return te(key) ? t(key) : value
  }

  /** Title-case a machine token, turning separators into readable spacing. */
  function pretty(value?: string | null): string {
    if (!value) return "—"
    return String(value)
      .replaceAll("_", " ")
      .replaceAll(".", " · ")
      .replace(/\b\w/g, (match) => match.toUpperCase())
  }

  /**
   * Timestamps in this view always show seconds so an operator can correlate
   * them with the audit log.
   */
  function formatTime(value: string | null): string {
    return formatDateTime(value, DATE_TIME_SECONDS, { locale: locale.value })
  }

  /**
   * Map a backend status token to a pill variant.
   *
   * The backend reports health, delivery and audit outcomes with several
   * spellings of the same idea, so this accepts the superset.
   */
  function statusVariant(value: string): StatusVariant {
    const normalized = value.toUpperCase()
    if (
      normalized === "OK" ||
      normalized === "SENT" ||
      normalized === "COMPLETED" ||
      normalized === "VERIFIED"
    ) {
      return "ok"
    }
    if (normalized === "ERROR" || normalized === "FAILED") {
      return "error"
    }
    return "muted"
  }

  return { stateLabel, pretty, formatTime, statusVariant }
}
