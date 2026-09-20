import { readonly, ref } from "vue"

export type ThemePreference = "system" | "light" | "dark"
export type ResolvedTheme = "light" | "dark"

const STORAGE_KEY = "zero-nvr.theme"
const themePreference = ref<ThemePreference>("system")
const resolvedTheme = ref<ResolvedTheme>("light")

let mediaQuery: MediaQueryList | null = null
let initialized = false

function isThemePreference(value: string | null): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark"
}

function readStoredPreference(): ThemePreference {
  const stored = window.localStorage.getItem(STORAGE_KEY)
  return isThemePreference(stored) ? stored : "system"
}

function resolveTheme(preference: ThemePreference): ResolvedTheme {
  if (preference === "light" || preference === "dark") return preference
  return mediaQuery?.matches ? "dark" : "light"
}

function applyTheme(): void {
  if (typeof document === "undefined") return

  resolvedTheme.value = resolveTheme(themePreference.value)
  document.documentElement.dataset.theme = resolvedTheme.value
  document.documentElement.dataset.themePreference = themePreference.value
  document.documentElement.style.colorScheme = resolvedTheme.value
}

function handleSystemThemeChange(): void {
  if (themePreference.value === "system") applyTheme()
}

export function initializeTheme(): void {
  if (initialized || typeof window === "undefined") return

  initialized = true
  mediaQuery = window.matchMedia("(prefers-color-scheme: dark)")
  themePreference.value = readStoredPreference()
  mediaQuery.addEventListener("change", handleSystemThemeChange)
  applyTheme()
}

export function setTheme(preference: ThemePreference): void {
  themePreference.value = preference
  window.localStorage.setItem(STORAGE_KEY, preference)
  applyTheme()
}

export function useTheme() {
  return {
    themePreference: readonly(themePreference),
    resolvedTheme: readonly(resolvedTheme),
    setTheme
  }
}
